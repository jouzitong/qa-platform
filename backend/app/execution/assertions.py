from typing import Any

from jsonschema import Draft202012Validator

from app.execution.context import get_path
from app.execution.expression import evaluate_expression


class AssertionFailure(Exception):
    pass


def evaluate_assertion_rules(
    response: dict[str, Any],
    assertions: list[dict[str, Any]],
    *,
    request: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    results = [
        _evaluate_rule(response, request or {}, context or {}, rule)
        for rule in assertions
        if rule.get("enabled", True)
    ]
    passed = all(item["passed"] or item["severity"] == "warning" for item in results)
    return {"passed": passed, "results": results}


def evaluate_assertions(response: dict[str, Any], assertions: list[dict[str, Any]]) -> None:
    """Compatibility entry point for existing callers using inline path assertions."""
    validation = evaluate_assertion_rules(response, assertions)
    if not validation["passed"]:
        failures = [
            item["message"]
            for item in validation["results"]
            if not item["passed"] and item["severity"] == "error"
        ]
        raise AssertionFailure("; ".join(failures))


def _evaluate_rule(
    response: dict[str, Any],
    request: dict[str, Any],
    context: dict[str, Any],
    rule: dict[str, Any],
) -> dict[str, Any]:
    engine = str(rule.get("engine", "path"))
    config = rule.get("config") if isinstance(rule.get("config"), dict) else rule
    assertion_id = str(rule.get("assertion_id") or rule.get("id") or "inline")
    name = str(rule.get("name") or config.get("source") or engine)
    severity = str(rule.get("severity", "error"))
    params = {**rule.get("default_params", {}), **rule.get("params", {})}
    actual: Any = None
    detail = ""
    try:
        if engine == "path":
            actual, passed = _evaluate_path(response, config)
        elif engine == "json_schema":
            source = str(config.get("source", "body"))
            actual = get_path(response, source) if source else response
            errors = sorted(
                Draft202012Validator(config.get("schema", {})).iter_errors(actual),
                key=lambda error: list(error.absolute_path),
            )
            passed = not errors
            if errors:
                detail = "; ".join(
                    f"{'.'.join(map(str, error.absolute_path)) or '$'}: {error.message}"
                    for error in errors[:10]
                )
        elif engine == "expression":
            expression = str(config.get("expression", ""))
            actual = evaluate_expression(
                expression,
                {
                    "response": response,
                    "request": request,
                    "context": context,
                    "params": params,
                },
            )
            passed = bool(actual)
        else:
            raise ValueError(f"Unsupported assertion engine: {engine}")
    except Exception as exc:
        passed = False
        detail = str(exc)

    configured_message = str(rule.get("message", ""))
    if passed:
        message = configured_message or "断言通过"
    else:
        message = configured_message or detail or f"断言失败：{name}"
        if configured_message and detail:
            message = f"{configured_message}（{detail}）"
    return {
        "assertion_id": assertion_id,
        "name": name,
        "engine": engine,
        "passed": passed,
        "severity": severity,
        "message": message,
        "actual": actual,
    }


def _evaluate_path(response: dict[str, Any], config: dict[str, Any]) -> tuple[Any, bool]:
    source = str(config.get("source", ""))
    operator_name = str(config.get("operator", "equals"))
    expected = config.get("expected", True if operator_name == "exists" else None)
    try:
        actual = get_path(response, source)
    except KeyError:
        if operator_name == "exists":
            return None, expected is False
        raise ValueError(f"Assertion source not found: {source}") from None
    return actual, _compare(actual, operator_name, expected)


def extract_values(response: dict[str, Any], extractors: list[dict[str, Any]]) -> dict[str, Any]:
    extracted: dict[str, Any] = {}
    for extractor in extractors:
        name = extractor.get("name")
        source = extractor.get("source")
        if not name or not source:
            raise ValueError("Extractor requires name and source")
        try:
            extracted[str(name)] = get_path(response, str(source))
        except KeyError:
            if "default" in extractor:
                extracted[str(name)] = extractor["default"]
            else:
                raise
    return extracted


def _compare(actual: Any, operator_name: str, expected: Any) -> bool:
    if operator_name == "equals":
        return actual == expected
    if operator_name == "not_equals":
        return actual != expected
    if operator_name == "contains":
        return expected in actual
    if operator_name == "exists":
        return bool(expected)
    if operator_name == "gt":
        return actual > expected
    if operator_name == "gte":
        return actual >= expected
    if operator_name == "lt":
        return actual < expected
    if operator_name == "lte":
        return actual <= expected
    raise ValueError(f"Unsupported assertion operator: {operator_name}")
