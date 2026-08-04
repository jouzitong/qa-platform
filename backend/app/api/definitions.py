from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.common import commit_or_conflict, get_or_404
from app.database import get_session
from app.execution.context import deep_merge
from app.execution.expression import ExpressionError, parse_expression
from app.execution.runner import execute_api_once
from app.execution.validation import validate_api_response
from app.models import ApiDefinition, ApiTemplate, AssertionProfile, Project, TestFlow
from app.schemas import ApiCreate, ApiRead, ApiUpdate, ExecuteRequest
from app.success_contract import default_success_contract

router = APIRouter(prefix="/apis", tags=["apis"])

DEFAULT_HTTP_HEADERS = {
    "X-trade-id": "{{ random.uuid(32) }}",
    "Accept": "application/json",
}


def _with_default_http_headers(request: dict[str, Any]) -> dict[str, Any]:
    result = deep_merge({}, request)
    headers = result.get("headers")
    normalized_headers = dict(headers) if isinstance(headers, dict) else {}
    existing_names = {str(name).lower() for name in normalized_headers}
    for name, value in DEFAULT_HTTP_HEADERS.items():
        if name.lower() not in existing_names:
            normalized_headers[name] = value
    result["headers"] = normalized_headers
    return result


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


def _validate_profile(
    session: Session,
    project_id: str,
    protocol: str,
    profile_id: str | None,
) -> AssertionProfile | None:
    if not profile_id:
        return None
    profile = get_or_404(session, AssertionProfile, profile_id, "Assertion profile")
    if profile.project_id != project_id:
        raise HTTPException(status_code=422, detail="Assertion profile belongs to another project")
    if profile.protocol != protocol:
        raise HTTPException(
            status_code=422, detail="API and assertion profile protocols must match"
        )
    return profile


def _validate_variants(
    session: Session,
    project_id: str,
    protocol: str,
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
        for profile_id in variant.get("assertion_profile_ids", []):
            _validate_profile(session, project_id, protocol, str(profile_id))


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


def _default_profile(session: Session, project_id: str, protocol: str) -> AssertionProfile | None:
    return session.scalar(
        select(AssertionProfile).where(
            AssertionProfile.project_id == project_id,
            AssertionProfile.protocol == protocol,
            AssertionProfile.is_default.is_(True),
        )
    )


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
    profile_id = payload.assertion_profile_id
    if "assertion_profile_id" not in payload.model_fields_set:
        profile_id = (_default_profile(session, payload.project_id, payload.protocol) or None)
        profile_id = profile_id.id if profile_id else None
    _validate_profile(session, payload.project_id, payload.protocol, profile_id)
    _validate_variants(
        session, payload.project_id, payload.protocol, payload.response_variants
    )
    success_contract = payload.success_contract
    if payload.protocol == "ws" and "messages" not in success_contract:
        success_contract = default_success_contract("ws")
    _validate_success_contract(payload.protocol, success_contract)
    values = payload.model_dump(exclude={"assertion_profile_id"})
    if payload.protocol == "http":
        values["request"] = _with_default_http_headers(payload.request)
    values["success_contract"] = success_contract
    definition = ApiDefinition(
        **values,
        assertion_profile_id=profile_id,
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
    target_template_id = values.get("template_id", definition.template_id)
    target_profile_id = values.get("assertion_profile_id", definition.assertion_profile_id)
    _validate_template(
        session, definition.project_id, target_protocol, target_template_id
    )
    _validate_profile(
        session, definition.project_id, target_protocol, target_profile_id
    )
    _validate_variants(
        session,
        definition.project_id,
        target_protocol,
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
    _validate_success_contract(target_protocol, success_contract)
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
