"""Load configured flow guidance and deterministic documented flow blocks."""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any


FLOW_FENCE_RE = re.compile(
    r"```(?P<kind>qa-platform-flow(?:-(?:json|yaml|yml))?)\s*\r?\n"
    r"(?P<body>[\s\S]*?)\r?\n```",
    re.IGNORECASE,
)
MAX_DOCUMENT_BYTES = 2 * 1024 * 1024


def _slug(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]+", "-", value.strip().lower()).strip("-")
    return normalized or "documented-flow"


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _format(path: Path, configured: str) -> str:
    if configured != "auto":
        return configured
    suffix = path.suffix.lower()
    return {
        ".md": "markdown",
        ".markdown": "markdown",
        ".adoc": "asciidoc",
        ".asciidoc": "asciidoc",
        ".json": "json",
        ".yaml": "yaml",
        ".yml": "yaml",
    }.get(suffix, "text")


def _structured_records(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict) and isinstance(value.get("flows"), list):
        value = value["flows"]
    elif isinstance(value, dict) and (value.get("steps") is not None or value.get("key")):
        value = [value]
    if not isinstance(value, list):
        return []
    return [deepcopy(item) for item in value if isinstance(item, dict)]


def _parse_structured(text: str, format_name: str, source: str) -> list[tuple[dict[str, Any], int]]:
    if format_name == "json":
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"Unable to parse flow document {source}: {exc}") from None
        return [(item, 1) for item in _structured_records(value)]
    if format_name == "yaml":
        try:
            import yaml  # type: ignore
        except ImportError:
            raise SystemExit(
                f"PyYAML is required to parse structured flow document {source}"
            ) from None
        try:
            value = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise SystemExit(f"Unable to parse flow document {source}: {exc}") from None
        return [(item, 1) for item in _structured_records(value)]
    if format_name != "markdown":
        return []

    result: list[tuple[dict[str, Any], int]] = []
    for match in FLOW_FENCE_RE.finditer(text):
        kind = match.group("kind").lower()
        body = match.group("body")
        line = text.count("\n", 0, match.start()) + 1
        if kind.endswith(("-yaml", "-yml")):
            try:
                import yaml  # type: ignore
            except ImportError:
                raise SystemExit(
                    f"PyYAML is required for the flow block in {source}:{line}"
                ) from None
            try:
                value = yaml.safe_load(body)
            except yaml.YAMLError as exc:
                raise SystemExit(
                    f"Unable to parse qa-platform-flow block {source}:{line}: {exc}"
                ) from None
        else:
            try:
                value = json.loads(body)
            except json.JSONDecodeError as exc:
                raise SystemExit(
                    f"Unable to parse qa-platform-flow block {source}:{line}: {exc}"
                ) from None
        result.extend((item, line) for item in _structured_records(value))
    return result


def _step_interface_key(step: dict[str, Any]) -> str:
    direct = step.get("interface_key") or step.get("api_key")
    if direct:
        return str(direct)
    protocol = str(step.get("protocol") or "http").lower()
    if protocol == "ws":
        target = str(step.get("url") or step.get("path") or "").strip()
        return f"ws:{target}" if target else ""
    method = str(step.get("method") or "GET").upper()
    path = str(step.get("path") or "").strip()
    return f"http:{method}:{path}" if path else ""


