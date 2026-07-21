import asyncio
from typing import Any

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.common import get_or_404
from app.database import SessionLocal, get_session
from app.execution.events import run_events
from app.execution.runner import execute_flow
from app.models import TestFlow, TestRun
from app.schemas import ExecuteRequest, RunRead

router = APIRouter(tags=["runs"])
_running_tasks: set[asyncio.Task[None]] = set()


def _run_in_new_session(run_id: str):
    async def run() -> None:
        with SessionLocal() as session:
            await execute_flow(session, run_id)

    return run()


@router.post("/flows/{flow_id}/runs", response_model=RunRead, status_code=202)
async def create_run(
    flow_id: str, payload: ExecuteRequest, session: Session = Depends(get_session)
) -> TestRun:
    get_or_404(session, TestFlow, flow_id, "Flow")
    run = TestRun(flow_id=flow_id, inputs=payload.inputs)
    session.add(run)
    session.commit()
    session.refresh(run)
    task = asyncio.create_task(_run_in_new_session(run.id))
    _running_tasks.add(task)
    task.add_done_callback(_running_tasks.discard)
    return run


@router.get("/runs", response_model=list[RunRead])
def list_runs(
    flow_id: str | None = Query(default=None), session: Session = Depends(get_session)
) -> list[TestRun]:
    statement = (
        select(TestRun)
        .options(selectinload(TestRun.step_runs))
        .order_by(TestRun.created_at.desc())
    )
    if flow_id:
        statement = statement.where(TestRun.flow_id == flow_id)
    return list(session.scalars(statement))


@router.get("/runs/{run_id}", response_model=RunRead)
def get_run(run_id: str, session: Session = Depends(get_session)) -> TestRun:
    statement = (
        select(TestRun)
        .where(TestRun.id == run_id)
        .options(selectinload(TestRun.step_runs))
    )
    run = session.scalar(statement)
    if not run:
        return get_or_404(session, TestRun, run_id, "Run")
    return run


@router.websocket("/ws/runs/{run_id}")
async def stream_run(websocket: WebSocket, run_id: str) -> None:
    await websocket.accept()
    queue = run_events.subscribe(run_id)
    try:
        with SessionLocal() as session:
            run = session.get(TestRun, run_id)
            if not run:
                await websocket.send_json({"type": "error", "error": "Run not found"})
                await websocket.close(code=4404)
                return
            await websocket.send_json({"type": "snapshot", "run_id": run.id, "status": run.status})
            if run.status in {"passed", "failed", "cancelled"}:
                await websocket.close()
                return
        while True:
            event: dict[str, Any] = await queue.get()
            await websocket.send_json(event)
            if event["type"] == "run_finished":
                await websocket.close()
                return
    except WebSocketDisconnect:
        pass
    finally:
        run_events.unsubscribe(run_id, queue)
