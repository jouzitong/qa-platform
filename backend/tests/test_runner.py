import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.execution.plans import execute_plan
from app.execution.protocols import ExecutionResult, _resolve_url
from app.execution.response import ResponseUnpackError, attach_payload
from app.execution.runner import build_request_config, execute_api_once, execute_flow
from app.models import (
    ApiDefinition,
    ApiTemplate,
    Project,
)


def test_response_unpack_keeps_wire_body_and_exposes_payload() -> None:
    response = attach_payload(
        {"status_code": 200, "body": {"code": 0, "data": {"id": 1}}},
        {"enabled": True, "source": "body.data"},
    )

    assert response["body"] == {"code": 0, "data": {"id": 1}}
    assert response["payload"] == {"id": 1}
    assert response["payload_source"] == "body.data"


def test_response_unpack_reports_missing_path_and_legacy_payload_fallback() -> None:
    with pytest.raises(ResponseUnpackError, match="响应解包路径不存在"):
        attach_payload(
            {"status_code": 200, "body": {"code": 0}},
            {"enabled": True, "source": "body.data"},
        )

    response = attach_payload({"status_code": 200, "body": {"status": "ok"}}, {})
    assert response["payload"] == response["body"]


@pytest.mark.asyncio
async def test_execute_api_once_attaches_unpacked_payload(monkeypatch) -> None:
    api = ApiDefinition(
        project_id="project",
        key="wrapped",
        name="wrapped",
        protocol="http",
        request={"method": "GET", "base_url": "https://example.test", "path": "/wrapped"},
        response_unpack={"enabled": True, "source": "body.data"},
        parameters=[],
    )

    async def fake_http(_config):
        return ExecutionResult(
            request={"path": "/wrapped"},
            response={"status_code": 200, "body": {"code": 0, "data": {"ok": True}}},
        )

    monkeypatch.setattr("app.execution.runner.execute_http", fake_http)
    result = await execute_api_once(api, {})

    assert result.response["body"]["code"] == 0
    assert result.response["payload"] == {"ok": True}
from app.models import (
    TestFlow as FlowModel,
)
from app.models import (
    TestPlan as PlanModel,
)
from app.models import (
    TestPlanRun as PlanRunModel,
)
from app.models import (
    TestRun as RunModel,
)


def test_parameter_defaults_build_request_values_and_inputs_override() -> None:
    api = ApiDefinition(
        project_id="project",
        key="search",
        name="search",
        protocol="http",
        request={
            "method": "GET",
            "base_url": "https://example.test",
            "path": "/users/{user_id}",
            "body": {"user_id": "legacy"},
        },
        parameters=[
            {"name": "user_id", "in": "path", "type": "integer", "default": "42"},
            {"name": "page", "in": "query", "type": "integer", "default": "1"},
            {"name": "X-Client", "in": "header", "type": "string", "default": "qa"},
            {"name": "enabled", "in": "body", "type": "boolean", "default": "true"},
        ],
    )

    defaults = build_request_config(api, {})
    assert defaults["path_params"] == {"user_id": 42}
    assert defaults["query"] == {"page": 1}
    assert defaults["headers"] == {"X-Client": "qa"}
    assert defaults["body"] == {"user_id": "legacy", "enabled": True}
    assert defaults["path"] == "/users/42"

    overridden = build_request_config(
        api,
        {"user_id": 7},
        request_override={"query": {"page": 3}},
    )
    assert overridden["path_params"] == {"user_id": 7}
    assert overridden["query"] == {"page": 3}
    assert overridden["path"] == "/users/7"


def test_object_parameter_children_build_nested_body_and_accept_nested_inputs() -> None:
    api = ApiDefinition(
        project_id="project",
        key="validate",
        name="validate",
        protocol="http",
        request={
            "method": "POST",
            "base_url": "https://example.test",
            "path": "/validate",
        },
        parameters=[
            {
                "name": "chunkMethod",
                "in": "body",
                "type": "object",
                "required": True,
                "children": [
                    {"name": "mode", "type": "string", "default": "custom"},
                    {"name": "maxTokens", "type": "integer", "default": "1024"},
                ],
            }
        ],
    )

    defaults = build_request_config(api, {})
    assert defaults["body"] == {
        "chunkMethod": {"mode": "custom", "maxTokens": 1024}
    }

    nested = build_request_config(
        api,
        {"chunkMethod": {"mode": "semantic", "maxTokens": "2048"}},
    )
    assert nested["body"] == {
        "chunkMethod": {"mode": "semantic", "maxTokens": 2048}
    }

    dotted = build_request_config(api, {"chunkMethod.mode": "hybrid"})
    assert dotted["body"] == {
        "chunkMethod": {"mode": "hybrid", "maxTokens": 1024}
    }


def test_object_parameter_child_params_alias_and_parent_value_merge() -> None:
    api = ApiDefinition(
        project_id="project",
        key="object-alias",
        name="object-alias",
        protocol="http",
        request={"method": "POST", "base_url": "https://example.test", "path": "/object"},
        parameters=[
            {
                "name": "options",
                "in": "body",
                "type": "object",
                "child_params": [
                    {"name": "enabled", "type": "boolean", "default": "true"},
                ],
            }
        ],
    )

    request = build_request_config(
        api,
        {"options": {"existing": "kept"}, "options.enabled": "false"},
    )

    assert request["body"] == {"options": {"existing": "kept", "enabled": False}}


