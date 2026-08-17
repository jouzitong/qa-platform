"""Canonical qa-platform API parameter construction helpers.

The qa-platform executor understands four request locations: ``path``,
``query``, ``header`` and JSON ``body``.  Body objects use a recursive
``children`` tree so nested DTO/schema fields remain executable without
inventing dotted parameter paths.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from copy import deepcopy
from typing import Any
from urllib.parse import urlsplit

PARAMETER_LOCATIONS = ("path", "query", "header", "body")
PARAMETER_TYPES = ("string", "integer", "number", "boolean", "object", "array")
PATH_BRACE_RE = re.compile(r"(?<!\{)\{(?P<name>[A-Za-z_][A-Za-z0-9_]*)\}(?!\})")
PATH_COLON_RE = re.compile(r"(?<=/):(?P<name>[A-Za-z_][A-Za-z0-9_]*)")
SENSITIVE_NAME_RE = re.compile(
    r"(?:authorization|cookie|password|passwd|secret|token|api[_-]?key|credential)",
    re.IGNORECASE,
)
_MISSING = object()


def parameter_type(value: Any, *, schema: dict[str, Any] | None = None) -> str:
    """Map source/OpenAPI types to the six types the qa-platform UI executes."""
    schema = schema or {}
    raw = str(value or schema.get("type") or "").strip().lower()
    format_value = str(schema.get("format") or "").strip().lower()
    raw = raw.removeprefix("?")
    if not raw and any(
        key in schema for key in ("properties", "additionalProperties", "allOf")
    ):
        return "object"
    if raw.startswith("optional<") and raw.endswith(">"):
        return parameter_type(raw[len("optional<") : -1], schema={})
    generic_base = raw.split("<", 1)[0].strip()
    simple_type = generic_base.rsplit(".", 1)[-1]
    if raw.endswith("[]"):
        return "array"
    if simple_type in {"list", "set", "collection", "iterable", "slice"}:
        return "array"
    if simple_type in {"map", "hashmap", "linkedhashmap", "dict"}:
        return "object"
    if simple_type in {"integer", "int", "int32", "int64", "long", "short", "byte", "biginteger"}:
        return "integer"
    if simple_type in {"number", "float", "double", "decimal", "bigdecimal"}:
        return "number"
    if simple_type in {"boolean", "bool"}:
        return "boolean"
    if simple_type in {"array", "list", "set", "collection", "slice"} or raw.endswith("[]"):
        return "array"
    if simple_type in {"object", "map", "dict", "json", "jsonnode", "any"}:
        return "object"
    if format_value in {"int32", "int64"}:
        return "integer"
    if format_value in {"float", "double"}:
        return "number"
    return "string"


def path_parameter_names(path: str) -> list[str]:
    parsed = urlsplit(path)
    value = parsed.path if parsed.scheme or parsed.netloc else path.split("?", 1)[0]
    names: list[str] = []
    for pattern in (PATH_BRACE_RE, PATH_COLON_RE):
        for match in pattern.finditer(value):
            name = match.group("name")
            if name not in names:
                names.append(name)
    return names


def _is_sensitive(name: str) -> bool:
    return bool(SENSITIVE_NAME_RE.search(name))


def _description(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _uses_chinese(language: str | None) -> bool:
    return str(language or "").lower().startswith("zh")


def _fallback_description(name: str, location: str, type_name: str, language: str | None) -> str:
    if _uses_chinese(language):
        labels = {"path": "路径", "query": "查询", "header": "请求头", "body": "请求体"}
        return f"{labels.get(location, '请求')}参数 `{name}`（{type_name}）。"
    labels = {"path": "path", "query": "query", "header": "header", "body": "request body"}
    return f"{labels.get(location, 'request')} parameter `{name}` ({type_name})."


def _has_value(value: Any) -> bool:
    return value is not _MISSING and value is not None and (
        not isinstance(value, str) or bool(value.strip())
    )


def _safe_variable_example(name: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_]+", "_", name).strip("_") or "secret"
    return f"{{{{ {normalized} }}}}"


def _fallback_example(name: str, type_name: str, schema: dict[str, Any], language: str | None) -> Any:
    enum = schema.get("enum")
    if isinstance(enum, list):
        for value in enum:
            if value is not None and (not isinstance(value, str) or value.strip()):
                return deepcopy(value)
    if type_name == "integer":
        minimum = schema.get("minimum")
        return int(minimum) if isinstance(minimum, (int, float)) and not isinstance(minimum, bool) else 1
    if type_name == "number":
        minimum = schema.get("minimum")
        return float(minimum) if isinstance(minimum, (int, float)) and not isinstance(minimum, bool) else 1.0
    if type_name == "boolean":
        return True
    if type_name == "array":
        return []
    if type_name == "object":
        return {}
    format_value = str(schema.get("format") or "").lower()
    if format_value == "uuid":
        return "00000000-0000-4000-8000-000000000001"
    if format_value == "email":
        return "user@example.com"
    if format_value == "date":
        return "2026-01-01"
    if format_value in {"date-time", "datetime"}:
        return "2026-01-01T00:00:00Z"
    lowered_name = name.lower()
    if lowered_name.endswith("id") or lowered_name == "id":
        return "example-id"
    if "name" in lowered_name:
        return "example-name" if not _uses_chinese(language) else "示例名称"
    return "example" if not _uses_chinese(language) else "示例值"


def _object_schema_parts(schema: dict[str, Any]) -> tuple[dict[str, Any], set[str]]:
    """Merge object properties and required names from nested ``allOf`` branches."""
    properties: dict[str, Any] = {}
    required_names: set[str] = set()

    own_properties = schema.get("properties")
    if isinstance(own_properties, dict):
        properties.update(own_properties)
    required_names.update(
        str(value) for value in schema.get("required", []) if isinstance(value, str)
    )

    branches = schema.get("allOf")
    if isinstance(branches, list):
        for branch in branches:
            if not isinstance(branch, dict):
                continue
            branch_properties, branch_required = _object_schema_parts(branch)
            properties.update(branch_properties)
            required_names.update(branch_required)
    return properties, required_names


def _sample_from_examples(value: Any) -> Any:
    if isinstance(value, dict):
        for item in value.values():
            if isinstance(item, dict) and "value" in item:
                return deepcopy(item["value"])
    elif isinstance(value, list) and value:
        return deepcopy(value[0])
    return _MISSING


def parameter_from_schema(
    name: str,
    location: str,
    schema: dict[str, Any] | None = None,
    *,
    required: bool = False,
    description: str = "",
    default: Any = _MISSING,
    example: Any = _MISSING,
    language: str | None = "en",
) -> dict[str, Any] | None:
    """Build one safe executable parameter from a JSON-schema-like object."""
    normalized_location = str(location or "query").lower()
    normalized_name = str(name or "").strip()
    if normalized_location not in PARAMETER_LOCATIONS or not normalized_name:
        return None
    schema = schema if isinstance(schema, dict) else {}
    resolved_type = parameter_type(schema=schema, value=schema.get("type"))
    resolved_description = _description(description or schema.get("description"))
    if not resolved_description:
        resolved_description = _fallback_description(
            normalized_name, normalized_location, resolved_type, language
        )
    result: dict[str, Any] = {
        "name": normalized_name,
        "in": normalized_location,
        "type": resolved_type,
        "required": bool(required) or normalized_location == "path",
        "description": resolved_description,
    }
    if default is _MISSING and "default" in schema:
        default = schema["default"]
    if example is _MISSING:
        if "example" in schema:
            example = schema["example"]
        else:
            example = _sample_from_examples(schema.get("examples"))
    if _is_sensitive(normalized_name):
        # Keep a runnable, non-secret placeholder even though defaults and
        # source examples must never carry credentials into the artifact.
        result["example"] = _safe_variable_example(normalized_name)
    else:
        if default is not _MISSING and default is not None:
            result["default"] = deepcopy(default)
        result["example"] = (
            deepcopy(example)
            if _has_value(example)
            else _fallback_example(normalized_name, resolved_type, schema, language)
        )
    for field in (
        "format",
        "enum",
        "pattern",
        "minimum",
        "maximum",
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
        "uniqueItems",
    ):
        if field in schema:
            result[field] = deepcopy(schema[field])
    if resolved_type == "object":
        children = parameters_from_object_schema(schema, language=language)
        if children:
            # ``in`` belongs to the root executable parameter.  Descendants
            # inherit the root location and therefore stay compact in the
            # public contract.
            result["children"] = [
                {
                    key: deepcopy(value)
                    for key, value in child.items()
                    if key != "in"
                }
                for child in children
            ]
    if result["type"] == "array" and isinstance(schema.get("items"), dict):
        item_type = parameter_type(schema=schema["items"], value=schema["items"].get("type"))
        result["items"] = {"type": item_type}
    return result


def normalize_openapi_parameter(raw: Any, *, language: str | None = "en") -> dict[str, Any] | None:
    """Map OpenAPI Parameter Object fields into qa-platform's parameter model."""
    if not isinstance(raw, dict):
        return None
    location = str(raw.get("in") or "").lower()
    if location == "cookie":
        return None
    schema = raw.get("schema") if isinstance(raw.get("schema"), dict) else {}
    # Swagger 2 Parameter Objects put the JSON-schema-like fields directly on
    # the parameter instead of under ``schema``. Keep this fallback here so
    # callers do not need version-specific parameter handling.
    if not schema:
        schema = {
            field: deepcopy(raw[field])
            for field in (
                "type",
                "format",
                "items",
                "enum",
                "pattern",
                "minimum",
                "maximum",
                "minLength",
                "maxLength",
                "minItems",
                "maxItems",
                "uniqueItems",
                "default",
                "example",
            )
            if field in raw
        }
    example: Any = raw.get("example", _MISSING)
    if example is _MISSING:
        example = _sample_from_examples(raw.get("examples"))
    default: Any = raw.get("default", _MISSING)
    return parameter_from_schema(
        str(raw.get("name") or ""),
        location,
        schema,
        required=bool(raw.get("required")),
        description=_description(raw.get("description") or schema.get("description")),
        default=default,
        example=example,
        language=language,
    )


