#!/usr/bin/env python3
"""Convert a validated scanner manifest into a qa-platform import ZIP."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import zipfile
from copy import deepcopy
from pathlib import Path
from typing import Any

from api_grouping import normalize_group_path
from module_bundle import ModuleBundleError, load_import_source, public_flow_documents
from project_config import (
    normalize_package_version,
    normalize_project_base_url,
    normalize_project_variables,
    normalize_storage,
    safe_filename,
    version_bucket,
)

HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "manifest",
        help="Validated module bundle directory/index or legacy qa-platform-import JSON",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Archive path; defaults beside the manifest using configured archive_filename",
    )
    parser.add_argument("--package-version", default=None)
    return parser.parse_args()


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        value = load_import_source(path)
    except (ModuleBundleError, OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Unable to read manifest: {exc}") from None
    if not isinstance(value, dict):
        raise SystemExit("Manifest root must be an object")
    return value


def validate_manifest(path: Path) -> None:
    validator = Path(__file__).with_name("validate-import.py")
    result = subprocess.run(
        [sys.executable, str(validator), str(path), "--json"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return
    try:
        report = json.loads(result.stdout)
        errors = report.get("errors", [])
    except json.JSONDecodeError:
        errors = [result.stdout.strip() or result.stderr.strip()]
    raise SystemExit("Manifest validation failed:\n" + "\n".join(f"- {error}" for error in errors))


def response_contract(interface: dict[str, Any], protocol: str) -> dict[str, Any]:
    configured = interface.get("success_contract")
    if isinstance(configured, dict) and configured:
        return deepcopy(configured)
    if protocol == "ws":
        receive_count = int(interface.get("receive_count") or 1)
        return {"messages": {"min": max(receive_count, 1)}, "body_schema": {}}
    contract: dict[str, Any] = {"status_codes": {"min": 200, "max": 299}}
    schema = interface.get("response_schema")
    if isinstance(schema, dict) and schema:
        contract["body_schema"] = schema
    return contract


def _header_names(headers: dict[str, Any]) -> set[str]:
    return {str(name).lower() for name in headers}


def _request_from_interface(
    interface: dict[str, Any], protocol: str, method: str, path: str, key: str
) -> dict[str, Any]:
    source_request = interface.get("request")
    request = deepcopy(source_request) if isinstance(source_request, dict) else {}

    if protocol == "http":
        configured_method = request.get("method")
        if configured_method and str(configured_method).upper() != method:
            raise SystemExit(
                f"HTTP API {key} method conflicts with request.method: "
                f"{method} != {configured_method}"
            )
        configured_path = request.get("path")
        if configured_path and not request.get("url") and str(configured_path) != path:
            raise SystemExit(
                f"HTTP API {key} path conflicts with request.path: "
                f"{path} != {configured_path}"
            )
        request["method"] = method
        if not request.get("url"):
            request["path"] = path

        headers = request.get("headers")
        if headers is None:
            headers = {}
        if not isinstance(headers, dict):
            raise SystemExit(f"HTTP API {key} request.headers must be an object")
        request["headers"] = headers

        request_schema = interface.get("request_schema")
        accept = request_schema.get("accept") if isinstance(request_schema, dict) else None
        if accept not in (None, ""):
            if not isinstance(accept, str) or not accept.strip():
                raise SystemExit(f"HTTP API {key} request_schema.accept must be a string")
            if "accept" not in _header_names(headers):
                headers["Accept"] = accept.strip()
        if not request.get("url") and path.startswith(("http://", "https://")):
            request["url"] = path
            request.pop("path", None)
        return request

    configured_url = request.get("url")
    if configured_url and str(configured_url) != str(interface.get("url") or interface.get("path") or ""):
        raise SystemExit(f"WebSocket API {key} URL conflicts with request.url")
    request.setdefault("url", str(interface.get("url") or interface.get("path") or ""))
    if interface.get("messages") and "messages" not in request:
        request["messages"] = deepcopy(interface["messages"])
    return request


def convert_interface(interface: dict[str, Any]) -> dict[str, Any]:
    protocol = str(interface.get("protocol") or "http").lower()
    key = str(interface["key"])
    if protocol == "http":
        method = str(interface.get("method") or "GET").upper()
        if method not in HTTP_METHODS:
            raise SystemExit(f"Unsupported HTTP method in {key}: {method}")
        path = str(interface.get("path") or "")
        expected_key = f"http:{method}:{path}"
        if key.startswith("http:") and key != expected_key:
            raise SystemExit(f"HTTP API key must equal {expected_key}: {key}")
    else:
        target = str(interface.get("url") or interface.get("path") or "")
        expected_key = f"ws:{target}"
        if key.startswith("ws:") and key != expected_key:
            raise SystemExit(f"WebSocket API key must equal {expected_key}: {key}")
        method = ""
        path = target

    request = _request_from_interface(interface, protocol, method, path, key)

    converted = {
        "id": key,
        "key": key,
        "name": str(interface.get("name") or key),
        "protocol": protocol,
        "group_path": normalize_group_path(interface.get("group_path", "/")),
        "description": str(interface.get("description") or ""),
        "request": request,
        "request_schema": (
            deepcopy(interface.get("request_schema"))
            if isinstance(interface.get("request_schema"), dict)
            else {}
        ),
        "response_schema": (
            deepcopy(interface.get("response_schema"))
            if isinstance(interface.get("response_schema"), dict)
            else {}
        ),
        "response_unpack": (
            deepcopy(interface.get("response_unpack"))
            if isinstance(interface.get("response_unpack"), dict)
            else {}
        ),
        "parameters": interface.get("parameters") if isinstance(interface.get("parameters"), list) else [],
        "examples": [],
        "success_contract": response_contract(interface, protocol),
        "response_variants": [],
    }
    template_key = interface.get("template_key") or interface.get("template_name")
    if template_key:
        converted["template_key"] = str(template_key)
    if interface.get("success_assertion_key"):
        converted["success_assertion_key"] = str(interface["success_assertion_key"])
    return converted


def convert_flow(flow: dict[str, Any]) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []
    for index, raw_step in enumerate(flow.get("steps") or [], start=1):
        step = raw_step if isinstance(raw_step, dict) else {}
        interface_key = step.get("interface_key")
        if not interface_key:
            raise SystemExit(f"Flow {flow.get('key')} step {index} has no interface_key")
        steps.append(
            {
                "id": str(step.get("id") or f"step-{index}"),
                "name": str(step.get("name") or interface_key),
                "api_key": str(interface_key),
                "enabled": bool(step.get("enabled", False)),
                "request": step.get("request") if isinstance(step.get("request"), dict) else {},
                "assertions": step.get("assertions") if isinstance(step.get("assertions"), list) else [],
                "disabled_assertion_ids": step.get("disabled_assertion_ids") if isinstance(step.get("disabled_assertion_ids"), list) else [],
                "extractors": step.get("extractors") if isinstance(step.get("extractors"), list) else [],
                "retry": step.get("retry") if isinstance(step.get("retry"), dict) else {"max_attempts": 1, "interval_ms": 0, "backoff_multiplier": 1},
            }
        )
    return {
        "id": str(flow.get("id") or flow["key"]),
        "key": str(flow["key"]),
        "name": str(flow.get("name") or flow["key"]),
        "description": str(flow.get("description") or ""),
        "variables": flow.get("variables") if isinstance(flow.get("variables"), dict) else {},
        "steps": steps,
    }


def convert_plan(plan: dict[str, Any], default_version: str) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for index, raw_item in enumerate(plan.get("items") or [], start=1):
        item = raw_item if isinstance(raw_item, dict) else {}
        target_key = item.get("target_key") or item.get("target_id")
        if not target_key:
            raise SystemExit(f"Test plan {plan.get('key')} item {index} has no target_key")
        item_type = str(item.get("type") or "flow")
        if item_type not in {"api", "flow"}:
            raise SystemExit(f"Test plan {plan.get('key')} has unsupported item type: {item_type}")
        items.append(
            {
                "id": str(item.get("id") or f"item-{index}"),
                "type": item_type,
                "target_key": str(target_key),
                "enabled": bool(item.get("enabled", False)),
            }
        )
    return {
        "id": str(plan.get("id") or plan["key"]),
        "key": str(plan["key"]),
        "version": normalize_package_version(plan.get("version") or default_version),
        "name": str(plan.get("name") or plan["key"]),
        "description": str(plan.get("description") or ""),
        "items": items,
    }


def version_dir(value: str) -> str:
    return version_bucket(value)


def build_archive(manifest: dict[str, Any], output: Path, package_version: str | None) -> None:
    version = normalize_package_version(package_version or str(
        manifest.get("package_version")
        or (manifest.get("import_decision") or {}).get("version")
        or "v1.0.0"
    ))
    project = manifest.get("project") if isinstance(manifest.get("project"), dict) else {}
    project = deepcopy(project)
    source = manifest.get("source") if isinstance(manifest.get("source"), dict) else {}
    architecture = manifest.get("architecture") if isinstance(manifest.get("architecture"), dict) else {}
    decision = manifest.get("import_decision") if isinstance(manifest.get("import_decision"), dict) else {}
    interfaces = manifest.get("interfaces") if isinstance(manifest.get("interfaces"), dict) else {}
    api_records = [
        convert_interface(item)
        for protocol in ("http", "ws")
        for item in interfaces.get(protocol, [])
        if isinstance(item, dict)
    ]
    flows = [convert_flow(item) for item in manifest.get("flows", []) if isinstance(item, dict)]
    plans = [convert_plan(item, version) for item in manifest.get("test_plans", []) if isinstance(item, dict)]
    assertion_definitions = [
        item for item in manifest.get("assertion_definitions", []) if isinstance(item, dict)
    ]
    api_templates = [
        item for item in manifest.get("api_templates", []) if isinstance(item, dict)
    ]
    flow_documents = public_flow_documents(manifest.get("flow_documents"))
    warnings = [str(item) for item in manifest.get("warnings", [])]
    if manifest.get("features"):
        warnings.append("features 作为扫描库存放在 inventory.json，导入中心当前仅应用 API、流程和计划")
    if manifest.get("test_cases"):
        warnings.append("test_cases 作为扫描草稿存放在 inventory.json，当前导入中心没有独立测试用例模型")
    gateway = architecture.get("gateway") if isinstance(architecture.get("gateway"), dict) else {}
    gateway_address = gateway.get("address") if isinstance(gateway.get("address"), dict) else {}
    if gateway_address.get("kind") == "explicit" and gateway_address.get("value"):
        variables = project.get("variables") if isinstance(project.get("variables"), dict) else {}
        project["variables"] = {
            **variables,
            "base_url": variables.get(
                "base_url",
                normalize_project_base_url(gateway_address["value"], allow_http_scheme=True),
            ),
        }
    project["variables"] = normalize_project_variables(
        project.get("variables"), require_base_url=True
    )
    source = {
        **source,
        "architecture": architecture,
        "import_decision": decision,
    }

    storage_metadata = manifest.get("storage") if isinstance(manifest.get("storage"), dict) else {}
    root_manifest = {
        "format": "qa-platform-import",
        "version": "1.0",
        "package_version": version,
        "language": manifest.get("language", project.get("language")),
        "api_grouping": deepcopy(manifest.get("api_grouping") or {}),
        "service_topology": deepcopy(manifest.get("service_topology") or {}),
        "storage": {**storage_metadata, **normalize_storage(storage_metadata)},
        "project": project,
        "source": source,
        "warnings": sorted(set(warnings)),
        "inventory": {
            "http": len(interfaces.get("http", [])),
            "ws": len(interfaces.get("ws", [])),
            "flows": len(flows),
            "test_plans": len(plans),
            "api_templates": len(api_templates),
            "assertion_definitions": len(assertion_definitions),
            "flow_documents": len(flow_documents.get("documents", [])),
        },
    }
    inventory = {
        "features": manifest.get("features", []),
        "test_cases": manifest.get("test_cases", []),
    }
    directory = version_dir(version)
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        def write_json(path: str, value: Any) -> None:
            archive.writestr(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")

        write_json("manifest.json", root_manifest)
        write_json("project.json", project)
        write_json("api_templates.json", api_templates)
        write_json("inventory.json", inventory)
        write_json("flow_documents.json", flow_documents)
        write_json("assertion_definitions.json", assertion_definitions)
        write_json(f"{directory}/api.json", api_records)
        write_json(f"{directory}/flow.json", flows)
        write_json(f"{directory}/plans.json", plans)


def main() -> int:
    args = parse_args()
    manifest_path = Path(args.manifest).expanduser().resolve()
    validate_manifest(manifest_path)
    manifest = load_manifest(manifest_path)
    storage = normalize_storage(manifest.get("storage"))
    source_directory = manifest_path if manifest_path.is_dir() else manifest_path.parent
    output = (
        Path(args.output).expanduser()
        if args.output
        else source_directory
        / safe_filename(storage.get("archive_filename"), "qa-platform-import.zip")
    )
    if not output.is_absolute():
        output = Path.cwd() / output
    output = output.resolve()
    build_archive(manifest, output, args.package_version)
    print(json.dumps({"output": str(output), "format": "zip"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
