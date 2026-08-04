from typing import Any


def default_success_contract(protocol: str = "http") -> dict[str, Any]:
    """Return the standard success contract for a newly created API."""
    if protocol == "ws":
        return {
            "messages": {"min": 1},
            "body_schema": {},
        }
    return {
        "status_codes": {"min": 200, "max": 299},
        "body_schema": {
            "type": "object",
            "required": ["code", "data"],
            "properties": {"code": {"const": 0}},
        },
    }
