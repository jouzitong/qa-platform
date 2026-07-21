import re
from copy import deepcopy
from typing import Any

TEMPLATE_PATTERN = re.compile(r"{{\s*([\w.-]+)\s*}}")


def get_path(value: Any, path: str) -> Any:
    current = value
    if not path:
        return current
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            raise KeyError(f"Context path not found: {path}")
    return current


def render(value: Any, context: dict[str, Any]) -> Any:
    if isinstance(value, dict):
        return {key: render(item, context) for key, item in value.items()}
    if isinstance(value, list):
        return [render(item, context) for item in value]
    if not isinstance(value, str):
        return value

    full_match = TEMPLATE_PATTERN.fullmatch(value)
    if full_match:
        return deepcopy(get_path(context, full_match.group(1)))

    return TEMPLATE_PATTERN.sub(lambda match: str(get_path(context, match.group(1))), value)


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result
