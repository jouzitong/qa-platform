"""Discover application success-code conventions and build QA assertion assets."""

from __future__ import annotations

import ast
import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

DEFAULT_SUCCESS_BODY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["code", "data"],
    "properties": {"code": {"const": 0}},
}

SUCCESS_CONSTANT_RE = re.compile(
    r"(?im)\b(?:SUCCESS_CODE|CODE_SUCCESS|RESULT_CODE_SUCCESS|RESPONSE_CODE_SUCCESS|"
    r"SUCCESS_VALUE|SUCCESS_RESULT)\b\s*(?:=|:)\s*(?P<value>[^,;\n]+)"
)
SUCCESS_ENUM_RE = re.compile(
    r"(?im)\b(?:ResultCode|ResponseCode|ApiCode|BusinessCode|ErrorCode)\s*\.\s*"
    r"SUCCESS\s*\(\s*(?P<value>[^,;)\n]+)"
)
SUCCESS_CONFIG_RE = re.compile(
    r"(?im)^\s*(?P<key>[A-Za-z0-9_.-]*(?:success[-_.]?code|code[-_.]?success))"
    r"\s*[:=]\s*(?P<value>[^#\n]+)"
)
SUCCESS_SOURCE_SUFFIXES = {
    ".java",
    ".kt",
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".vue",
    ".go",
    ".rb",
    ".php",
    ".properties",
    ".yaml",
    ".yml",
    ".json",
}


def _parse_literal(raw: str) -> Any | None:
    value = raw.strip().rstrip(")").strip()
    if not value or value.startswith(("${", "#{")):
        return None
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    if re.fullmatch(r"-?\d+\.\d+", value):
        return float(value)
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    if len(value) >= 2 and value[0] in {"'", '"'} and value[-1] == value[0]:
        try:
            parsed = ast.literal_eval(value)
        except (SyntaxError, ValueError):
            return value[1:-1]
        return parsed if isinstance(parsed, (str, int, float, bool)) else None
    return None


def discover_success_code_values(
    root: Path, files: list[Path]
) -> tuple[list[dict[str, Any]], list[str]]:
    """Find literal application success-code definitions without executing code."""
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int]] = set()

    def add_candidate(path: Path, line: int, raw_value: str, key: str, confidence: float) -> None:
        value = _parse_literal(raw_value)
        if value is None:
            return
        try:
            relative = path.relative_to(root).as_posix()
        except ValueError:
            relative = path.name
        identity = (json.dumps(value, ensure_ascii=False, sort_keys=True), relative, line)
        if identity in seen:
            return
        seen.add(identity)
        candidates.append(
            {
                "key": key,
                "value": value,
                "source_ref": {"file": relative, "line": line},
                "confidence": confidence,
            }
        )

    for path in files:
        if path.suffix.lower() not in SUCCESS_SOURCE_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for pattern in (SUCCESS_CONSTANT_RE, SUCCESS_ENUM_RE):
            for match in pattern.finditer(text):
                add_candidate(
                    path,
                    text.count("\n", 0, match.start()) + 1,
                    match.group("value"),
                    match.group(0).split("=", 1)[0].strip(),
                    0.9,
                )
        for match in SUCCESS_CONFIG_RE.finditer(text):
            add_candidate(
                path,
                text.count("\n", 0, match.start()) + 1,
                match.group("value"),
                match.group("key"),
                0.85,
            )

    values = {json.dumps(item["value"], ensure_ascii=False, sort_keys=True) for item in candidates}
    warnings: list[str] = []
    if len(values) > 1:
        evidence = ", ".join(
            f"{item['source_ref']['file']}:{item['source_ref']['line']}={item['value']}"
            for item in candidates
        )
        warnings.append(f"发现多个成功码定义，未自动覆盖默认成功体契约：{evidence}")
    return candidates, warnings


def _body_schema(interface: dict[str, Any], success_code: Any | None) -> dict[str, Any]:
    raw_schema = interface.get("response_schema")
    schema = deepcopy(raw_schema) if isinstance(raw_schema, dict) and raw_schema else {}
    has_explicit_schema = bool(schema)
    if not schema:
        schema = deepcopy(DEFAULT_SUCCESS_BODY_SCHEMA)
    if schema.get("type") != "object":
        return schema
    properties = schema.setdefault("properties", {})
    code_schema = properties.get("code")
    if success_code is not None and (not has_explicit_schema or code_schema is None):
        properties["code"] = {"const": success_code}
        required = set(schema.get("required", []))
        required.add("code")
        schema["required"] = sorted(required)
    return schema


