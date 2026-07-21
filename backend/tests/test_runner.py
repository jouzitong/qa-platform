import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.execution.protocols import ExecutionResult
from app.execution.runner import execute_flow
from app.models import ApiDefinition, ApiTemplate, Project
from app.models import TestFlow as FlowModel
from app.models import TestRun as RunModel


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