def parameters_from_object_schema(schema: Any, *, language: str | None = "en") -> list[dict[str, Any]]:
    """Emit top-level JSON body fields and recursively materialize object children."""
    if not isinstance(schema, dict):
        return []
    properties, required_names = _object_schema_parts(schema)
    if not properties:
        return []
    result: list[dict[str, Any]] = []
    for name, value in properties.items():
        parameter = parameter_from_schema(
            str(name),
            "body",
            value if isinstance(value, dict) else {},
            required=str(name) in required_names,
            language=language,
        )
        if parameter:
            result.append(parameter)
    return result


def parameter_identity(value: dict[str, Any]) -> tuple[str, str]:
    location = str(value.get("in") or "query").lower()
    name = str(value.get("name") or "").strip()
    return (location, name.lower() if location == "header" else name)


def merge_parameter(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    """Merge same-location parameters without losing a required constraint/default."""
    result = deepcopy(existing)
    result["required"] = bool(existing.get("required")) or bool(incoming.get("required"))
    for field, value in incoming.items():
        if field == "required":
            continue
        if field in {"description", "format", "pattern"} and not value:
            continue
        if field == "type" and value == "string" and result.get("type") not in {None, "string"}:
            continue
        result[field] = deepcopy(value)
    return result


def add_parameters(target: dict[str, Any], values: Iterable[dict[str, Any]]) -> None:
    """Upsert parameters on a scanner interface in stable platform order."""
    current = [item for item in target.get("parameters", []) if isinstance(item, dict)]
    positions = {parameter_identity(item): index for index, item in enumerate(current)}
    for item in values:
        identity = parameter_identity(item)
        if identity[0] not in PARAMETER_LOCATIONS or not identity[1]:
            continue
        if identity in positions:
            current[positions[identity]] = merge_parameter(current[positions[identity]], item)
        else:
            positions[identity] = len(current)
            current.append(deepcopy(item))
    order = {location: index for index, location in enumerate(PARAMETER_LOCATIONS)}
    target["parameters"] = sorted(
        current,
        key=lambda item: (order.get(str(item.get("in")), len(order)), str(item.get("name") or "").lower()),
    )


def add_path_parameters(target: dict[str, Any], path: str, *, language: str | None = "en") -> None:
    add_parameters(
        target,
        (
            parameter_from_schema(name, "path", {}, required=True, language=language)
            for name in path_parameter_names(path)
        ),
    )
