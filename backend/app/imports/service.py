from __future__ import annotations

from collections.abc import Iterable
from copy import deepcopy
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.definitions import DEFAULT_HTTP_HEADERS
from app.execution.context import deep_merge
from app.models import (
    ApiDefinition,
    ApiTemplate,
    AssertionDefinition,
    ImportSession,
    Project,
    TestFlow,
    TestPlan,
    utcnow,
)
from app.success_contract import default_success_contract

COLLECTIONS: tuple[tuple[str, type[Any], str, tuple[str, ...]], ...] = (
    (
        "api_templates",
        ApiTemplate,
        "name",
        ("name", "protocol", "description", "request", "parameters", "examples"),
    ),
    (
        "assertion_definitions",
        AssertionDefinition,
        "key",
        (
            "key",
            "name",
            "engine",
            "description",
            "config",
            "default_params",
            "severity",
            "message",
        ),
    ),
    (
        "apis",
        ApiDefinition,
        "key",
        (
            "key",
            "name",
            "protocol",
            "description",
            "request",
            "request_schema",
            "response_schema",
            "parameters",
            "examples",
            "success_contract",
            "response_variants",
            "template_id",
            "success_assertion_id",
        ),
    ),
    (
        "flows",
        TestFlow,
        "key",
        ("key", "name", "description", "variables", "steps"),
    ),
    (
        "test_plans",
        TestPlan,
        "key",
        ("key", "version", "name", "description", "items"),
    ),
)

DEFAULTS: dict[str, dict[str, Any]] = {
    "api_templates": {
        "protocol": "http",
        "description": "",
        "request": {},
        "parameters": [],
        "examples": [],
    },
    "assertion_definitions": {
        "engine": "path",
        "description": "",
        "config": {},
        "default_params": {},
        "severity": "success",
        "message": "",
    },
    "apis": {
        "protocol": "http",
        "description": "",
        "request": {},
        "request_schema": {},
        "response_schema": {},
        "parameters": [],
        "examples": [],
        "success_contract": {},
        "response_variants": [],
    },
    "flows": {"description": "", "variables": {}, "steps": []},
    "test_plans": {"version": "v1.0.0", "description": "", "items": []},
}


def _value(record: dict[str, Any], collection: str, field: str) -> Any:
    if field in record:
        return record[field]
    return deepcopy(DEFAULTS.get(collection, {}).get(field))


def _identity(record: dict[str, Any], identity_field: str, fallback: str = "") -> str:
    value = record.get(identity_field) or record.get("key") or record.get("name") or fallback
    return str(value).strip()


def _normalize_package(package: dict[str, Any]) -> tuple[dict[str, Any], list[str], list[str]]:
    normalized = deepcopy(package)
    errors: list[str] = []
    warnings = [str(item) for item in normalized.get("warnings", [])]
    project = normalized.get("project")
    if project and not isinstance(project, dict):
        errors.append("project 必须是对象")
        normalized["project"] = {}
    elif project is None:
        normalized["project"] = {}

    for collection, _model, identity_field, _fields in COLLECTIONS:
        records = normalized.get(collection, [])
        if not isinstance(records, list):
            errors.append(f"{collection} 必须是数组")
            normalized[collection] = []
            continue
        seen: set[str] = set()
        for position, record in enumerate(records, start=1):
            if not isinstance(record, dict):
                errors.append(f"{collection} 第 {position} 项必须是对象")
                continue
            identity = _identity(record, identity_field, f"item-{position}")
            if not identity:
                errors.append(f"{collection} 第 {position} 项缺少 {identity_field}")
                continue
            if identity in seen:
                errors.append(f"{collection} 包含重复标识：{identity}")
            seen.add(identity)
            record.setdefault(identity_field, identity)
            if not record.get("name"):
                record["name"] = identity
            if not record.get("key") and collection in {"apis", "flows", "test_plans"}:
                record["key"] = identity

    return normalized, errors, warnings


def _existing_map(
    session: Session, model: type[Any], project_id: str, identity_field: str
) -> dict[str, Any]:
    records = session.scalars(select(model).where(model.project_id == project_id))
    return {str(getattr(record, identity_field)): record for record in records}