def test_path_only_api_uses_project_base_url() -> None:
    http_api = ApiDefinition(
        project_id="project",
        key="health",
        name="health",
        protocol="http",
        request={"method": "GET", "path": "/health"},
        parameters=[],
    )
    http_request = build_request_config(http_api, {"base_url": "127.0.0.1:8080"})

    assert http_request["base_url"] == "127.0.0.1:8080"
    assert _resolve_url(http_request) == "http://127.0.0.1:8080/health"

    ws_api = ApiDefinition(
        project_id="project",
        key="events",
        name="events",
        protocol="ws",
        request={"path": "/events"},
        parameters=[],
    )
    ws_request = build_request_config(ws_api, {"base_url": "127.0.0.1:9000"})

    assert ws_request["base_url"] == "127.0.0.1:9000"
    assert _resolve_url(ws_request, scheme="ws") == "ws://127.0.0.1:9000/events"


@pytest.mark.asyncio
async def test_flow_retries_and_updates_context(monkeypatch) -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    calls = 0

    async def fake_http(config):
        nonlocal calls
        calls += 1
        assert config["base_url"] == "https://example.test"
        assert config["path"] == "/login"
        assert config["headers"] == {"X-Common": "template", "X-API": "override"}
        status = 503 if calls == 1 else 200
        return ExecutionResult(
            request={"base_url": config["base_url"], "path": config["path"]},
            response={"status_code": status, "body": {"token": "done"}},
        )

    monkeypatch.setattr("app.execution.runner.execute_http", fake_http)

    with Session(engine, expire_on_commit=False) as session:
        project = Project(name="demo", variables={"base_url": "https://example.test"})
        session.add(project)
        session.flush()
        template = ApiTemplate(
            project_id=project.id,
            name="common",
            protocol="http",
            request={
                "base_url": "{{ base_url }}",
                "headers": {"X-Common": "template", "X-API": "template"},
            },
        )
        session.add(template)
        session.flush()
        api = ApiDefinition(
            project_id=project.id,
            template_id=template.id,
            key="login",
            name="login",
            protocol="http",
            request={
                "method": "POST",
                "path": "/login",
                "headers": {"X-API": "override"},
            },
        )
        session.add(api)
        session.flush()
        flow = FlowModel(
            project_id=project.id,
            key="smoke",
            name="smoke",
            steps=[
                {
                    "id": "login",
                    "name": "Login",
                    "api_id": api.id,
                    "retry": {"max_attempts": 2},
                    "assertions": [
                        {"source": "status_code", "operator": "equals", "expected": 200}
                    ],
                    "extractors": [{"name": "token", "source": "body.token"}],
                }
            ],
        )
        session.add(flow)
        session.flush()
        run = RunModel(flow_id=flow.id, inputs={})
        session.add(run)
        session.commit()

        await execute_flow(session, run.id)
        session.refresh(run)

        assert run.status == "passed"
        assert run.context["token"] == "done"
        assert [item.status for item in run.step_runs] == ["failed", "passed"]


@pytest.mark.asyncio
async def test_test_plan_executes_flow_and_records_details(monkeypatch) -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    async def fake_http(config):
        return ExecutionResult(
            request={"base_url": config["base_url"], "path": config["path"]},
            response={"status_code": 200, "body": {"ok": True}},
        )

    monkeypatch.setattr("app.execution.runner.execute_http", fake_http)

    with Session(engine, expire_on_commit=False) as session:
        project = Project(name="plan-project", variables={"base_url": "https://example.test"})
        session.add(project)
        session.flush()
        api = ApiDefinition(
            project_id=project.id,
            key="health",
            name="health",
            protocol="http",
            request={"method": "GET", "base_url": "https://example.test", "path": "/health"},
        )
        session.add(api)
        session.flush()
        flow = FlowModel(
            project_id=project.id,
            key="smoke",
            name="smoke",
            steps=[
                {
                    "id": "health",
                    "name": "Health",
                    "api_id": api.id,
                    "assertions": [
                        {"source": "status_code", "operator": "equals", "expected": 200}
                    ],
                }
            ],
        )
        session.add(flow)
        session.flush()
        plan = PlanModel(
            project_id=project.id,
            key="release.smoke",
            version="v1.0.0",
            name="Release smoke",
            items=[{"id": "flow-item", "type": "flow", "target_id": flow.id}],
        )
        session.add(plan)
        session.flush()
        plan_run = PlanRunModel(plan_id=plan.id, inputs={})
        session.add(plan_run)
        session.commit()

        await execute_plan(session, plan_run.id)
        session.refresh(plan_run)

        assert plan_run.status == "passed"
        assert plan_run.total_count == 1
        assert plan_run.passed_count == 1
        assert plan_run.failed_count == 0
        assert plan_run.results[0]["target_key"] == "smoke"
        assert plan_run.results[0]["details"]["step_runs"][0]["status"] == "passed"
