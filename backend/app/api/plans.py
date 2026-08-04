import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.common import commit_or_conflict, get_or_404
from app.database import SessionLocal, get_session
from app.execution.plans import execute_plan
from app.models import ApiDefinition, Project, TestFlow, TestPlan, TestPlanRun
from app.schemas import ExecuteRequest, TestPlanCreate, TestPlanRead, TestPlanRunRead, TestPlanUpdate

router = APIRouter(prefix="/test-plans", tags=["test-plans"])
runs_router = APIRouter(tags=["test-plans"])
_running_tasks: set[asyncio.Task[None]] = set()


def _validate_items(session: Session, project_id: str, items: list[dict]) -> None:
    item_ids: set[str] = set()
    for item in items:
        if item["id"] in item_ids:
            raise HTTPException(status_code=422, detail=f"Duplicate plan item id: {item['id']}")
        item_ids.add(item["id"])
        model = ApiDefinition if item["type"] == "api" else TestFlow
        target = session.get(model, item["target_id"])
        if not target or target.project_id != project_id:
            raise HTTPException(
                status_code=422,
                detail=f"Plan item resource does not belong to this project: {item['target_id']}",
            )


def _run_in_new_session(plan_run_id: str):
    async def run() -> None:
        with SessionLocal() as session:
            await execute_plan(session, plan_run_id)

    return run()


@router.get("", response_model=list[TestPlanRead])
def list_plans(
    project_id: str | None = Query(default=None), session: Session = Depends(get_session)
) -> list[TestPlan]:
    statement = select(TestPlan).order_by(TestPlan.updated_at.desc())
    if project_id:
        statement = statement.where(TestPlan.project_id == project_id)
    return list(session.scalars(statement))


@router.post("", response_model=TestPlanRead, status_code=201)
def create_plan(payload: TestPlanCreate, session: Session = Depends(get_session)) -> TestPlan:
    get_or_404(session, Project, payload.project_id, "Project")
    values = payload.model_dump(mode="json")
    _validate_items(session, payload.project_id, values["items"])
    plan = TestPlan(**values)
    session.add(plan)
    commit_or_conflict(session, "Test plan key already exists in this project")
    session.refresh(plan)
    return plan


@router.get("/{plan_id}", response_model=TestPlanRead)
def get_plan(plan_id: str, session: Session = Depends(get_session)) -> TestPlan:
    return get_or_404(session, TestPlan, plan_id, "Test plan")


@router.patch("/{plan_id}", response_model=TestPlanRead)
def update_plan(
    plan_id: str, payload: TestPlanUpdate, session: Session = Depends(get_session)
) -> TestPlan:
    plan = get_or_404(session, TestPlan, plan_id, "Test plan")
    values = payload.model_dump(exclude_none=True, mode="json")
    if "items" in values:
        _validate_items(session, plan.project_id, values["items"])
    for field, value in values.items():
        setattr(plan, field, value)
    commit_or_conflict(session, "Test plan key already exists in this project")
    session.refresh(plan)
    return plan


@router.delete("/{plan_id}", status_code=204)
def delete_plan(plan_id: str, session: Session = Depends(get_session)) -> Response:
    session.delete(get_or_404(session, TestPlan, plan_id, "Test plan"))
    session.commit()
    return Response(status_code=204)


@router.get("/{plan_id}/runs", response_model=list[TestPlanRunRead])
def list_plan_runs(plan_id: str, session: Session = Depends(get_session)) -> list[TestPlanRun]:
    get_or_404(session, TestPlan, plan_id, "Test plan")
    statement = (
        select(TestPlanRun)
        .where(TestPlanRun.plan_id == plan_id)
        .order_by(TestPlanRun.created_at.desc())
    )
    return list(session.scalars(statement))


@router.post("/{plan_id}/runs", response_model=TestPlanRunRead, status_code=202)
async def create_plan_run(
    plan_id: str, payload: ExecuteRequest, session: Session = Depends(get_session)
) -> TestPlanRun:
    plan = get_or_404(session, TestPlan, plan_id, "Test plan")
    enabled_count = sum(item.get("enabled", True) for item in plan.items)
    if not enabled_count:
        raise HTTPException(status_code=422, detail="Test plan must contain at least one enabled item")
    run = TestPlanRun(plan_id=plan_id, inputs=payload.inputs, total_count=enabled_count)
    session.add(run)
    session.commit()
    session.refresh(run)
    task = asyncio.create_task(_run_in_new_session(run.id))
    _running_tasks.add(task)
    task.add_done_callback(_running_tasks.discard)
    return run


@runs_router.get("/test-plan-runs/{run_id}", response_model=TestPlanRunRead)
def get_plan_run(run_id: str, session: Session = Depends(get_session)) -> TestPlanRun:
    return get_or_404(session, TestPlanRun, run_id, "Test plan run")
