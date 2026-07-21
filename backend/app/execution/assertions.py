from typing import Any

from app.execution.context import get_path


class AssertionFailure(Exception):
    pass


def evaluate_assertions(response: dict[str, Any], assertions: list[dict[str, Any]]) -> None:
    for rule in assertions:
        source = str(rule.get("source", ""))
        operator = str(rule.get("operator", "equals"))
        expected = rule.get("expected", True if operator == "exists" else None)
        try:
            actual = get_path(response, source)
        except KeyError:
            if operator == "exists" and expected is False:
                continue
            raise AssertionFailure(f"Assertion source not found: {source}") from None

        passed = _compare(actual, operator, expected)
        if not passed:
            raise AssertionFailure(
                f"Assertion failed: {source} {operator} {expected!r}; actual={actual!r}"
            )


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


def _compare(actual: Any, operator: str, expected: Any) -> bool:
    if operator == "equals":
        return actual == expected
    if operator == "not_equals":
        return actual != expected
    if operator == "contains":
        return expected in actual
    if operator == "exists":
        return bool(expected)
    if operator == "gt":
        return actual > expected
    if operator == "gte":
        return actual >= expected
    if operator == "lt":
        return actual < expected
    if operator == "lte":
        return actual <= expected
    raise ValueError(f"Unsupported assertion operator: {operator}")
