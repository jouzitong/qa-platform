from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.common import get_or_404
from app.database import get_session
from app.execution.context import deep_merge
from app.execution.runner import execute_api_once
from app.models import ApiDefinition, ApiTemplate, Project, TestFlow
from app.schemas import ApiCreate, ApiRead, ApiUpdate, ExecuteRequest

router = APIRouter(prefix="/apis", tags=["apis"])


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
    definition = ApiDefinition(**payload.model_dump())
    session.add(definition)
    session.commit()
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
    _validate_template(
        session, definition.project_id, target_protocol, target_template_id
    )
    for field, value in values.items():
        setattr(definition, field, value)
    session.commit()
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
    return {"request": result.request, "response": result.response}
