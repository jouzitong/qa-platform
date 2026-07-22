from fastapi import APIRouter, Depends, HTTPException, Query, Response
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.common import get_or_404
from app.database import get_session
from app.execution.expression import ExpressionError, parse_expression
from app.models import ApiDefinition, AssertionDefinition, AssertionProfile, Project
from app.schemas import (
    AssertionDefinitionCreate,
    AssertionDefinitionRead,
    AssertionDefinitionUpdate,
    AssertionProfileCreate,
    AssertionProfileRead,
    AssertionProfileUpdate,
)

definitions_router = APIRouter(
    prefix="/assertion-definitions", tags=["assertion-definitions"]
)
profiles_router = APIRouter(prefix="/assertion-profiles", tags=["assertion-profiles"])


def _validate_definition(engine: str, config: dict) -> None:
    try:
        if engine == "path":
            if not config.get("source"):
                raise ValueError("Path assertion requires config.source")
        elif engine == "expression":
            parse_expression(str(config.get("expression", "")))
        elif engine == "json_schema":
            Draft202012Validator.check_schema(config.get("schema", {}))
    except (ValueError, ExpressionError, SchemaError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


def _validate_bindings(session: Session, project_id: str, bindings: list[dict]) -> None:
    seen: set[str] = set()
    for binding in bindings:
        assertion_id = str(binding.get("assertion_id", ""))
        if not assertion_id or assertion_id in seen:
            raise HTTPException(
                status_code=422, detail="Profile bindings require unique assertion_id values"
            )
        seen.add(assertion_id)
        definition = session.get(AssertionDefinition, assertion_id)
        if not definition or definition.project_id != project_id:
            raise HTTPException(
                status_code=422,
                detail=f"Assertion definition is not in this project: {assertion_id}",
            )


def _unset_other_defaults(
    session: Session, project_id: str, protocol: str, current_id: str | None = None
) -> None:
    profiles = session.scalars(
        select(AssertionProfile).where(
            AssertionProfile.project_id == project_id,
            AssertionProfile.protocol == protocol,
            AssertionProfile.is_default.is_(True),
        )
    )
    for profile in profiles:
        if profile.id != current_id:
            profile.is_default = False


@definitions_router.get("", response_model=list[AssertionDefinitionRead])
def list_definitions(
    project_id: str | None = Query(default=None), session: Session = Depends(get_session)
) -> list[AssertionDefinition]:
    statement = select(AssertionDefinition).order_by(AssertionDefinition.created_at.desc())
    if project_id:
        statement = statement.where(AssertionDefinition.project_id == project_id)
    return list(session.scalars(statement))


@definitions_router.post("", response_model=AssertionDefinitionRead, status_code=201)
def create_definition(
    payload: AssertionDefinitionCreate, session: Session = Depends(get_session)
) -> AssertionDefinition:
    get_or_404(session, Project, payload.project_id, "Project")
    _validate_definition(payload.engine, payload.config)
    definition = AssertionDefinition(**payload.model_dump())
    session.add(definition)
    session.commit()
    session.refresh(definition)
    return definition


@definitions_router.patch("/{definition_id}", response_model=AssertionDefinitionRead)
def update_definition(
    definition_id: str,
    payload: AssertionDefinitionUpdate,
    session: Session = Depends(get_session),
) -> AssertionDefinition:
    definition = get_or_404(session, AssertionDefinition, definition_id, "Assertion definition")
    values = payload.model_dump(exclude_unset=True)
    _validate_definition(
        values.get("engine", definition.engine), values.get("config", definition.config)
    )
    for field, value in values.items():
        setattr(definition, field, value)
    session.commit()
    session.refresh(definition)
    return definition


@definitions_router.delete("/{definition_id}", status_code=204)
def delete_definition(
    definition_id: str, session: Session = Depends(get_session)
) -> Response:
    definition = get_or_404(session, AssertionDefinition, definition_id, "Assertion definition")
    profiles = session.scalars(
        select(AssertionProfile).where(AssertionProfile.project_id == definition.project_id)
    )
    if any(
        binding.get("assertion_id") == definition_id
        for profile in profiles
        for binding in profile.bindings
    ):
        raise HTTPException(status_code=409, detail="Assertion is referenced by a profile")
    session.delete(definition)
    session.commit()
    return Response(status_code=204)


@profiles_router.get("", response_model=list[AssertionProfileRead])
def list_profiles(
    project_id: str | None = Query(default=None), session: Session = Depends(get_session)
) -> list[AssertionProfile]:
    statement = select(AssertionProfile).order_by(AssertionProfile.created_at.desc())
    if project_id:
        statement = statement.where(AssertionProfile.project_id == project_id)
    return list(session.scalars(statement))


@profiles_router.post("", response_model=AssertionProfileRead, status_code=201)
def create_profile(
    payload: AssertionProfileCreate, session: Session = Depends(get_session)
) -> AssertionProfile:
    get_or_404(session, Project, payload.project_id, "Project")
    _validate_bindings(session, payload.project_id, payload.bindings)
    profile = AssertionProfile(**payload.model_dump())
    session.add(profile)
    session.flush()
    if profile.is_default:
        _unset_other_defaults(session, profile.project_id, profile.protocol, profile.id)
    session.commit()
    session.refresh(profile)
    return profile


@profiles_router.patch("/{profile_id}", response_model=AssertionProfileRead)
def update_profile(
    profile_id: str,
    payload: AssertionProfileUpdate,
    session: Session = Depends(get_session),
) -> AssertionProfile:
    profile = get_or_404(session, AssertionProfile, profile_id, "Assertion profile")
    values = payload.model_dump(exclude_unset=True)
    protocol = values.get("protocol", profile.protocol)
    if protocol != profile.protocol and profile.apis:
        raise HTTPException(status_code=409, detail="Profile protocol cannot change while in use")
    _validate_bindings(session, profile.project_id, values.get("bindings", profile.bindings))
    for field, value in values.items():
        setattr(profile, field, value)
    if profile.is_default:
        _unset_other_defaults(session, profile.project_id, protocol, profile.id)
    session.commit()
    session.refresh(profile)
    return profile


@profiles_router.delete("/{profile_id}", status_code=204)
def delete_profile(profile_id: str, session: Session = Depends(get_session)) -> Response:
    profile = get_or_404(session, AssertionProfile, profile_id, "Assertion profile")
    direct_use = session.scalar(
        select(ApiDefinition.id).where(ApiDefinition.assertion_profile_id == profile_id).limit(1)
    )
    variants = session.scalars(
        select(ApiDefinition).where(ApiDefinition.project_id == profile.project_id)
    )
    variant_use = any(
        profile_id in variant.get("assertion_profile_ids", [])
        for api in variants
        for variant in api.response_variants
    )
    if direct_use or variant_use:
        raise HTTPException(status_code=409, detail="Assertion profile is referenced by an API")
    session.delete(profile)
    session.commit()
    return Response(status_code=204)