def _normalize_flow(
    raw: dict[str, Any],
    *,
    source: str,
    line: int,
    interface_keys: set[str],
) -> dict[str, Any]:
    name = str(raw.get("name") or raw.get("key") or "Documented flow").strip()
    key = str(raw.get("key") or f"flow:{_slug(name)}").strip()
    if not key.startswith("flow:"):
        key = f"flow:{_slug(key)}"
    raw_steps = raw.get("steps", [])
    if not isinstance(raw_steps, list) or not raw_steps:
        raise SystemExit(f"Documented flow {key} in {source}:{line} must define steps")
    steps: list[dict[str, Any]] = []
    for index, raw_step in enumerate(raw_steps, start=1):
        if not isinstance(raw_step, dict):
            raise SystemExit(
                f"Documented flow {key} step {index} in {source}:{line} must be an object"
            )
        interface_key = _step_interface_key(raw_step)
        if not interface_key:
            raise SystemExit(
                f"Documented flow {key} step {index} in {source}:{line} has no API reference"
            )
        if interface_key not in interface_keys:
            raise SystemExit(
                f"Documented flow {key} step {index} references unknown interface: {interface_key}"
            )
        steps.append(
            {
                "id": str(raw_step.get("id") or f"step-{index}"),
                "name": str(raw_step.get("name") or interface_key),
                "interface_key": interface_key,
                # Documentation proves intended order, not that runtime values
                # have been reviewed in qa-platform.
                "enabled": False,
                "request": deepcopy(raw_step.get("request"))
                if isinstance(raw_step.get("request"), dict)
                else {},
                "assertions": deepcopy(raw_step.get("assertions"))
                if isinstance(raw_step.get("assertions"), list)
                else [],
                "disabled_assertion_ids": deepcopy(
                    raw_step.get("disabled_assertion_ids")
                )
                if isinstance(raw_step.get("disabled_assertion_ids"), list)
                else [],
                "extractors": deepcopy(raw_step.get("extractors"))
                if isinstance(raw_step.get("extractors"), list)
                else [],
                "retry": deepcopy(raw_step.get("retry"))
                if isinstance(raw_step.get("retry"), dict)
                else {"max_attempts": 1, "interval_ms": 0, "backoff_multiplier": 1},
            }
        )
    return {
        "key": key,
        "name": name,
        "description": str(raw.get("description") or "").strip(),
        "status": "draft",
        "origin": "documentation",
        "variables": deepcopy(raw.get("variables"))
        if isinstance(raw.get("variables"), dict)
        else {},
        "steps": steps,
        "source_refs": [{"file": source, "line": line}],
        "confidence": 0.9,
        "warnings": ["流程顺序来自项目文档；执行参数仍需审核后启用"],
    }


def load_flow_documents(
    root: Path,
    configurations: list[dict[str, Any]],
    interface_keys: set[str],
    warnings: list[str],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Return AI-readable document context and deterministic documented flows."""
    documents: list[dict[str, Any]] = []
    flows: list[dict[str, Any]] = []
    flow_keys: set[str] = set()
    for configured in configurations:
        path = Path(str(configured["path"])).expanduser()
        if not path.is_absolute():
            path = root / path
        path = path.resolve()
        try:
            path.relative_to(root.resolve())
        except ValueError:
            raise SystemExit(
                f"qa-platform flow document must stay inside the project root: {path}"
            ) from None
        source = _relative(path, root)
        if not path.is_file():
            message = f"Configured flow document does not exist: {source}"
            if configured.get("required", True):
                raise SystemExit(message)
            warnings.append(message)
            continue
        try:
            raw_bytes = path.read_bytes()
        except OSError as exc:
            if configured.get("required", True):
                raise SystemExit(f"Unable to read flow document {source}: {exc}") from None
            warnings.append(f"Unable to read optional flow document {source}: {exc}")
            continue
        if len(raw_bytes) > MAX_DOCUMENT_BYTES:
            raise SystemExit(
                f"Flow document exceeds {MAX_DOCUMENT_BYTES} bytes: {source}"
            )
        text = raw_bytes.decode("utf-8", errors="replace")
        format_name = _format(path, str(configured.get("format") or "auto"))
        structured = _parse_structured(text, format_name, source)
        document_flow_keys: list[str] = []
        for raw_flow, line in structured:
            flow = _normalize_flow(
                raw_flow,
                source=source,
                line=line,
                interface_keys=interface_keys,
            )
            if flow["key"] in flow_keys:
                raise SystemExit(f"Duplicate documented flow key: {flow['key']}")
            flow_keys.add(str(flow["key"]))
            document_flow_keys.append(str(flow["key"]))
            flows.append(flow)
        documents.append(
            {
                "path": source,
                "format": format_name,
                "required": bool(configured.get("required", True)),
                "sha256": hashlib.sha256(raw_bytes).hexdigest(),
                "bytes": len(raw_bytes),
                "usage": "structured_and_ai_guidance"
                if document_flow_keys
                else "ai_guidance",
                "structured_flow_keys": document_flow_keys,
                "content": text,
            }
        )
    return {
        "documents": documents,
        "structured_flow_keys": sorted(flow_keys),
    }, flows
