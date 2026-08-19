from copy import deepcopy
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.common import commit_or_conflict, get_or_404, normalize_group_path
from app.api.groups import ensure_api_group_path
from app.database import get_session
from app.execution.context import deep_merge
from app.execution.expression import ExpressionError, parse_expression
from app.execution.runner import execute_api_once
from app.execution.validation import validate_api_response
from app.models import ApiDefinition, ApiTemplate, AssertionDefinition, Project, TestFlow
from app.schemas import ApiCreate, ApiRead, ApiUpdate, ExecuteRequest
from app.success_contract import default_success_contract

router = APIRouter(prefix="/apis", tags=["apis"])

DEFAULT_HTTP_HEADERS = {
    "X-trade-id": "{{ random.uuid(32) }}",
    "Accept": "application/json",
}


def _with_default_http_headers(
    request: dict[str, Any], request_schema: dict[str, Any] | None = None
) -> dict[str, Any]:
    result = deep_merge({}, request)
    headers = result.get("headers")
    normalized_headers = dict(headers) if isinstance(headers, dict) else {}
    existing_names = {str(name).lower() for name in normalized_headers}
    accept = request_schema.get("accept") if isinstance(request_schema, dict) else None
    if accept is not None and not isinstance(accept, str):
        raise HTTPException(status_code=422, detail="request_schema.accept must be a string")
    if isinstance(accept, str) and accept.strip() and "accept" not in existing_names:
        normalized_headers["Accept"] = accept.strip()
        existing_names.add("accept")
    for name, value in DEFAULT_HTTP_HEADERS.items():
        if name.lower() not in existing_names:
            normalized_headers[name] = value
    result["headers"] = normalized_headers
    return result


def _validate_request_schema(protocol: str, request_schema: dict[str, Any]) -> None:
    if not isinstance(request_schema, dict):
        raise HTTPException(status_code=422, detail="request_schema must be an object")
    accept = request_schema.get("accept")
    if accept is not None and not isinstance(accept, str):
        raise HTTPException(status_code=422, detail="request_schema.accept must be a string")
    if protocol == "ws" and accept not in (None, ""):
        raise HTTPException(status_code=422, detail="WebSocket request_schema cannot define accept")
    schema = request_schema.get("schema")
    if schema is not None:
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as exc:
            raise HTTPException(status_code=422, detail=f"Request schema: {exc}") from None


def _validate_response_schema(response_schema: dict[str, Any]) -> None:
    if not isinstance(response_schema, dict):
        raise HTTPException(status_code=422, detail="response_schema must be an object")
    if not response_schema:
        return
    try:
        Draft202012Validator.check_schema(response_schema)
    except SchemaError as exc:
        raise HTTPException(status_code=422, detail=f"Response schema: {exc}") from None


def _normalize_response_unpack(
    protocol: str, response_unpack: dict[str, Any] | None
) -> dict[str, Any]:
    """Validate the optional HTTP response envelope extraction contract."""
    if response_unpack in (None, {}):
        return {}
    if not isinstance(response_unpack, dict):
        raise HTTPException(status_code=422, detail="response_unpack must be an object")

    enabled = response_unpack.get("enabled", False)
    if not isinstance(enabled, bool):
        raise HTTPException(status_code=422, detail="response_unpack.enabled must be boolean")
    if not enabled:
        return {"enabled": False}
    if protocol != "http":
        raise HTTPException(
            status_code=422, detail="response_unpack is only supported for HTTP APIs"
        )

    source = response_unpack.get("source")
    if not isinstance(source, str) or not source.strip():
        raise HTTPException(
            status_code=422,
            detail="response_unpack.source must be a non-empty response path",
        )
    normalized_source = source.strip()
    segments = normalized_source.split(".")
    if segments[0] != "body" or any(
        not segment or not segment.replace("_", "").replace("-", "").isalnum()
        for segment in segments
    ):
        raise HTTPException(
            status_code=422,
            detail="response_unpack.source must be a dot path rooted at response body",
        )
    normalized = {"enabled": True, "source": normalized_source}
    envelope_schema = response_unpack.get("envelope_schema")
    if isinstance(envelope_schema, dict) and envelope_schema:
        _validate_response_schema(envelope_schema)
        normalized["envelope_schema"] = deepcopy(envelope_schema)
    return normalized


