from fastapi import APIRouter, Depends, HTTPException, Query, Response
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.common import commit_or_conflict, get_or_404
from app.database import get_session
from app.execution.expression import ExpressionError, parse_expression
from app.models import ApiDefinition, AssertionDefinition, Project
from app.schemas import (
    AssertionDefinitionCreate,
    AssertionDefinitionRead,
    AssertionDefinitionUpdate,
)

definitions_router = APIRouter(
    prefix="/assertion-definitions", tags=["assertion-definitions"]
)


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
    commit_or_conflict(session, "Assertion name or key already exists in this project")
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
    commit_or_conflict(session, "Assertion name or key already exists in this project")
    session.refresh(definition)
    return definition


@definitions_router.delete("/{definition_id}", status_code=204)
def delete_definition(
    definition_id: str, session: Session = Depends(get_session)
) -> Response:
    definition = get_or_404(session, AssertionDefinition, definition_id, "Assertion definition")
    direct_use = session.scalar(
        select(ApiDefinition.id).where(
            ApiDefinition.success_assertion_id == definition_id
        ).limit(1)
    )
    if direct_use:
        raise HTTPException(status_code=409, detail="成功条件已被 API 引用，无法删除")
    session.delete(definition)
    session.commit()
    return Response(status_code=204)
