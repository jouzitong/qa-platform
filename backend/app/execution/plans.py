from time import perf_counter
from typing import Any

from sqlalchemy.orm import Session

from app.execution.context import deep_merge
from app.execution.runner import build_request_config, execute_api_once, execute_flow
from app.execution.validation import validate_api_response
from app.models import (
    ApiDefinition,
    ApiTemplate,
    Project,
    TestFlow,
    TestPlan,
    TestPlanRun,
    TestRun,
    utcnow,
)


def _step_run_payload(step_run: Any) -> dict[str, Any]:
    return {
        "id": step_run.id,
        "step_id": step_run.step_id,
        "step_name": step_run.step_name,
        "position": step_run.position,
        "attempt": step_run.attempt,
        "status": step_run.status,
        "duration_ms": step_run.duration_ms,
        "request_snapshot": step_run.request_snapshot,
        "response_snapshot": step_run.response_snapshot,
        "extracted": step_run.extracted,
        "assertion_results": step_run.assertion_results,
        "error": step_run.error,
        "created_at": step_run.created_at.isoformat() if step_run.created_at else None,
    }


def _missing_item_result(item: dict[str, Any], message: str) -> dict[str, Any]:
    return {
        "item_id": item.get("id"),
        "type": item.get("type"),
        "target_id": item.get("target_id"),
        "status": "failed",
        "duration_ms": 0,
        "error": message,
        "details": {},
    }


async def _execute_api_item(
    session: Session,
    api: ApiDefinition,
    inputs: dict[str, Any],
) -> dict[str, Any]:
    started = perf_counter()
    project = session.get(Project, api.project_id)
    context = deep_merge(project.variables if project else {}, inputs)
    template = session.get(ApiTemplate, api.template_id) if api.template_id else None
    try:
        result = await execute_api_once(api, context, template=template)
        request_config = build_request_config(api, context, template=template)
        validation = validate_api_response(
            session,
            api,
            request=request_config,
            response=result.response,
            context=context,
        )
        passed = bool(validation["passed"])
        return {
            "status": "passed" if passed else "failed",
            "duration_ms": (perf_counter() - started) * 1000,
            "error": None if passed else "API response validation failed",
            "details": {
                "request": result.request,
                "response": result.response,
                "validation": validation,
            },
        }
    except Exception as exc:
        return {
            "status": "failed",
            "duration_ms": (perf_counter() - started) * 1000,
            "error": str(exc),
            "details": {},
        }


async def _execute_flow_item(
    session: Session,
    flow: TestFlow,
    inputs: dict[str, Any],
) -> dict[str, Any]:
    child_run = TestRun(flow_id=flow.id, inputs=inputs)
    session.add(child_run)
    session.commit()
    await execute_flow(session, child_run.id)
    session.refresh(child_run)
    return {
        "status": child_run.status,
        "duration_ms": (
            (child_run.finished_at - child_run.started_at).total_seconds() * 1000
            if child_run.finished_at and child_run.started_at
            else 0
        ),
        "run_id": child_run.id,
        "error": child_run.error,
        "details": {
            "context": child_run.context,
            "step_runs": [_step_run_payload(item) for item in child_run.step_runs],
        },
    }


async def execute_plan(session: Session, plan_run_id: str) -> None:
    plan_run = session.get(TestPlanRun, plan_run_id)
    if not plan_run:
        return
    plan = session.get(TestPlan, plan_run.plan_id)
    if not plan:
        plan_run.status = "failed"
        plan_run.error = "Test plan not found"
        plan_run.finished_at = utcnow()
        session.commit()
        return

    items = [item for item in plan.items if item.get("enabled", True)]
    plan_run.status = "running"
    plan_run.started_at = utcnow()
    plan_run.total_count = len(items)
    plan_run.results = []
    session.commit()

    results: list[dict[str, Any]] = []
    for item in items:
        target: ApiDefinition | TestFlow | None
        if item.get("type") == "api":
            target = session.get(ApiDefinition, item.get("target_id"))
        else:
            target = session.get(TestFlow, item.get("target_id"))

        if not target or target.project_id != plan.project_id:
            result = _missing_item_result(item, "计划项引用的资源不存在或不属于当前项目")
        elif item.get("type") == "api":
            result = await _execute_api_item(session, target, plan_run.inputs)
        else:
            result = await _execute_flow_item(session, target, plan_run.inputs)

        result.update(
            {
                "item_id": item.get("id"),
                "type": item.get("type"),
                "target_id": target.id if target else item.get("target_id"),
                "target_key": target.key if target else None,
                "target_name": target.name if target else None,
            }
        )
        results.append(result)
        plan_run.results = list(results)
        plan_run.passed_count = sum(item["status"] == "passed" for item in results)
        plan_run.failed_count = sum(item["status"] == "failed" for item in results)
        session.commit()

    plan_run.status = "failed" if plan_run.failed_count else "passed"
    plan_run.error = "一个或多个计划项执行失败" if plan_run.failed_count else None
    plan_run.finished_at = utcnow()
    session.commit()