def _response_schema_from_legacy_contract(
    success_contract: dict[str, Any], response_unpack: dict[str, Any]
) -> dict[str, Any]:
    """Extract ``data`` from the former full-envelope schema when possible."""
    if not response_unpack.get("enabled"):
        return {}
    source = str(response_unpack.get("source") or "")
    if source != "body.data":
        return {}
    schema = success_contract.get("body_schema")
    if not isinstance(schema, dict) or schema.get("type") != "object":
        return {}
    properties = schema.get("properties")
    data_schema = properties.get("data") if isinstance(properties, dict) else None
    return data_schema if isinstance(data_schema, dict) else {}


def _validate_template(
    session: Session,
    project_id: str,
    protocol: str,
    template_id: str | None,
) -> ApiTemplate | None:
    if not template_id:
        return None
    template = get_or_404(session, ApiTemplate, template_id, "API template")
    if template.project_id != project_id:
        raise HTTPException(status_code=422, detail="API template belongs to another project")
    if template.protocol != protocol:
        raise HTTPException(status_code=422, detail="API and template protocols must match")
    return template


def _validate_success_assertion(
    session: Session,
    project_id: str,
    assertion_id: str | None,
) -> AssertionDefinition | None:
    if not assertion_id:
        return None
    assertion = get_or_404(session, AssertionDefinition, assertion_id, "成功条件")
    if assertion.project_id != project_id:
        raise HTTPException(status_code=422, detail="成功条件属于其他项目")
    return assertion


def _validate_variants(
    variants: list[dict[str, Any]],
) -> None:
    names: set[str] = set()
    for variant in variants:
        name = str(variant.get("name", "")).strip()
        if not name or name in names:
            raise HTTPException(status_code=422, detail="Response variants require unique names")
        names.add(name)
        try:
            parse_expression(str(variant.get("match", "")))
            if variant.get("schema") is not None:
                Draft202012Validator.check_schema(variant["schema"])
        except (ExpressionError, SchemaError) as exc:
            raise HTTPException(status_code=422, detail=f"Variant {name}: {exc}") from None
def _validate_success_contract(protocol: str, contract: dict[str, Any]) -> None:
    if not isinstance(contract, dict):
        raise HTTPException(status_code=422, detail="Success contract must be an object")
    if protocol == "http":
        status_codes = contract.get("status_codes", {})
        if not isinstance(status_codes, dict):
            raise HTTPException(status_code=422, detail="status_codes must be an object")
        try:
            minimum = int(status_codes.get("min", 200))
            maximum = int(status_codes.get("max", 299))
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=422, detail="status_codes min/max must be integers"
            ) from None
        if not 100 <= minimum <= maximum <= 599:
            raise HTTPException(status_code=422, detail="status_codes must be within 100..599")
    schema = contract.get("body_schema")
    if schema is not None:
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as exc:
            raise HTTPException(status_code=422, detail=f"Success response schema: {exc}") from None


@router.get("", response_model=list[ApiRead])
def list_apis(
    project_id: str | None = Query(default=None), session: Session = Depends(get_session)
) -> list[ApiDefinition]:
    statement = select(ApiDefinition).order_by(ApiDefinition.created_at.desc())
    if project_id:
        statement = statement.where(ApiDefinition.project_id == project_id)
    return list(session.scalars(statement))


@router.post("", response_model=ApiRead, status_code=201)
def create_api(payload: ApiCreate, session: Session = Depends(get_session)) -> ApiDefinition:
    get_or_404(session, Project, payload.project_id, "Project")
    _validate_template(session, payload.project_id, payload.protocol, payload.template_id)
    _validate_success_assertion(
        session, payload.project_id, payload.success_assertion_id
    )
    _validate_request_schema(payload.protocol, payload.request_schema)
    _validate_response_schema(payload.response_schema)
    response_unpack = _normalize_response_unpack(payload.protocol, payload.response_unpack)
    _validate_variants(
        payload.response_variants
    )
    success_contract = payload.success_contract
    if payload.protocol == "ws" and "messages" not in success_contract:
        success_contract = default_success_contract("ws")
    if payload.response_schema:
        response_schema = payload.response_schema
    elif response_unpack.get("enabled"):
        response_schema = _response_schema_from_legacy_contract(success_contract, response_unpack)
    else:
        response_schema = success_contract.get("body_schema", {})
    _validate_response_schema(response_schema)
    if response_schema:
        success_contract = {**success_contract, "body_schema": response_schema}
    _validate_success_contract(payload.protocol, success_contract)
    values = payload.model_dump(exclude={"success_assertion_id"})
    values["group_path"] = normalize_group_path(payload.group_path)
    ensure_api_group_path(session, payload.project_id, values["group_path"])
    if payload.protocol == "http":
        values["request"] = _with_default_http_headers(payload.request, payload.request_schema)
    values["success_contract"] = success_contract
    values["response_schema"] = response_schema
    values["response_unpack"] = response_unpack
    definition = ApiDefinition(
        **values,
        success_assertion_id=payload.success_assertion_id,
    )
    session.add(definition)
    commit_or_conflict(session, "API key already exists in this project")
    session.refresh(definition)
    return definition


