#!/usr/bin/env python3
"""Validate a qa-platform import manifest without third-party dependencies."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from project_config import normalize_project_variables

SECRET_RE = re.compile(
    r"(?:sk-[A-Za-z0-9]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|-----BEGIN (?:RSA|OPENSSH|EC|DSA|PRIVATE) KEY-----)"
)
PARAMETER_LOCATIONS = {"path", "query", "header", "body"}
PARAMETER_TYPES = {"string", "integer", "number", "boolean", "object", "array"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser.parse_args()


def add_error(errors: list[str], message: str) -> None:
    errors.append(message)


def check_source_refs(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, list):
        add_error(errors, f"{path} must be a list")
        return
    for index, ref in enumerate(value):
        if not isinstance(ref, dict) or not isinstance(ref.get("file"), str) or not isinstance(ref.get("line"), int):
            add_error(errors, f"{path}[{index}] must contain string file and integer line")


def validate_parameters(value: Any, path: str, errors: list[str]) -> None:
    """Validate qa-platform's flat, executable parameter model."""
    if not isinstance(value, list):
        add_error(errors, f"{path} must be a list")
        return
    identities: set[tuple[str, str]] = set()
    for index, parameter in enumerate(value):
        item_path = f"{path}[{index}]"
        if not isinstance(parameter, dict):
            add_error(errors, f"{item_path} must be an object")
            continue
        name = parameter.get("name")
        location = parameter.get("in")
        parameter_type = parameter.get("type")
        if not isinstance(name, str) or not name.strip():
            add_error(errors, f"{item_path}.name must be a non-empty string")
            continue
        if location not in PARAMETER_LOCATIONS:
            add_error(errors, f"{item_path}.in must be one of {sorted(PARAMETER_LOCATIONS)}")
            continue
        if parameter_type not in PARAMETER_TYPES:
            add_error(errors, f"{item_path}.type must be one of {sorted(PARAMETER_TYPES)}")
        if not isinstance(parameter.get("required"), bool):
            add_error(errors, f"{item_path}.required must be boolean")
        elif location == "path" and not parameter["required"]:
            add_error(errors, f"{item_path}: path parameters must be required")
        description = parameter.get("description")
        if not isinstance(description, str) or not description.strip():
            add_error(errors, f"{item_path}.description must be a non-empty string")
        if "example" not in parameter:
            add_error(errors, f"{item_path}.example is required")
        elif parameter["example"] is None or (
            isinstance(parameter["example"], str) and not parameter["example"].strip()
        ):
            add_error(errors, f"{item_path}.example must be populated")
        identity = (str(location), name.lower() if location == "header" else name)
        if identity in identities:
            add_error(errors, f"duplicate parameter identity: {location}:{name}")
        identities.add(identity)
        if parameter_type == "array" and "items" in parameter:
            items = parameter["items"]
            if not isinstance(items, dict) or items.get("type") not in PARAMETER_TYPES:
                add_error(errors, f"{item_path}.items.type must be a supported parameter type")


def walk_secrets(value: Any, path: str, findings: list[str]) -> None:
    if isinstance(value, str):
        if SECRET_RE.search(value):
            findings.append(path)
    elif isinstance(value, dict):
        for key, child in value.items():
            walk_secrets(child, f"{path}.{key}", findings)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            walk_secrets(child, f"{path}[{index}]", findings)


