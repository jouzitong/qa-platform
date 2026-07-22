from typing import Any

from sqlalchemy.orm import Session

from app.execution.assertions import evaluate_assertion_rules
from app.execution.expression import evaluate_expression
from app.models import ApiDefinition, AssertionDefinition, AssertionProfile


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


def resolve_profile_rules(
    session: Session,
    profile_ids: list[str],
    *,
    project_id: str,
    protocol: str,
) -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = []
    for profile_id in profile_ids:
        profile = session.get(AssertionProfile, profile_id)
        if not profile or profile.project_id != project_id or profile.protocol != protocol:
            raise ValueError(f"Invalid assertion profile for this API: {profile_id}")
        for binding in profile.bindings:
            if not binding.get("enabled", True):
                continue
            definition = session.get(AssertionDefinition, binding.get("assertion_id"))
            if not definition or definition.project_id != project_id:
                raise ValueError(
                    f"Assertion definition not found in this project: {binding.get('assertion_id')}"
                )
            rules.append(definition_to_rule(definition, binding))
    return rules


def validate_api_response(
    session: Session,
    api: ApiDefinition,
    *,
    request: dict[str, Any],
    response: dict[str, Any],
    context: dict[str, Any],
    step_assertions: list[dict[str, Any]] | None = None,
    step_disabled_assertion_ids: list[str] | None = None,
    allow_error_status: bool = False,
) -> dict[str, Any]:
    variant, match_error = _select_variant(api.response_variants, request, response, context)
    if api.response_variants and not variant:
        result = {
            "assertion_id": "system:response-variant",
            "name": "响应分支匹配",
            "engine": "expression",
            "passed": False,
            "severity": "error",
            "message": match_error or "响应未匹配任何已配置分支",
            "actual": None,
        }
        return {"passed": False, "variant": None, "results": [result]}

    profile_ids: list[str] = []
    if api.assertion_profile_id:
        profile_ids.append(api.assertion_profile_id)
    if variant:
        profile_ids.extend(str(item) for item in variant.get("assertion_profile_ids", []))
    rules = resolve_profile_rules(
        session, profile_ids, project_id=api.project_id, protocol=api.protocol
    )

    if not api.response_variants and api.protocol == "http" and not allow_error_status:
        rules.insert(
            0,
            {
                "assertion_id": "system:http-status",
                "name": "HTTP 状态码小于 400",
                "engine": "expression",
                "config": {"expression": "response.status_code < 400"},
                "severity": "error",
                "message": "HTTP 状态码必须小于 400",
            },
        )
    if variant and variant.get("schema") is not None:
        rules.append(
            {
                "assertion_id": f"variant:{variant.get('name', 'unnamed')}:schema",
                "name": f"{variant.get('name', '响应分支')} JSON Schema",
                "engine": "json_schema",
                "config": {"source": "body", "schema": variant["schema"]},
                "severity": "error",
            }
        )
    if variant:
        rules.extend(variant.get("assertions", []))
    rules.extend(step_assertions or [])

    disabled = set(variant.get("disabled_assertion_ids", []) if variant else [])
    disabled.update(step_disabled_assertion_ids or [])
    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for index, rule in enumerate(rules):
        assertion_id = str(rule.get("assertion_id") or rule.get("id") or f"inline:{index}")
        if assertion_id in disabled:
            continue
        normalized = {**rule, "assertion_id": assertion_id}
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
    return validation


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