@router.get("/{api_id}", response_model=ApiRead)
def get_api(api_id: str, session: Session = Depends(get_session)) -> ApiDefinition:
    return get_or_404(session, ApiDefinition, api_id, "API")


@router.patch("/{api_id}", response_model=ApiRead)
def update_api(
    api_id: str, payload: ApiUpdate, session: Session = Depends(get_session)
) -> ApiDefinition:
    definition = get_or_404(session, ApiDefinition, api_id, "API")
    values = payload.model_dump(exclude_unset=True)
    target_protocol = values.get("protocol", definition.protocol)
    values["group_path"] = normalize_group_path(values.get("group_path", definition.group_path))
    ensure_api_group_path(session, definition.project_id, values["group_path"])
    target_template_id = values.get("template_id", definition.template_id)
    target_assertion_id = values.get("success_assertion_id", definition.success_assertion_id)
    _validate_template(
        session, definition.project_id, target_protocol, target_template_id
    )
    _validate_success_assertion(session, definition.project_id, target_assertion_id)
    target_request_schema = values.get("request_schema", definition.request_schema)
    _validate_request_schema(target_protocol, target_request_schema)
    target_response_unpack = _normalize_response_unpack(
        target_protocol,
        values.get("response_unpack", getattr(definition, "response_unpack", {})),
    )
    target_response_schema = values.get(
        "response_schema", getattr(definition, "response_schema", {})
    )
    _validate_response_schema(target_response_schema)
    _validate_variants(
        values.get("response_variants", definition.response_variants),
    )
    success_contract = values.get(
        "success_contract", definition.success_contract or default_success_contract(target_protocol)
    )
    if not isinstance(success_contract, dict):
        success_contract = default_success_contract(target_protocol)
        values["success_contract"] = success_contract
    elif target_protocol == "ws" and "messages" not in success_contract:
        success_contract = default_success_contract("ws")
        values["success_contract"] = success_contract
    elif target_protocol == "http" and "status_codes" not in success_contract:
        success_contract = default_success_contract("http")
        values["success_contract"] = success_contract
    if target_response_unpack.get("enabled"):
        target_response_schema = _response_schema_from_legacy_contract(
            {"body_schema": target_response_schema}, target_response_unpack
        ) or target_response_schema
    elif "response_schema" not in values and not target_response_schema:
        target_response_schema = success_contract.get("body_schema", {})
    if target_response_schema:
        success_contract = {**success_contract, "body_schema": target_response_schema}
        values["success_contract"] = success_contract
    values["response_schema"] = target_response_schema
    values["response_unpack"] = target_response_unpack
    _validate_success_contract(target_protocol, success_contract)
    if target_protocol == "http":
        values["request"] = _with_default_http_headers(
            values.get("request", definition.request), target_request_schema
        )
    for field, value in values.items():
        setattr(definition, field, value)
    commit_or_conflict(session, "API key already exists in this project")
    session.refresh(definition)
    return definition


@router.delete("/{api_id}", status_code=204)
def delete_api(api_id: str, session: Session = Depends(get_session)) -> Response:
    definition = get_or_404(session, ApiDefinition, api_id, "API")
    flows = session.scalars(
        select(TestFlow).where(TestFlow.project_id == definition.project_id)
    )
    if any(step.get("api_id") == api_id for flow in flows for step in flow.steps):
        raise HTTPException(status_code=409, detail="API is referenced by a test flow")
    session.delete(definition)
    session.commit()
    return Response(status_code=204)


@router.post("/{api_id}/execute")
async def execute_api(
    api_id: str, payload: ExecuteRequest, session: Session = Depends(get_session)
) -> dict[str, Any]:
    definition = get_or_404(session, ApiDefinition, api_id, "API")
    project = get_or_404(session, Project, definition.project_id, "Project")
    context = deep_merge(project.variables, payload.inputs)
    try:
        result = await execute_api_once(
            definition, context, payload.request, template=definition.template
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    request_config = deep_merge(
        definition.template.request if definition.template else {}, definition.request
    )
    request_config = deep_merge(request_config, payload.request)
    validation = validate_api_response(
        session,
        definition,
        request=request_config,
        response=result.response,
        context=context,
    )
    return {"request": result.request, "response": result.response, "validation": validation}
