"""Read and write the editable multi-file qa-platform scan bundle.

The scanner keeps ``qa-platform-import.json`` as a compatibility snapshot, but
the module files are the authoritative inputs for validation and ZIP building.
This lets an AI or reviewer update flows independently without rewriting one
large generated document.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any


BUNDLE_FORMAT = "qa-platform-scan-bundle"
BUNDLE_VERSION = "1.0"
IMPORT_FORMAT = "qa-platform-import"
IMPORT_VERSION = "1.0"
COMPATIBILITY_FILENAME = "qa-platform-import.json"
MODULE_FILES = {
    "project": "project.json",
    "api_templates": "api_templates.json",
    "assertion_definitions": "assertion_definitions.json",
    "inventory": "inventory.json",
    "flow_documents": "flow_documents.json",
    "apis": "api.json",
    "flows": "flow.json",
    "test_plans": "plans.json",
}


class ModuleBundleError(ValueError):
    """Raised when a scan module bundle is incomplete or unsafe to read."""


def _records(value: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ModuleBundleError(f"{label} must be a JSON array")
    if not all(isinstance(item, dict) for item in value):
        raise ModuleBundleError(f"Every item in {label} must be a JSON object")
    return [deepcopy(item) for item in value]


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ModuleBundleError(f"Unable to read module {path}: {exc}") from None


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _safe_module_path(directory: Path, configured: Any, fallback: str) -> Path:
    relative = Path(str(configured or fallback))
    if relative.is_absolute() or ".." in relative.parts:
        raise ModuleBundleError(f"Unsafe module path: {relative}")
    resolved = (directory / relative).resolve()
    try:
        resolved.relative_to(directory.resolve())
    except ValueError:
        raise ModuleBundleError(f"Unsafe module path: {relative}") from None
    return resolved


def public_flow_documents(value: Any) -> dict[str, Any]:
    """Remove prose content before compatibility validation or ZIP packaging."""
    if not isinstance(value, dict):
        return {"documents": [], "structured_flow_keys": []}
    documents: list[dict[str, Any]] = []
    for raw in value.get("documents", []):
        if not isinstance(raw, dict):
            continue
        document = {key: deepcopy(item) for key, item in raw.items() if key != "content"}
        documents.append(document)
    keys = value.get("structured_flow_keys", [])
    return {
        "documents": documents,
        "structured_flow_keys": [str(item) for item in keys if str(item).strip()]
        if isinstance(keys, list)
        else [],
    }


def public_import_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(manifest)
    if "flow_documents" in result:
        result["flow_documents"] = public_flow_documents(result["flow_documents"])
    return result


def _module_values(manifest: dict[str, Any]) -> dict[str, Any]:
    interfaces = manifest.get("interfaces") if isinstance(manifest.get("interfaces"), dict) else {}
    apis = [
        deepcopy(item)
        for protocol in ("http", "ws")
        for item in interfaces.get(protocol, [])
        if isinstance(item, dict)
    ]
    return {
        "project": deepcopy(manifest.get("project") or {}),
        "api_templates": deepcopy(manifest.get("api_templates") or []),
        "assertion_definitions": deepcopy(manifest.get("assertion_definitions") or []),
        "inventory": {
            "features": deepcopy(manifest.get("features") or []),
            "test_cases": deepcopy(manifest.get("test_cases") or []),
        },
        "flow_documents": deepcopy(
            manifest.get("flow_documents")
            or {"documents": [], "structured_flow_keys": []}
        ),
        "apis": apis,
        "flows": deepcopy(manifest.get("flows") or []),
        "test_plans": deepcopy(manifest.get("test_plans") or []),
    }


def bundle_index(manifest: dict[str, Any]) -> dict[str, Any]:
    values = _module_values(manifest)
    interfaces = manifest.get("interfaces") if isinstance(manifest.get("interfaces"), dict) else {}
    return {
        "format": BUNDLE_FORMAT,
        "version": BUNDLE_VERSION,
        "import_format": IMPORT_FORMAT,
        "import_version": str(manifest.get("version") or IMPORT_VERSION),
        "package_version": manifest.get("package_version"),
        "language": deepcopy(manifest.get("language")),
        "storage": deepcopy(manifest.get("storage") or {}),
        "source": deepcopy(manifest.get("source") or {}),
        "architecture": deepcopy(manifest.get("architecture") or {}),
        "import_decision": deepcopy(manifest.get("import_decision") or {}),
        "api_template_discovery": deepcopy(manifest.get("api_template_discovery") or {}),
        "success_assertions": deepcopy(manifest.get("success_assertions") or {}),
        "warnings": deepcopy(manifest.get("warnings") or []),
        "modules": deepcopy(MODULE_FILES),
        "compatibility_manifest": COMPATIBILITY_FILENAME,
        "inventory": {
            "http": len(interfaces.get("http", [])),
            "ws": len(interfaces.get("ws", [])),
            "api_templates": len(values["api_templates"]),
            "assertion_definitions": len(values["assertion_definitions"]),
            "features": len(values["inventory"]["features"]),
            "test_cases": len(values["inventory"]["test_cases"]),
            "flow_documents": len(values["flow_documents"].get("documents", [])),
            "flows": len(values["flows"]),
            "test_plans": len(values["test_plans"]),
        },
    }


def write_module_bundle(
    manifest: dict[str, Any],
    directory: Path,
    *,
    compatibility_path: Path | None = None,
) -> dict[str, str]:
    """Write all scan modules and a compatibility aggregate."""
    directory = directory.expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    values = _module_values(manifest)
    index = bundle_index(manifest)
    _write_json(directory / "manifest.json", index)
    for label, filename in MODULE_FILES.items():
        _write_json(directory / filename, values[label])

    public_manifest = public_import_manifest(manifest)
    aggregate = compatibility_path or directory / COMPATIBILITY_FILENAME
    aggregate = aggregate.expanduser().resolve()
    _write_json(aggregate, public_manifest)
    compatibility_in_bundle = directory / COMPATIBILITY_FILENAME
    if compatibility_in_bundle.resolve() != aggregate:
        _write_json(compatibility_in_bundle, public_manifest)
    return {
        "directory": str(directory),
        "manifest": str(directory / "manifest.json"),
        "compatibility_manifest": str(aggregate),
    }


def _load_module(directory: Path, modules: dict[str, Any], label: str) -> Any:
    return _read_json(
        _safe_module_path(directory, modules.get(label), MODULE_FILES[label])
    )


def load_module_bundle(directory: Path) -> dict[str, Any]:
    directory = directory.expanduser().resolve()
    index = _read_json(directory / "manifest.json")
    if not isinstance(index, dict) or index.get("format") != BUNDLE_FORMAT:
        raise ModuleBundleError(
            f"{directory / 'manifest.json'} is not a {BUNDLE_FORMAT} manifest"
        )
    modules = index.get("modules")
    if not isinstance(modules, dict):
        raise ModuleBundleError("Bundle manifest.modules must be an object")

    project = _load_module(directory, modules, "project")
    if not isinstance(project, dict):
        raise ModuleBundleError("project.json must be a JSON object")
    inventory = _load_module(directory, modules, "inventory")
    if not isinstance(inventory, dict):
        raise ModuleBundleError("inventory.json must be a JSON object")
    flow_documents = _load_module(directory, modules, "flow_documents")
    if not isinstance(flow_documents, dict):
        raise ModuleBundleError("flow_documents.json must be a JSON object")
    apis = _records(_load_module(directory, modules, "apis"), "api.json")
    interfaces: dict[str, list[dict[str, Any]]] = {"http": [], "ws": []}
    for index_value, api in enumerate(apis):
        protocol = str(api.get("protocol") or "http").lower()
        if protocol not in interfaces:
            raise ModuleBundleError(
                f"api.json[{index_value}].protocol must be http or ws"
            )
        interfaces[protocol].append(api)

    return {
        "format": str(index.get("import_format") or IMPORT_FORMAT),
        "version": str(index.get("import_version") or IMPORT_VERSION),
        "package_version": index.get("package_version"),
        "language": deepcopy(index.get("language")),
        "storage": deepcopy(index.get("storage") or {}),
        "project": project,
        "source": deepcopy(index.get("source") or {}),
        "interfaces": interfaces,
        "api_templates": _records(
            _load_module(directory, modules, "api_templates"), "api_templates.json"
        ),
        "assertion_definitions": _records(
            _load_module(directory, modules, "assertion_definitions"),
            "assertion_definitions.json",
        ),
        "success_assertions": deepcopy(index.get("success_assertions") or {}),
        "features": _records(inventory.get("features", []), "inventory.features"),
        "test_cases": _records(inventory.get("test_cases", []), "inventory.test_cases"),
        "flow_documents": public_flow_documents(flow_documents),
        "flows": _records(_load_module(directory, modules, "flows"), "flow.json"),
        "test_plans": _records(
            _load_module(directory, modules, "test_plans"), "plans.json"
        ),
        "architecture": deepcopy(index.get("architecture") or {}),
        "import_decision": deepcopy(index.get("import_decision") or {}),
        "api_template_discovery": deepcopy(index.get("api_template_discovery") or {}),
        "warnings": [str(item) for item in index.get("warnings", [])]
        if isinstance(index.get("warnings", []), list)
        else [],
    }


def load_import_source(path: Path) -> dict[str, Any]:
    """Load either a legacy aggregate JSON or a module bundle directory/index."""
    path = path.expanduser().resolve()
    if path.is_dir():
        return load_module_bundle(path)
    value = _read_json(path)
    if not isinstance(value, dict):
        raise ModuleBundleError("Import source root must be a JSON object")
    if value.get("format") == BUNDLE_FORMAT:
        return load_module_bundle(path.parent)
    if value.get("format") != IMPORT_FORMAT:
        raise ModuleBundleError(
            f"Import source format must be {IMPORT_FORMAT} or {BUNDLE_FORMAT}"
        )
    return value