def _source_lookup(records: Iterable[dict[str, Any]], identity_field: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for record in records:
        identity = _identity(record, identity_field)
        for candidate in (record.get("id"), record.get("key"), record.get("name"), identity):
            if candidate:
                result[str(candidate)] = identity
    return result


def _reference_identity(
    record: dict[str, Any],
    records: list[dict[str, Any]],
    identity_field: str,
    *fields: str,
) -> str | None:
    value: Any = None
    for field in fields:
        if record.get(field) not in (None, ""):
            value = record[field]
            break
    if value in (None, ""):
        return None
    value = str(value)
    lookup = _source_lookup(records, identity_field)
    return lookup.get(value)


def _target_ref(
    session: Session,
    project_id: str | None,
    identity: str | None,
    existing: dict[str, Any],
    model: type[Any],
) -> str | None:
    if identity is None:
        return None
    if identity in existing:
        return existing[identity].id
    if project_id:
        direct = session.scalar(
            select(model).where(model.id == identity, model.project_id == project_id)
        )
        if direct:
            return direct.id
    return f"new:{model.__tablename__}:{identity}"


def _materialize_assertion_ref(
    session: Session,
    project_id: str | None,
    value: Any,
    assertion_records: list[dict[str, Any]],
    assertion_existing: dict[str, Any],
    errors: list[str],
    required: bool = True,
) -> str | None:
    if value in (None, ""):
        if required:
            errors.append("断言引用缺少 assertion_id")
        return None
    lookup = _source_lookup(assertion_records, "key")
    identity = lookup.get(str(value)) or str(value)
    target_id = _target_ref(session, project_id, identity, assertion_existing, AssertionDefinition)
    if target_id is None:
        return None
    if target_id.startswith("new:") and identity not in lookup.values():
        errors.append(f"引用了不存在的断言：{value}")
        return None
    return target_id


def _materialize_step_assertions(
    session: Session,
    project_id: str | None,
    assertions: list[dict[str, Any]],
    disabled_ids: list[str],
    package: dict[str, Any],
    existing_maps: dict[str, dict[str, Any]],
    errors: list[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    assertion_lookup = _source_lookup(package["assertion_definitions"], "key")
    result: list[dict[str, Any]] = []
    for assertion in assertions:
        item = deepcopy(assertion)
        if not isinstance(item, dict):
            errors.append("流程步骤 assertions 中的每一项必须是对象")
            continue
        value = item.get("assertion_id") or item.get("id")
        identity = assertion_lookup.get(str(value)) if value not in (None, "") else None
        if identity:
            target_id = _materialize_assertion_ref(
                session,
                project_id,
                value,
                package["assertion_definitions"],
                existing_maps["assertion_definitions"],
                errors,
                required=False,
            )
            if target_id:
                item["assertion_id"] = target_id
        result.append(item)

    normalized_disabled: list[str] = []
    for value in disabled_ids:
        identity = assertion_lookup.get(str(value))
        if identity:
            target_id = _materialize_assertion_ref(
                session,
                project_id,
                value,
                package["assertion_definitions"],
                existing_maps["assertion_definitions"],
                errors,
                required=False,
            )
            if target_id:
                normalized_disabled.append(target_id)
        elif str(value).startswith(("system:", "inline:")):
            normalized_disabled.append(str(value))
        else:
            direct = (
                session.scalar(
                    select(AssertionDefinition).where(
                        AssertionDefinition.id == str(value),
                        AssertionDefinition.project_id == project_id,
                    )
                )
                if project_id
                else None
            )
            if direct:
                normalized_disabled.append(direct.id)
            else:
                errors.append(f"禁用断言引用了不存在的断言：{value}")
    return result, normalized_disabled


def _materialize_steps(
    session: Session,
    project_id: str | None,
    steps: list[dict[str, Any]],
    api_records: list[dict[str, Any]],
    api_existing: dict[str, Any],
    package: dict[str, Any],
    existing_maps: dict[str, dict[str, Any]],
    errors: list[str],
) -> list[dict[str, Any]]:
    api_lookup = _source_lookup(api_records, "key")
    result: list[dict[str, Any]] = []
    for position, raw_step in enumerate(steps, start=1):
        step = deepcopy(raw_step)
        if not isinstance(step, dict):
            errors.append(f"flows.steps 第 {position} 项必须是对象")
            continue
        identity = api_lookup.get(str(step.get("api_id"))) or api_lookup.get(
            str(step.get("api_key"))
        )
        if identity is None and step.get("api_id"):
            identity = str(step["api_id"])
        if identity is None:
            errors.append(f"流程步骤 {step.get('name') or position} 缺少 api_id 或 api_key")
        target_id = _target_ref(session, project_id, identity, api_existing, ApiDefinition)
        if target_id is None or (
            target_id.startswith("new:") and identity not in api_lookup.values()
        ):
            if target_id is None:
                continue
            if target_id.startswith("new:"):
                errors.append(f"流程步骤引用了不存在的 API：{identity}")
        step["api_id"] = target_id
        step.pop("api_key", None)
        step["assertions"], step["disabled_assertion_ids"] = _materialize_step_assertions(
            session,
            project_id,
            list(step.get("assertions") or []),
            list(step.get("disabled_assertion_ids") or []),
            package,
            existing_maps,
            errors,
        )
        result.append(step)
    return result


def _materialize_items(
    session: Session,
    project_id: str | None,
    items: list[dict[str, Any]],
    api_records: list[dict[str, Any]],
    flow_records: list[dict[str, Any]],
    api_existing: dict[str, Any],
    flow_existing: dict[str, Any],
    errors: list[str],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    api_lookup = _source_lookup(api_records, "key")
    flow_lookup = _source_lookup(flow_records, "key")
    for position, raw_item in enumerate(items, start=1):
        item = deepcopy(raw_item)
        if not isinstance(item, dict):
            errors.append(f"test_plans.items 第 {position} 项必须是对象")
            continue
        item_type = str(item.get("type", ""))
        if item_type not in {"api", "flow"}:
            errors.append(f"测试计划第 {position} 项 type 必须是 api 或 flow")
            continue
        lookup = api_lookup if item_type == "api" else flow_lookup
        existing = api_existing if item_type == "api" else flow_existing
        model = ApiDefinition if item_type == "api" else TestFlow
        identity = lookup.get(str(item.get("target_id"))) or lookup.get(str(item.get("target_key")))
        if identity is None and item.get("target_id"):
            identity = str(item["target_id"])
        target_id = _target_ref(session, project_id, identity, existing, model)
        if target_id is None or (target_id.startswith("new:") and identity not in lookup.values()):
            errors.append(f"测试计划引用了不存在的{item_type}：{identity or '未填写'}")
            continue
        item["target_id"] = target_id
        item.pop("target_key", None)
        result.append(item)
    return result


def _incoming_payload(
    session: Session,
    collection: str,
    record: dict[str, Any],
    project_id: str | None,
    existing_maps: dict[str, dict[str, Any]],
    package: dict[str, Any],
    errors: list[str],
) -> dict[str, Any]:
    fields = next(fields for name, _model, _identity, fields in COLLECTIONS if name == collection)
    payload = {
        field: _value(record, collection, field)
        for field in fields
        if field not in {"template_id", "success_assertion_id", "steps", "items"}
    }
    if collection == "apis":
        template_value = next(
            (
                record.get(field)
                for field in ("template_key", "template_name", "template_id")
                if record.get(field) not in (None, "")
            ),
            None,
        )
        assertion_value = next(
            (
                record.get(field)
                for field in (
                    "success_assertion_key",
                    "success_assertion_name",
                    "success_assertion_id",
                )
                if record.get(field) not in (None, "")
            ),
            None,
        )
        template_identity = _reference_identity(
            record,
            package["api_templates"],
            "name",
            "template_key",
            "template_name",
            "template_id",
        )
        assertion_identity = _reference_identity(
            record,
            package["assertion_definitions"],
            "key",
            "success_assertion_key",
            "success_assertion_name",
            "success_assertion_id",
        )
        if template_identity is None and project_id and template_value:
            direct_template = session.scalar(
                select(ApiTemplate).where(
                    ApiTemplate.id == str(template_value),
                    ApiTemplate.project_id == project_id,
                )
            )
            template_identity = direct_template.name if direct_template else None
        if assertion_identity is None and project_id and assertion_value:
            direct_assertion = session.scalar(
                select(AssertionDefinition).where(
                    AssertionDefinition.id == str(assertion_value),
                    AssertionDefinition.project_id == project_id,
                )
            )
            assertion_identity = direct_assertion.key if direct_assertion else None
        if (
            any(
                record.get(field) not in (None, "")
                for field in ("template_key", "template_name", "template_id")
            )
            and template_identity is None
        ):
            errors.append(f"API {record.get('key')} 引用了不存在的 API 模板")
        if (
            any(
                record.get(field) not in (None, "")
                for field in (
                    "success_assertion_key",
                    "success_assertion_name",
                    "success_assertion_id",
                )
            )
            and assertion_identity is None
        ):
            errors.append(f"API {record.get('key')} 引用了不存在的成功条件")
        payload["template_id"] = _target_ref(
            session,
            project_id,
            template_identity,
            existing_maps["api_templates"],
            ApiTemplate,
        )
        payload["success_assertion_id"] = _target_ref(
            session,
            project_id,
            assertion_identity,
            existing_maps["assertion_definitions"],
            AssertionDefinition,
        )
        if payload.get("protocol") == "http":
            request = deep_merge({}, payload.get("request") or {})
            headers = dict(request.get("headers") or {})
            request_schema = payload.get("request_schema") or {}
            accept = request_schema.get("accept") if isinstance(request_schema, dict) else None
            if isinstance(accept, str) and accept.strip() and "accept" not in {
                str(key).lower() for key in headers
            }:
                headers["Accept"] = accept.strip()
            for name, value in DEFAULT_HTTP_HEADERS.items():
                if name.lower() not in {str(key).lower() for key in headers}:
                    headers[name] = value
            request["headers"] = headers
            payload["request"] = request
        if not payload.get("success_contract"):
            payload["success_contract"] = default_success_contract(
                str(payload.get("protocol") or "http")
            )
        variants = []
        for variant in list(payload.get("response_variants") or []):
            materialized_variant = deepcopy(variant)
            materialized_variant.pop("assertion_profile_ids", None)
            variants.append(materialized_variant)
        payload["response_variants"] = variants
    elif collection == "flows":
        payload["steps"] = _materialize_steps(
            session,
            project_id,
            list(record.get("steps") or []),
            package["apis"],
            existing_maps["apis"],
            package,
            existing_maps,
            errors,
        )
    elif collection == "test_plans":
        payload["items"] = _materialize_items(
            session,
            project_id,
            list(record.get("items") or []),
            package["apis"],
            package["flows"],
            existing_maps["apis"],
            existing_maps["flows"],
            errors,
        )
    return payload


def _changes(existing: Any | None, payload: dict[str, Any], fields: tuple[str, ...]) -> list[str]:
    if existing is None:
        return list(fields)
    return [field for field in fields if getattr(existing, field) != payload.get(field)]


def _resolve_target_project(
    session: Session, package: dict[str, Any], requested_project_id: str | None
) -> Project | None:
    if requested_project_id:
        project = session.get(Project, requested_project_id)
        if not project:
            raise ValueError("目标项目不存在")
        return project
    package_project = package.get("project") or {}
    exported_id = package_project.get("id")
    if exported_id:
        project = session.get(Project, str(exported_id))
        if project:
            return project
    name = str(package_project.get("name") or "").strip()
    if name:
        return session.scalar(select(Project).where(Project.name == name))
    return None


def build_preview(
    session: Session,
    package: dict[str, Any],
    requested_project_id: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any], list[str], list[str], str | None]:
    package, errors, warnings = _normalize_package(package)
    target_project = _resolve_target_project(session, package, requested_project_id)
    project_data = package.get("project") or {}
    if target_project is None and not str(project_data.get("name") or "").strip():
        errors.append("导入项目必须提供 project.name，或指定目标项目")

    target_project_id = target_project.id if target_project else None
    project_payload = {
        "name": str(project_data.get("name") or (target_project.name if target_project else "")),
        "description": project_data.get(
            "description", target_project.description if target_project else ""
        ),
        "variables": project_data.get(
            "variables", target_project.variables if target_project else {}
        ),
    }
    if target_project and project_payload["name"] != target_project.name:
        name_conflict = session.scalar(
            select(Project).where(
                Project.name == project_payload["name"], Project.id != target_project.id
            )
        )
        if name_conflict:
            errors.append(f"导入项目名称已被其他项目占用：{project_payload['name']}")
    project_changes = []
    if target_project:
        project_changes = [
            field
            for field in ("name", "description", "variables")
            if getattr(target_project, field) != project_payload[field]
        ]
    items: list[dict[str, Any]] = [
        {
            "type": "project",
            "key": target_project.id if target_project else project_payload["name"],
            "name": project_payload["name"],
            "action": "create"
            if target_project is None
            else ("update" if project_changes else "unchanged"),
            "changes": project_changes
            or (["name", "description", "variables"] if target_project is None else []),
        }
    ]

    existing_maps = {
        collection: (
            _existing_map(session, model, target_project_id, identity_field)
            if target_project_id
            else {}
        )
        for collection, model, identity_field, _fields in COLLECTIONS
    }
    for collection, _model, identity_field, fields in COLLECTIONS:
        for record in package[collection]:
            identity = _identity(record, identity_field)
            payload = _incoming_payload(
                session, collection, record, target_project_id, existing_maps, package, errors
            )
            existing = existing_maps[collection].get(identity)
            changed = _changes(existing, payload, fields)
            items.append(
                {
                    "type": collection,
                    "key": identity,
                    "name": str(record.get("name") or identity),
                    "action": "create"
                    if existing is None
                    else ("update" if changed else "unchanged"),
                    "changes": changed if existing is not None else list(fields),
                }
            )

    counts = {"create": 0, "update": 0, "unchanged": 0, "error": len(errors)}
    for item in items:
        counts[item["action"]] = counts.get(item["action"], 0) + 1
    preview = {
        "package_version": str(package.get("package_version") or "1.0"),
        "target_project_id": target_project_id,
        "project": project_payload,
        "summary": counts,
        "items": items,
    }
    return package, preview, errors, warnings, target_project_id


def _apply_collection(
    session: Session,
    collection: str,
    model: type[Any],
    identity_field: str,
    fields: tuple[str, ...],
    package: dict[str, Any],
    project_id: str,
    existing_maps: dict[str, dict[str, Any]],
) -> None:
    for record in package[collection]:
        identity = _identity(record, identity_field)
        existing = existing_maps[collection].get(identity)
        payload = _incoming_payload(
            session, collection, record, project_id, existing_maps, package, []
        )
        if existing is None:
            existing = model(project_id=project_id, **payload)
            session.add(existing)
            session.flush()
            existing_maps[collection][identity] = existing
        else:
            for field in fields:
                setattr(existing, field, payload.get(field))
        if collection == "api_templates":
            source_id = record.get("id")
            if source_id:
                existing_maps["_source_template_ids"][str(source_id)] = existing.id
        if collection == "apis":
            source_id = record.get("id")
            if source_id:
                existing_maps["_source_api_ids"][str(source_id)] = existing.id
        if collection == "flows":
            source_id = record.get("id")
            if source_id:
                existing_maps["_source_flow_ids"][str(source_id)] = existing.id


def apply_import(session: Session, import_session: ImportSession) -> Project:
    package = deepcopy(import_session.package)
    target_project = (
        session.get(Project, import_session.project_id) if import_session.project_id else None
    )
    project_data = package.get("project") or {}
    if target_project is None:
        target_project = Project(
            name=str(project_data.get("name") or "导入项目"),
            description=str(project_data.get("description") or ""),
            variables=dict(project_data.get("variables") or {}),
        )
        session.add(target_project)
        session.flush()
        import_session.project_id = target_project.id
    else:
        for field in ("name", "description", "variables"):
            if field in project_data:
                setattr(target_project, field, project_data[field])

    existing_maps: dict[str, dict[str, Any]] = {
        collection: _existing_map(session, model, target_project.id, identity_field)
        for collection, model, identity_field, _fields in COLLECTIONS
    }
    existing_maps["_source_template_ids"] = {}
    existing_maps["_source_api_ids"] = {}
    existing_maps["_source_flow_ids"] = {}

    # Dependencies are applied first so API, flow, and plan references can be resolved.
    for collection, model, identity_field, fields in COLLECTIONS:
        _apply_collection(
            session,
            collection,
            model,
            identity_field,
            fields,
            package,
            target_project.id,
            existing_maps,
        )
    return target_project


def mark_reviewed(import_session: ImportSession, status: str) -> None:
    import_session.status = status
    import_session.reviewed_at = utcnow()
