#!/usr/bin/env python3
"""Validate a qa-platform import manifest without third-party dependencies."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from api_grouping import group_path_error
from module_bundle import ModuleBundleError, load_import_source
from project_config import normalize_project_variables, normalize_service_topology

SECRET_RE = re.compile(
    r"(?:sk-[A-Za-z0-9]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|-----BEGIN (?:RSA|OPENSSH|EC|DSA|PRIVATE) KEY-----)"
)
PARAMETER_LOCATIONS = {"path", "query", "header", "body"}
PARAMETER_TYPES = {"string", "integer", "number", "boolean", "object", "array"}
RESPONSE_PATH_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_-]+$")
PLATFORM_NAME_MAX_LENGTH = 120
PLATFORM_KEY_MAX_LENGTH = 120
PLATFORM_PLAN_VERSION_MAX_LENGTH = 60


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser.parse_args()


def add_error(errors: list[str], message: str) -> None:
    errors.append(message)


def validate_bounded_string(
    value: Any, path: str, max_length: int, errors: list[str]
) -> None:
    if isinstance(value, str) and len(value) > max_length:
        add_error(
            errors,
            f"{path} must not exceed {max_length} characters (got {len(value)})",
        )


def validate_api_grouping_metadata(value: Any, errors: list[str]) -> None:
    """Validate optional scanner metadata without making it an import dependency."""
    if value in (None, {}):
        return
    if not isinstance(value, dict):
        add_error(errors, "api_grouping must be an object when present")
        return
    default_path = value.get("default_path", "/")
    error = group_path_error(default_path)
    if error:
        add_error(errors, f"api_grouping.default_path {error}")
    rules = value.get("rules", [])
    if not isinstance(rules, list):
        add_error(errors, "api_grouping.rules must be a list")
        return
    for index, rule in enumerate(rules):
        path = f"api_grouping.rules[{index}]"
        if not isinstance(rule, dict):
            add_error(errors, f"{path} must be an object")
            continue
        error = group_path_error(rule.get("group_path"))
        if error:
            add_error(errors, f"{path}.group_path {error}")
        if not isinstance(rule.get("match", {}), dict):
            add_error(errors, f"{path}.match must be an object")


def validate_service_topology_metadata(value: Any, errors: list[str]) -> None:
    """Validate optional service ownership and route-prefix metadata."""
    if value in (None, {}):
        return
    try:
        normalize_service_topology(value)
    except SystemExit as exc:
        add_error(errors, str(exc))


def check_source_refs(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, list):
        add_error(errors, f"{path} must be a list")
        return
    for index, ref in enumerate(value):
        if not isinstance(ref, dict) or not isinstance(ref.get("file"), str) or not isinstance(ref.get("line"), int):
            add_error(errors, f"{path}[{index}] must contain string file and integer line")


def _validate_parameter(
    parameter: dict[str, Any],
    item_path: str,
    errors: list[str],
    *,
    inherited_location: str | None = None,
    identities: set[tuple[str, str]] | None = None,
    sibling_names: set[str] | None = None,
) -> None:
    name = parameter.get("name")
    if not isinstance(name, str) or not name.strip():
        add_error(errors, f"{item_path}.name must be a non-empty string")
        return

    declared_location = parameter.get("in")
    if inherited_location is None:
        if declared_location not in PARAMETER_LOCATIONS:
            add_error(errors, f"{item_path}.in must be one of {sorted(PARAMETER_LOCATIONS)}")
            return
        location = str(declared_location)
    else:
        location = inherited_location
        if declared_location is not None and declared_location != inherited_location:
            add_error(
                errors,
                f"{item_path}.in must inherit parent location {inherited_location}",
            )

    if sibling_names is not None:
        if name in sibling_names:
            add_error(errors, f"duplicate child parameter: {location}:{name}")
        sibling_names.add(name)

    parameter_type = parameter.get("type")
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

    if identities is not None:
        identity = (location, name.lower() if location == "header" else name)
        if identity in identities:
            add_error(errors, f"duplicate parameter identity: {location}:{name}")
        identities.add(identity)

    if parameter_type == "array" and "items" in parameter:
        items = parameter["items"]
        if not isinstance(items, dict) or items.get("type") not in PARAMETER_TYPES:
            add_error(errors, f"{item_path}.items.type must be a supported parameter type")

    children = parameter.get("children")
    if children is None and "child_params" in parameter:
        # Accept the pre-children compatibility spelling on hand-authored
        # imports, while all generated artifacts use ``children``.
        children = parameter.get("child_params")
    if children is None:
        return
    if parameter_type != "object":
        add_error(errors, f"{item_path}.children is only valid for object parameters")
        return
    if not isinstance(children, list):
        add_error(errors, f"{item_path}.children must be a list")
        return
    child_names: set[str] = set()
    for child_index, child in enumerate(children):
        child_path = f"{item_path}.children[{child_index}]"
        if not isinstance(child, dict):
            add_error(errors, f"{child_path} must be an object")
            continue
        _validate_parameter(
            child,
            child_path,
            errors,
            inherited_location=location,
            sibling_names=child_names,
        )


def validate_parameters(value: Any, path: str, errors: list[str]) -> None:
    """Validate executable parameters, including recursive object children."""
    if not isinstance(value, list):
        add_error(errors, f"{path} must be a list")
        return
    identities: set[tuple[str, str]] = set()
    for index, parameter in enumerate(value):
        item_path = f"{path}[{index}]"
        if not isinstance(parameter, dict):
            add_error(errors, f"{item_path} must be an object")
            continue
        _validate_parameter(parameter, item_path, errors, identities=identities)


def validate_response_schema_fields(value: Any, path: str, errors: list[str]) -> None:
    """Require reviewable metadata for every visible response field."""
    if not isinstance(value, dict):
        add_error(errors, f"{path} must be an object")
        return
    properties = value.get("properties")
    if isinstance(properties, dict):
        for name, field in properties.items():
            field_path = f"{path}.properties.{name}"
            if not isinstance(field, dict):
                add_error(errors, f"{field_path} must be an object")
                continue
            if not isinstance(field.get("description"), str) or not field[
                "description"
            ].strip():
                add_error(errors, f"{field_path}.description must be a non-empty string")
            if "example" not in field:
                add_error(errors, f"{field_path}.example is required")
            validate_response_schema_fields(field, field_path, errors)
    items = value.get("items")
    if isinstance(items, dict):
        validate_response_schema_fields(items, f"{path}.items", errors)
    for keyword in ("allOf", "anyOf", "oneOf"):
        branches = value.get(keyword)
        if isinstance(branches, list):
            for index, branch in enumerate(branches):
                if isinstance(branch, dict):
                    validate_response_schema_fields(
                        branch, f"{path}.{keyword}[{index}]", errors
                    )


def validate_response_unpack(
    value: Any, path: str, protocol: str, errors: list[str]
) -> None:
    if value in (None, {}):
        return
    if not isinstance(value, dict):
        add_error(errors, f"{path} must be an object")
        return
    enabled = value.get("enabled", False)
    if not isinstance(enabled, bool):
        add_error(errors, f"{path}.enabled must be boolean")
        return
    if not enabled:
        return
    if protocol != "http":
        add_error(errors, f"{path} is only supported for HTTP interfaces")
    source = value.get("source")
    segments = str(source or "").strip().split(".")
    if (
        segments[0] != "body"
        or any(
            not segment or not RESPONSE_PATH_SEGMENT_RE.fullmatch(segment)
            for segment in segments
        )
    ):
        add_error(errors, f"{path}.source must be a dot path rooted at body")


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


def validate_assertion_assets(manifest: dict[str, Any], errors: list[str]) -> set[str]:
    """Validate imported success conditions and return their keys."""
    definitions = manifest.get("assertion_definitions", [])
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
        validate_bounded_string(
            key, f"{path}.key", PLATFORM_KEY_MAX_LENGTH, errors
        )
        validate_bounded_string(
            definition.get("name"), f"{path}.name", PLATFORM_NAME_MAX_LENGTH, errors
        )

    metadata = manifest.get("success_assertions")
    if metadata is not None:
        if not isinstance(metadata, dict):
            add_error(errors, "success_assertions must be an object when present")
        else:
            raw_defaults = metadata.get("default_assertions", {})
            if not isinstance(raw_defaults, dict):
                add_error(errors, "success_assertions.default_assertions must be an object")
            else:
                for protocol, key in raw_defaults.items():
                    if protocol not in {"http", "ws"}:
                        add_error(errors, "success_assertions.default_assertions supports only http and ws")
                        continue
                    if not isinstance(key, str) or key not in definition_keys:
                        add_error(
                            errors,
                            f"success_assertions.default_assertions.{protocol} must reference a definition",
                        )
    return definition_keys


def validate_api_templates(manifest: dict[str, Any], errors: list[str]) -> set[str]:
    templates = manifest.get("api_templates", [])
    aliases: set[str] = set()
    identities: set[str] = set()
    if not isinstance(templates, list):
        add_error(errors, "api_templates must be a list")
        return aliases
    for index, template in enumerate(templates):
        path = f"api_templates[{index}]"
        if not isinstance(template, dict):
            add_error(errors, f"{path} must be an object")
            continue
        name = template.get("name")
        if not isinstance(name, str) or not name.strip():
            add_error(errors, f"{path}.name must be a non-empty string")
            continue
        if name in identities:
            add_error(errors, f"duplicate API template name: {name}")
        identities.add(name)
        validate_bounded_string(
            name, f"{path}.name", PLATFORM_NAME_MAX_LENGTH, errors
        )
        for candidate in (template.get("id"), template.get("key"), name):
            if candidate not in (None, ""):
                aliases.add(str(candidate))
        if template.get("protocol", "http") not in {"http", "ws"}:
            add_error(errors, f"{path}.protocol must be http or ws")
        for field in ("request",):
            if field in template and not isinstance(template[field], dict):
                add_error(errors, f"{path}.{field} must be an object")
        for field in ("parameters", "examples"):
            if field in template and not isinstance(template[field], list):
                add_error(errors, f"{path}.{field} must be a list")
        if isinstance(template.get("parameters"), list):
            validate_parameters(template["parameters"], f"{path}.parameters", errors)
    return aliases


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
        validate_bounded_string(
            project.get("name"), "project.name", PLATFORM_NAME_MAX_LENGTH, errors
        )
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

    validate_api_grouping_metadata(manifest.get("api_grouping"), errors)
    validate_service_topology_metadata(manifest.get("service_topology"), errors)

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

    assertion_definition_keys = validate_assertion_assets(manifest, errors)
    api_template_aliases = validate_api_templates(manifest, errors)

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
            validate_bounded_string(
                key, f"{path}.key", PLATFORM_KEY_MAX_LENGTH, errors
            )
            validate_bounded_string(
                item.get("name"), f"{path}.name", PLATFORM_NAME_MAX_LENGTH, errors
            )
            if protocol == "http":
                if item.get("method") not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE"}:
                    add_error(errors, f"{path}.method is not a supported HTTP method")
                if not isinstance(item.get("path"), str) or not item["path"].strip():
                    add_error(errors, f"{path}.path must be a non-empty string")
            else:
                if not isinstance(item.get("url") or item.get("path"), str):
                    add_error(errors, f"{path} needs url or path")
            request_schema = item.get("request_schema", {})
            if not isinstance(request_schema, dict):
                add_error(errors, f"{path}.request_schema must be an object")
            else:
                accept = request_schema.get("accept")
                if accept is not None and (not isinstance(accept, str) or not accept.strip()):
                    add_error(errors, f"{path}.request_schema.accept must be a non-empty string")
                if "schema" in request_schema and not isinstance(
                    request_schema["schema"], dict
                ):
                    add_error(errors, f"{path}.request_schema.schema must be an object")
            response_schema = item.get("response_schema", {})
            if not isinstance(response_schema, dict):
                add_error(errors, f"{path}.response_schema must be an object")
            elif response_schema:
                validate_response_schema_fields(
                    response_schema, f"{path}.response_schema", errors
                )
            if "group_path" in item:
                group_path_issue = group_path_error(item.get("group_path"))
                if group_path_issue:
                    add_error(errors, f"{path}.group_path {group_path_issue}")
            validate_response_unpack(
                item.get("response_unpack", {}),
                f"{path}.response_unpack",
                protocol,
                errors,
            )
            assertion_key = item.get("success_assertion_key")
            if not isinstance(assertion_key, str) or not assertion_key.strip():
                add_error(errors, f"{path}.success_assertion_key must be a non-empty string")
            elif assertion_key not in assertion_definition_keys:
                add_error(errors, f"{path}.success_assertion_key must reference a definition")
            template_key = item.get("template_key") or item.get("template_name")
            if template_key not in (None, "") and str(template_key) not in api_template_aliases:
                add_error(errors, f"{path}.template_key must reference an API template")
            validate_parameters(item.get("parameters", []), f"{path}.parameters", errors)
            check_source_refs(item.get("source_refs", []), f"{path}.source_refs", errors)

    flow_documents = manifest.get("flow_documents")
    if flow_documents is not None:
        if not isinstance(flow_documents, dict):
            add_error(errors, "flow_documents must be an object when present")
        elif not isinstance(flow_documents.get("documents", []), list):
            add_error(errors, "flow_documents.documents must be a list")
        else:
            for index, document in enumerate(flow_documents.get("documents", [])):
                path = f"flow_documents.documents[{index}]"
                if not isinstance(document, dict):
                    add_error(errors, f"{path} must be an object")
                    continue
                if not isinstance(document.get("path"), str) or not document["path"].strip():
                    add_error(errors, f"{path}.path must be a non-empty string")
                if "required" in document and not isinstance(document["required"], bool):
                    add_error(errors, f"{path}.required must be boolean")

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
        validate_bounded_string(
            key, f"{path}.key", PLATFORM_KEY_MAX_LENGTH, errors
        )
        validate_bounded_string(
            item.get("name"), f"{path}.name", PLATFORM_NAME_MAX_LENGTH, errors
        )
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
        validate_bounded_string(
            key, f"{path}.key", PLATFORM_KEY_MAX_LENGTH, errors
        )
        validate_bounded_string(
            item.get("name"), f"{path}.name", PLATFORM_NAME_MAX_LENGTH, errors
        )
        if not isinstance(item.get("version"), str) or not item["version"].strip():
            add_error(errors, f"{path}.version must be a non-empty string")
        elif isinstance(package_version, str) and package_version.strip() and item["version"] != package_version:
            add_error(errors, f"{path}.version must equal package_version")
        validate_bounded_string(
            item.get("version"),
            f"{path}.version",
            PLATFORM_PLAN_VERSION_MAX_LENGTH,
            errors,
        )
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
        manifest = load_import_source(Path(args.manifest))
    except (ModuleBundleError, OSError, json.JSONDecodeError) as exc:
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
