from typing import Any

from sqlalchemy.orm import Session

from app.execution.assertions import evaluate_assertion_rules
from app.execution.expression import evaluate_expression
from app.models import ApiDefinition, AssertionDefinition


def definition_to_rule(
    definition: AssertionDefinition, binding: dict[str, Any] | None = None
) -> dict[str, Any]:
    binding = binding or {}
    return {
        "assertion_id": definition.id,
        "name": definition.name,
        "engine": definition.engine,
        "config": definition.config,
        "default_params": definition.default_params,
        "params": binding.get("params", {}),
        "severity": binding.get("severity", definition.severity),
        "message": binding.get("message", definition.message),
        "enabled": binding.get("enabled", True),
    }


def resolve_success_assertion_rule(
    session: Session,
    assertion_id: str,
    *,
    project_id: str,
) -> dict[str, Any]:
    definition = session.get(AssertionDefinition, assertion_id)
    if not definition or definition.project_id != project_id:
        raise ValueError(f"成功条件不存在或不属于当前项目：{assertion_id}")
    return definition_to_rule(definition)


def validate_api_response(
    session: Session,
    api: ApiDefinition,
    *,
    request: dict[str, Any],
    response: dict[str, Any],
    context: dict[str, Any],
    step_assertions: list[dict[str, Any]] | None = None,
    step_disabled_assertion_ids: list[str] | None = None,
) -> dict[str, Any]:
    variant: dict[str, Any] | None = None
    rules: list[dict[str, Any]] = []
    response_unpack = api.response_unpack if isinstance(api.response_unpack, dict) else {}

    # A directly linked success condition is the source of truth.
    # Keep success_contract only as a compatibility fallback for older APIs.
    if api.success_assertion_id:
        rules.append(
            resolve_success_assertion_rule(
                session, api.success_assertion_id, project_id=api.project_id
            )
        )
    elif api.success_contract:
        rules.extend(
            _success_contract_rules(api.protocol, api.success_contract, response_unpack)
        )
    else:
        # Legacy response variants remain readable for existing projects.
        variant, match_error = _select_variant(api.response_variants, request, response, context)
        if api.response_variants and not variant:
            result = {
                "assertion_id": "system:response-variant",
                "name": "成功响应契约匹配",
                "engine": "expression",
                "passed": False,
                "severity": "success",
                "message": match_error or "响应未匹配已配置的成功契约",
                "actual": None,
            }
            return {"passed": False, "variant": None, "results": [result]}
        if not api.response_variants and api.protocol == "http":
            rules.append(
                {
                    "assertion_id": "system:http-success-status",
                    "name": "HTTP 成功状态码",
                    "engine": "expression",
                    "config": {"expression": "response.status_code >= 200 and response.status_code < 300"},
                    "severity": "success",
                    "message": "HTTP 状态码必须在 200–299 范围内",
                    "mandatory": True,
                }
            )
        if variant and variant.get("schema") is not None:
            rules.append(
                {
                    "assertion_id": f"variant:{variant.get('name', 'unnamed')}:schema",
                    "name": f"{variant.get('name', '成功响应')} JSON Schema",
                    "engine": "json_schema",
                    "config": {
                        "source": "payload" if response_unpack.get("enabled") else "body",
                        "schema": variant["schema"],
                    },
                    "severity": "success",
                }
            )
        if variant:
            rules.extend(variant.get("assertions", []))

    rules.extend(step_assertions or [])

    disabled = set(variant.get("disabled_assertion_ids", []) if variant else [])
    disabled.update(step_disabled_assertion_ids or [])
    mandatory_ids = {
        "system:http-success-status",
        "system:success-status",
        "system:success-messages",
        "system:success-body-schema",
    }
    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for index, rule in enumerate(rules):
        assertion_id = str(rule.get("assertion_id") or rule.get("id") or f"inline:{index}")
        if assertion_id in disabled and not rule.get("mandatory", False):
            continue
        normalized = {**rule, "assertion_id": assertion_id}
        if assertion_id in mandatory_ids:
            if assertion_id in merged:
                continue
            normalized["mandatory"] = True
        if assertion_id not in merged:
            order.append(assertion_id)
        merged[assertion_id] = normalized
    validation = evaluate_assertion_rules(
        response,
        [merged[item] for item in order],
        request=request,
        context=context,
    )
    validation["variant"] = variant.get("name") if variant else None
    validation["success_contract"] = bool(api.success_contract and not api.success_assertion_id)
    validation["success_assertion_id"] = api.success_assertion_id
    return validation


def _success_contract_rules(
    protocol: str,
    contract: dict[str, Any],
    response_unpack: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = []
    if protocol == "http":
        status_codes = contract.get("status_codes", {})
        minimum = int(status_codes.get("min", 200))
        maximum = int(status_codes.get("max", 299))
        rules.append(
            {
                "assertion_id": "system:success-status",
                "name": "成功状态码",
                "engine": "expression",
                "config": {
                    "expression": (
                        f"response.status_code >= {minimum} "
                        f"and response.status_code <= {maximum}"
                    )
                },
                "severity": "success",
                "message": f"HTTP 状态码必须在 {minimum}–{maximum} 范围内",
                "mandatory": True,
            }
        )
    else:
        messages = contract.get("messages", {})
        minimum_messages = int(messages.get("min", 1)) if isinstance(messages, dict) else 1
        rules.append(
            {
                "assertion_id": "system:success-messages",
                "name": "成功消息数量",
                "engine": "expression",
                "config": {"expression": f"len(response.messages) >= {minimum_messages}"},
                "severity": "success",
                "message": f"WebSocket 至少需要收到 {minimum_messages} 条消息",
                "mandatory": True,
            }
        )
    schema = contract.get("body_schema")
    if schema:
        source = "payload" if isinstance(response_unpack, dict) and response_unpack.get("enabled") else "body"
        rules.append(
            {
                "assertion_id": "system:success-body-schema",
                "name": "成功响应体结构",
                "engine": "json_schema",
                "config": {"source": source, "schema": schema},
                "severity": "success",
                "message": "响应体不符合成功契约定义",
                "mandatory": True,
            }
        )
    return rules


def _select_variant(
    variants: list[dict[str, Any]],
    request: dict[str, Any],
    response: dict[str, Any],
    context: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    errors: list[str] = []
    for variant in variants:
        expression = str(variant.get("match", ""))
        try:
            if evaluate_expression(
                expression,
                {"response": response, "request": request, "context": context, "params": {}},
            ):
                return variant, None
        except Exception as exc:
            errors.append(f"分支 {variant.get('name', '未命名')}：{exc}")
    return None, "; ".join(errors) or None
