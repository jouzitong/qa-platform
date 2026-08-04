from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.common import commit_or_conflict, get_or_404
from app.database import get_session
from app.models import ApiDefinition, Project, TestFlow
from app.schemas import FlowCreate, FlowRead, FlowUpdate

router = APIRouter(prefix="/flows", tags=["flows"])


def _validate_steps(session: Session, project_id: str, steps: list[dict]) -> None:
    step_ids: set[str] = set()
    for step in steps:
        if step["id"] in step_ids:
            raise HTTPException(status_code=422, detail=f"Duplicate step id: {step['id']}")
        step_ids.add(step["id"])
        definition = session.get(ApiDefinition, step["api_id"])
        if not definition or definition.project_id != project_id:
            raise HTTPException(
                status_code=422,
                detail=f"API does not belong to this project: {step['api_id']}",
            )


@router.get("", response_model=list[FlowRead])
def list_flows(
    project_id: str | None = Query(default=None), session: Session = Depends(get_session)
) -> list[TestFlow]:
    statement = select(TestFlow).order_by(TestFlow.created_at.desc())
    if project_id:
        statement = statement.where(TestFlow.project_id == project_id)
    return list(session.scalars(statement))


@router.post("", response_model=FlowRead, status_code=201)
def create_flow(payload: FlowCreate, session: Session = Depends(get_session)) -> TestFlow:
    get_or_404(session, Project, payload.project_id, "Project")
    values = payload.model_dump(mode="json")
    _validate_steps(session, payload.project_id, values["steps"])
    flow = TestFlow(**values)
    session.add(flow)
    commit_or_conflict(session, "Test flow key already exists in this project")
    session.refresh(flow)
    return flow


@router.get("/{flow_id}", response_model=FlowRead)
def get_flow(flow_id: str, session: Session = Depends(get_session)) -> TestFlow:
    return get_or_404(session, TestFlow, flow_id, "Flow")


@router.patch("/{flow_id}", response_model=FlowRead)
def update_flow(
    flow_id: str, payload: FlowUpdate, session: Session = Depends(get_session)
) -> TestFlow:
    flow = get_or_404(session, TestFlow, flow_id, "Flow")
    values = payload.model_dump(exclude_none=True, mode="json")
    if "steps" in values:
        _validate_steps(session, flow.project_id, values["steps"])
    for field, value in values.items():
        setattr(flow, field, value)
    commit_or_conflict(session, "Test flow key already exists in this project")
    session.refresh(flow)
    return flow


@router.delete("/{flow_id}", status_code=204)
def delete_flow(flow_id: str, session: Session = Depends(get_session)) -> Response:
    session.delete(get_or_404(session, TestFlow, flow_id, "Flow"))
    session.commit()
    return Response(status_code=204)