def _schema_key(schema: dict[str, Any]) -> str:
    digest = hashlib.sha1(
        json.dumps(schema, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:10]
    return digest


def _build_inferred_success_assertion_assets(
    interfaces: dict[str, dict[str, dict[str, Any]]],
    success_code_candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    """Create one atomic system success condition for each protocol."""
    definitions: dict[str, dict[str, Any]] = {}
    distinct_codes = {json.dumps(item["value"], ensure_ascii=False, sort_keys=True) for item in success_code_candidates}
    success_code = success_code_candidates[0]["value"] if len(distinct_codes) == 1 and success_code_candidates else None

    def add_definition(record: dict[str, Any]) -> None:
        definitions.setdefault(str(record["key"]), record)

    add_definition(
        {
            "key": "system:success-status",
            "name": "system:success-status",
            "engine": "expression",
            "description": "qa-platform 系统 HTTP 成功状态码定义。",
            "config": {"expression": "response.status_code >= 200 and response.status_code <= 299"},
            "default_params": {},
            "severity": "success",
            "message": "HTTP 状态码必须在 200–299 范围内",
        }
    )
    add_definition(
        {
            "key": "system:success-messages",
            "name": "system:success-messages",
            "engine": "expression",
            "description": "qa-platform 系统 WebSocket 成功消息数量定义。",
            "config": {"expression": "len(response.messages) >= params['minimum']"},
            "default_params": {"minimum": 1},
            "severity": "success",
            "message": "WebSocket 收到的消息数量不足",
        }
    )

    for item in interfaces["http"].values():
        schema = _body_schema(item, success_code)
        item["success_assertion_key"] = "system:success-status"
        item["success_contract"] = {
            "status_codes": {"min": 200, "max": 299},
            "body_schema": schema,
        }
        if success_code_candidates:
            item["success_assertion_refs"] = [
                candidate["source_ref"] for candidate in success_code_candidates
            ]

    ws_assertions: dict[int, str] = {}
    for item in interfaces["ws"].values():
        minimum = max(int(item.get("receive_count") or 1), 1)
        definition_key = "system:success-messages" if minimum == 1 else f"system:success-messages:{minimum}"
        ws_assertions[minimum] = definition_key
        if definition_key not in definitions:
            add_definition(
                {
                    "key": definition_key,
                    "name": definition_key,
                    "engine": "expression",
                    "description": "qa-platform 系统 WebSocket 成功消息数量定义。",
                    "config": {"expression": "len(response.messages) >= params['minimum']"},
                    "default_params": {"minimum": minimum},
                    "severity": "success",
                    "message": f"WebSocket 至少需要收到 {minimum} 条消息",
                }
            )
        item["success_assertion_key"] = definition_key
        item["success_contract"] = {"messages": {"min": minimum}, "body_schema": {}}

    return {
        "assertion_definitions": sorted(definitions.values(), key=lambda item: item["key"]),
        "detected_success_codes": success_code_candidates,
        "success_assertion_keys": sorted(
            {str(item.get("success_assertion_key")) for protocol in interfaces.values() for item in protocol.values() if item.get("success_assertion_key")}
        ),
        "default_assertions": {},
        "source": "inferred_system_contract",
    }


def _build_configured_success_assertion_assets(
    interfaces: dict[str, dict[str, dict[str, Any]]],
    success_code_candidates: list[dict[str, Any]],
    configured: dict[str, Any],
) -> dict[str, Any]:
    """Materialize configured success conditions and bind every API to one."""
    definitions = deepcopy(configured.get("definitions") or [])
    defaults = deepcopy(configured.get("default_assertions") or {})
    definition_keys = {str(item.get("key")) for item in definitions if isinstance(item, dict)}
    distinct_codes = {
        json.dumps(item["value"], ensure_ascii=False, sort_keys=True)
        for item in success_code_candidates
        if isinstance(item, dict) and "value" in item
    }
    success_code = (
        success_code_candidates[0]["value"]
        if len(distinct_codes) == 1 and success_code_candidates
        else None
    )

    for protocol in ("http", "ws"):
        records = interfaces.get(protocol, {})
        if not records:
            continue
        assertion_key = str(defaults.get(protocol) or "").strip()
        if assertion_key not in definition_keys:
            raise SystemExit(
                f"qa-platform success_assertions has no configured default {protocol} success condition"
            )
        for item in records.values():
            item["success_assertion_key"] = assertion_key
            if protocol == "http":
                schema = _body_schema(item, success_code)
                item["success_contract"] = {
                    "status_codes": {"min": 200, "max": 299},
                    "body_schema": schema,
                }
                if success_code_candidates:
                    item["success_assertion_refs"] = [
                        candidate["source_ref"]
                        for candidate in success_code_candidates
                        if isinstance(candidate, dict) and isinstance(candidate.get("source_ref"), dict)
                    ]
            else:
                minimum = max(int(item.get("receive_count") or 1), 1)
                item["success_contract"] = {"messages": {"min": minimum}, "body_schema": {}}

    return {
        "assertion_definitions": sorted(
            (item for item in definitions if isinstance(item, dict)),
            key=lambda item: str(item.get("key") or ""),
        ),
        "detected_success_codes": success_code_candidates,
        "success_assertion_keys": sorted(definition_keys),
        "default_assertions": {str(key): str(value) for key, value in defaults.items()},
        "source": "project_config",
    }


def build_success_assertion_assets(
    interfaces: dict[str, dict[str, dict[str, Any]]],
    success_code_candidates: list[dict[str, Any]],
    configured: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create assertion assets, preferring an explicit project configuration.

    The configuration is normalized before this function is called. A project
    without the section receives conservative system success conditions.
    """
    if configured is not None:
        return _build_configured_success_assertion_assets(
            interfaces, success_code_candidates, configured
        )
    return _build_inferred_success_assertion_assets(interfaces, success_code_candidates)
