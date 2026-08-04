import re
from copy import deepcopy
from typing import Any
from urllib.parse import quote

from app.execution.expression import evaluate_expression

TEMPLATE_PATTERN = re.compile(r"{{\s*([\w.-]+)\s*}}")
RANDOM_TEMPLATE_PATTERN = re.compile(
    r"{{\s*(random\.(?:uuid|string|int|integer|float)\s*\([^{}]*\))\s*}}"
)
PATH_PARAMETER_PATTERN = re.compile(r"(?<!{)\{([A-Za-z_][A-Za-z0-9_]*)}(?!})")
COLON_PATH_PARAMETER_PATTERN = re.compile(r"(?<=/):([A-Za-z_][A-Za-z0-9_]*)")


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

    random_match = RANDOM_TEMPLATE_PATTERN.fullmatch(value)
    if random_match:
        return evaluate_expression(random_match.group(1), context)

    value = RANDOM_TEMPLATE_PATTERN.sub(
        lambda match: str(evaluate_expression(match.group(1), context)), value
    )
    full_match = TEMPLATE_PATTERN.fullmatch(value)
    if full_match:
        return deepcopy(get_path(context, full_match.group(1)))

    return TEMPLATE_PATTERN.sub(lambda match: str(get_path(context, match.group(1))), value)


def render_path_parameters(
    value: str,
    context: dict[str, Any],
    explicit: dict[str, Any] | None = None,
) -> str:
    """Render REST-style ``{id}`` or ``:id`` segments with URL-safe values."""
    values = explicit or {}

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        try:
            raw = values[name] if name in values else get_path(context, name)
        except KeyError:
            raise ValueError(f"Missing path parameter: {name}") from None
        return quote(str(raw), safe="")

    rendered = PATH_PARAMETER_PATTERN.sub(replace, value)
    return COLON_PATH_PARAMETER_PATTERN.sub(replace, rendered)


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result
