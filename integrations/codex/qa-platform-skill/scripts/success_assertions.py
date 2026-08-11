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
    """Keep legacy inferred system assertion assets for projects without config."""
    definitions: dict[str, dict[str, Any]] = {}
    profiles: dict[str, dict[str, Any]] = {}
    distinct_codes = {json.dumps(item["value"], ensure_ascii=False, sort_keys=True) for item in success_code_candidates}
    success_code = success_code_candidates[0]["value"] if len(distinct_codes) == 1 and success_code_candidates else None

    def add_definition(record: dict[str, Any]) -> None:
        definitions.setdefault(str(record["key"]), record)

    def add_profile(record: dict[str, Any]) -> None:
        profiles.setdefault(str(record["name"]), record)

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

    http_body_profiles: dict[str, str] = {}
    for item in interfaces["http"].values():
        schema = _body_schema(item, success_code)
        schema_id = _schema_key(schema)
        is_system_default = schema == DEFAULT_SUCCESS_BODY_SCHEMA
        body_key = "system:success-body-schema" if is_system_default else f"system:success-body-schema:{schema_id}"
        profile_name = "system:http-success" if is_system_default else f"system:http-success:{schema_id}"
        if schema_id not in http_body_profiles:
            http_body_profiles[schema_id] = profile_name
            add_definition(
                {
                    "key": body_key,
                    "name": body_key,
                    "engine": "json_schema",
                    "description": "qa-platform 系统成功响应体 JSON Schema 定义。",
                    "config": {"source": "body", "schema": schema},
                    "default_params": {},
                    "severity": "success",
                    "message": "响应体不符合成功契约定义",
                }
            )
            add_profile(
                {
                    "name": profile_name,
                    "protocol": "http",
                    "description": "由 qa-platform 系统成功状态和响应体定义组成的 HTTP 成功断言集合。",
                    "is_default": False,
                    "bindings": [
                        {"assertion_id": "system:success-status", "enabled": True},
                        {"assertion_id": body_key, "enabled": True},
                    ],
                }
            )
        item["assertion_profile_key"] = profile_name
        item["success_contract"] = {
            "status_codes": {"min": 200, "max": 299},
            "body_schema": schema,
        }
        if success_code_candidates:
            item["success_assertion_refs"] = [
                candidate["source_ref"] for candidate in success_code_candidates
            ]

    ws_profiles: dict[int, str] = {}
    for item in interfaces["ws"].values():
        minimum = max(int(item.get("receive_count") or 1), 1)
        profile_name = "system:ws-success" if minimum == 1 else f"system:ws-success:{minimum}"
        if minimum not in ws_profiles:
            ws_profiles[minimum] = profile_name
            definition_key = "system:success-messages" if minimum == 1 else f"system:success-messages:{minimum}"
            if minimum != 1:
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
            add_profile(
                {
                    "name": profile_name,
                    "protocol": "ws",
                    "description": "由 qa-platform 系统 WebSocket 成功消息定义组成的成功断言集合。",
                    "is_default": False,
                    "bindings": [{"assertion_id": definition_key, "enabled": True}],
                }
            )
        item["assertion_profile_key"] = profile_name
        item["success_contract"] = {"messages": {"min": minimum}, "body_schema": {}}

    return {
        "assertion_definitions": sorted(definitions.values(), key=lambda item: item["key"]),
        "assertion_profiles": sorted(profiles.values(), key=lambda item: item["name"]),
        "detected_success_codes": success_code_candidates,
        "profile_keys": sorted(profiles),
        "default_profiles": {},
        "source": "inferred_system_contract",
    }


def _build_configured_success_assertion_assets(
    interfaces: dict[str, dict[str, dict[str, Any]]],
    success_code_candidates: list[dict[str, Any]],
    configured: dict[str, Any],
) -> dict[str, Any]:
    """Materialize config assets and bind every discovered API to its default."""
    definitions = deepcopy(configured.get("definitions") or [])
    profiles = deepcopy(configured.get("profiles") or [])
    defaults = deepcopy(configured.get("default_profiles") or {})
    profile_by_name = {
        str(profile.get("name")): profile for profile in profiles if isinstance(profile, dict)
    }
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
        profile_name = str(defaults.get(protocol) or "").strip()
        profile = profile_by_name.get(profile_name)
        if not profile:
            raise SystemExit(
                f"qa-platform success_assertions has no configured default {protocol} profile for discovered APIs"
            )
        if str(profile.get("protocol") or "").lower() != protocol:
            raise SystemExit(
                f"qa-platform success_assertions default profile {profile_name} does not match {protocol}"
            )
        for item in records.values():
            item["assertion_profile_key"] = profile_name
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
        "assertion_profiles": sorted(
            (item for item in profiles if isinstance(item, dict)),
            key=lambda item: str(item.get("name") or ""),
        ),
        "detected_success_codes": success_code_candidates,
        "profile_keys": sorted(profile_by_name),
        "default_profiles": {str(key): str(value) for key, value in defaults.items()},
        "source": "project_config",
    }


def build_success_assertion_assets(
    interfaces: dict[str, dict[str, dict[str, Any]]],
    success_code_candidates: list[dict[str, Any]],
    configured: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create assertion assets, preferring an explicit project configuration.

    The configuration is normalized before this function is called.  A legacy
    project without the section retains the prior inferred system profile
    behavior, while any present configuration is authoritative for all APIs.
    """
    if configured is not None:
        return _build_configured_success_assertion_assets(
            interfaces, success_code_candidates, configured
        )
    return _build_inferred_success_assertion_assets(interfaces, success_code_candidates)