def validate_assertion_assets(manifest: dict[str, Any], errors: list[str]) -> tuple[dict[str, str], dict[str, str]]:
    """Validate imported assertion IDs and return profile protocol/default maps."""
    definitions = manifest.get("assertion_definitions", [])
    profiles = manifest.get("assertion_profiles", [])
    definition_keys: set[str] = set()
    if not isinstance(definitions, list):
        add_error(errors, "assertion_definitions must be a list")
        definitions = []
    for index, definition in enumerate(definitions):
        path = f"assertion_definitions[{index}]"
        if not isinstance(definition, dict):
            add_error(errors, f"{path} must be an object")
            continue
        key = definition.get("key")
        if not isinstance(key, str) or not key.strip():
            add_error(errors, f"{path}.key must be a non-empty string")
            continue
        if key in definition_keys:
            add_error(errors, f"duplicate assertion definition key: {key}")
        definition_keys.add(key)

    profile_protocols: dict[str, str] = {}
    if not isinstance(profiles, list):
        add_error(errors, "assertion_profiles must be a list")
        profiles = []
    for index, profile in enumerate(profiles):
        path = f"assertion_profiles[{index}]"
        if not isinstance(profile, dict):
            add_error(errors, f"{path} must be an object")
            continue
        name = profile.get("name")
        protocol = profile.get("protocol")
        if not isinstance(name, str) or not name.strip():
            add_error(errors, f"{path}.name must be a non-empty string")
            continue
        if protocol not in {"http", "ws"}:
            add_error(errors, f"{path}.protocol must be http or ws")
            continue
        if name in profile_protocols:
            add_error(errors, f"duplicate assertion profile name: {name}")
        profile_protocols[name] = protocol
        bindings = profile.get("bindings")
        if not isinstance(bindings, list) or not bindings:
            add_error(errors, f"{path}.bindings must be a non-empty list")
            continue
        for binding_index, binding in enumerate(bindings):
            binding_path = f"{path}.bindings[{binding_index}]"
            if not isinstance(binding, dict):
                add_error(errors, f"{binding_path} must be an object")
                continue
            assertion_id = binding.get("assertion_id")
            if not isinstance(assertion_id, str) or assertion_id not in definition_keys:
                add_error(errors, f"{binding_path}.assertion_id references an unknown definition")
            if "enabled" in binding and not isinstance(binding["enabled"], bool):
                add_error(errors, f"{binding_path}.enabled must be boolean")

    default_profiles: dict[str, str] = {}
    metadata = manifest.get("success_assertions")
    if metadata is not None:
        if not isinstance(metadata, dict):
            add_error(errors, "success_assertions must be an object when present")
        else:
            raw_defaults = metadata.get("default_profiles", {})
            if not isinstance(raw_defaults, dict):
                add_error(errors, "success_assertions.default_profiles must be an object")
            else:
                for protocol, name in raw_defaults.items():
                    if protocol not in {"http", "ws"}:
                        add_error(errors, "success_assertions.default_profiles supports only http and ws")
                        continue
                    if not isinstance(name, str) or profile_protocols.get(name) != protocol:
                        add_error(
                            errors,
                            f"success_assertions.default_profiles.{protocol} must reference a matching profile",
                        )
                        continue
                    default_profiles[protocol] = name
    return profile_protocols, default_profiles


def validate(manifest: Any) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(manifest, dict):
        return ["Manifest root must be an object"], []
    if manifest.get("format") != "qa-platform-import":
        add_error(errors, "format must equal qa-platform-import")
    if manifest.get("version") != "1.0":
        add_error(errors, "version must equal 1.0")
    if not isinstance(manifest.get("package_version"), str) or not manifest["package_version"].strip():
        add_error(errors, "package_version must be a non-empty string")
    project = manifest.get("project")
    if not isinstance(project, dict):
        add_error(errors, "project must be an object")
    else:
        for field in ("key", "name"):
            if not isinstance(project.get(field), str) or not project[field].strip():
                add_error(errors, f"project.{field} must be a non-empty string")
        try:
            normalize_project_variables(project.get("variables"), require_base_url=True)
        except SystemExit as exc:
            add_error(errors, str(exc))

    language = manifest.get("language")
    if language is not None:
        if not isinstance(language, dict):
            add_error(errors, "language must be an object when present")
        elif not isinstance(language.get("code"), str) or not language["code"].strip():
            add_error(errors, "language.code must be a non-empty string")

    storage = manifest.get("storage")
    if storage is not None:
        if not isinstance(storage, dict):
            add_error(errors, "storage must be an object when present")
        else:
            if not isinstance(storage.get("directory"), str) or not storage["directory"].strip():
                add_error(errors, "storage.directory must be a non-empty string")
            if "versioned" in storage and not isinstance(storage["versioned"], bool):
                add_error(errors, "storage.versioned must be boolean")
            for field in ("manifest_filename", "archive_filename"):
                if field in storage and (not isinstance(storage[field], str) or not storage[field].strip()):
                    add_error(errors, f"storage.{field} must be a non-empty string")

    architecture = manifest.get("architecture")
    if architecture is not None and not isinstance(architecture, dict):
        add_error(errors, "architecture must be an object when present")
    decision = manifest.get("import_decision")
    if decision is not None:
        if not isinstance(decision, dict):
            add_error(errors, "import_decision must be an object when present")
        else:
            if decision.get("mode") not in {"create", "update", "new_version", "unchanged"}:
                add_error(errors, "import_decision.mode is invalid")
            if not isinstance(decision.get("version"), str) or not decision["version"].strip():
                add_error(errors, "import_decision.version must be a non-empty string")

    assertion_profile_protocols, configured_default_profiles = validate_assertion_assets(
        manifest, errors
    )

    interfaces = manifest.get("interfaces")
    interface_keys: set[str] = set()
    if not isinstance(interfaces, dict):
        add_error(errors, "interfaces must be an object")
        interfaces = {}
    for protocol in ("http", "ws"):
        records = interfaces.get(protocol, [])
        if not isinstance(records, list):
            add_error(errors, f"interfaces.{protocol} must be a list")
            continue
        for index, item in enumerate(records):
            path = f"interfaces.{protocol}[{index}]"
            if not isinstance(item, dict):
                add_error(errors, f"{path} must be an object")
                continue
            key = item.get("key")
            if not isinstance(key, str) or not key:
                add_error(errors, f"{path}.key must be a non-empty string")
            elif key in interface_keys:
                add_error(errors, f"duplicate interface key: {key}")
            else:
                interface_keys.add(key)
            if protocol == "http":
                if item.get("method") not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE"}:
                    add_error(errors, f"{path}.method is not a supported HTTP method")
                if not isinstance(item.get("path"), str) or not item["path"].strip():
                    add_error(errors, f"{path}.path must be a non-empty string")
            else:
                if not isinstance(item.get("url") or item.get("path"), str):
                    add_error(errors, f"{path} needs url or path")
            profile_key = item.get("assertion_profile_key")
            if not isinstance(profile_key, str) or not profile_key.strip():
                add_error(errors, f"{path}.assertion_profile_key must be a non-empty string")
            elif assertion_profile_protocols.get(profile_key) != protocol:
                add_error(errors, f"{path}.assertion_profile_key must reference a matching profile")
            elif (
                configured_default_profiles.get(protocol)
                and profile_key != configured_default_profiles[protocol]
            ):
                add_error(
                    errors,
                    f"{path}.assertion_profile_key must use configured default {configured_default_profiles[protocol]}",
                )
            validate_parameters(item.get("parameters", []), f"{path}.parameters", errors)
            check_source_refs(item.get("source_refs", []), f"{path}.source_refs", errors)

    features = manifest.get("features", [])
    feature_keys: set[str] = set()
    if not isinstance(features, list):
        add_error(errors, "features must be a list")
        features = []
    for index, item in enumerate(features):
        path = f"features[{index}]"
        if not isinstance(item, dict):
            add_error(errors, f"{path} must be an object")
            continue
        key = item.get("key")
        if not isinstance(key, str) or not key:
            add_error(errors, f"{path}.key must be a non-empty string")
        elif key in feature_keys:
            add_error(errors, f"duplicate feature key: {key}")
        else:
            feature_keys.add(key)
        for ref in item.get("related_interfaces", []):
            if ref not in interface_keys:
                add_error(errors, f"{path} references unknown interface: {ref}")
        check_source_refs(item.get("source_refs", []), f"{path}.source_refs", errors)

    cases = manifest.get("test_cases", [])
    case_keys: set[str] = set()
    if not isinstance(cases, list):
        add_error(errors, "test_cases must be a list")
        cases = []
    for index, item in enumerate(cases):
        path = f"test_cases[{index}]"
        if not isinstance(item, dict):
            add_error(errors, f"{path} must be an object")
            continue
        key = item.get("key")
        if not isinstance(key, str) or not key:
            add_error(errors, f"{path}.key must be a non-empty string")
        elif key in case_keys:
            add_error(errors, f"duplicate test case key: {key}")
        else:
            case_keys.add(key)
        target = item.get("target", {})
        if isinstance(target, dict) and target.get("interface_key") and target["interface_key"] not in interface_keys:
            add_error(errors, f"{path} references unknown interface: {target['interface_key']}")
        if item.get("status") not in {"draft", "approved", "active", None}:
            add_error(errors, f"{path}.status is invalid")
        check_source_refs(item.get("source_refs", []), f"{path}.source_refs", errors)

    flows = manifest.get("flows", [])
    flow_keys: set[str] = set()
    if not isinstance(flows, list):
        add_error(errors, "flows must be a list")
        flows = []
    for index, item in enumerate(flows):
        path = f"flows[{index}]"
        if not isinstance(item, dict):
            add_error(errors, f"{path} must be an object")
            continue
        key = item.get("key")
        if not isinstance(key, str) or not key:
            add_error(errors, f"{path}.key must be a non-empty string")
        elif key in flow_keys:
            add_error(errors, f"duplicate flow key: {key}")
        else:
            flow_keys.add(key)
        for step_index, step in enumerate(item.get("steps", [])):
            if not isinstance(step, dict):
                add_error(errors, f"{path}.steps[{step_index}] must be an object")
                continue
            ref = step.get("interface_key")
            if ref not in interface_keys:
                add_error(errors, f"{path}.steps[{step_index}] references unknown interface: {ref}")
            if "enabled" in step and not isinstance(step["enabled"], bool):
                add_error(errors, f"{path}.steps[{step_index}].enabled must be boolean")
        check_source_refs(item.get("source_refs", []), f"{path}.source_refs", errors)

    plans = manifest.get("test_plans", [])
    plan_keys: set[str] = set()
    if not isinstance(plans, list):
        add_error(errors, "test_plans must be a list")
        plans = []
    elif len(plans) > 1:
        add_error(errors, "test_plans must contain at most one plan for package_version")
    package_version = manifest.get("package_version")
    for index, item in enumerate(plans):
        path = f"test_plans[{index}]"
        if not isinstance(item, dict):
            add_error(errors, f"{path} must be an object")
            continue
        key = item.get("key")
        if not isinstance(key, str) or not key:
            add_error(errors, f"{path}.key must be a non-empty string")
        elif key in plan_keys:
            add_error(errors, f"duplicate test plan key: {key}")
        else:
            plan_keys.add(key)
        if not isinstance(item.get("version"), str) or not item["version"].strip():
            add_error(errors, f"{path}.version must be a non-empty string")
        elif isinstance(package_version, str) and package_version.strip() and item["version"] != package_version:
            add_error(errors, f"{path}.version must equal package_version")
        items = item.get("items", [])
        if not isinstance(items, list):
            add_error(errors, f"{path}.items must be a list")
            continue
        for item_index, plan_item in enumerate(items):
            item_path = f"{path}.items[{item_index}]"
            if not isinstance(plan_item, dict):
                add_error(errors, f"{item_path} must be an object")
                continue
            item_type = plan_item.get("type")
            if item_type not in {"api", "flow"}:
                add_error(errors, f"{item_path}.type must be api or flow")
            target_key = plan_item.get("target_key")
            if not isinstance(target_key, str) or not target_key:
                add_error(errors, f"{item_path}.target_key must be a non-empty string")
            elif item_type == "flow" and target_key not in flow_keys:
                add_error(errors, f"{item_path} references unknown flow: {target_key}")
            elif item_type == "api" and target_key not in interface_keys:
                add_error(errors, f"{item_path} references unknown interface: {target_key}")
            if "enabled" in plan_item and not isinstance(plan_item["enabled"], bool):
                add_error(errors, f"{item_path}.enabled must be boolean")
        check_source_refs(item.get("source_refs", []), f"{path}.source_refs", errors)

    secret_paths: list[str] = []
    walk_secrets(manifest, "$", secret_paths)
    if secret_paths:
        add_error(errors, "possible secret values found at: " + ", ".join(secret_paths))
    if not interface_keys:
        warnings.append("No interfaces were found")
    warnings.extend(str(item) for item in manifest.get("warnings", []) if isinstance(item, str))
    return errors, warnings


def main() -> int:
    args = parse_args()
    try:
        manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Unable to read manifest: {exc}", file=sys.stderr)
        return 2
    errors, warnings = validate(manifest)
    report = {"valid": not errors, "errors": errors, "warnings": warnings}
    if args.as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("valid" if not errors else "invalid")
        for message in errors:
            print(f"ERROR: {message}")
        for message in warnings:
            print(f"WARNING: {message}")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
