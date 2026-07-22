import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.execution.expression import ExpressionError, evaluate_expression
from app.execution.validation import validate_api_response
from app.main import app
from app.models import ApiDefinition, AssertionDefinition, AssertionProfile, Project


def test_safe_expression_supports_business_rules_and_blocks_code_execution() -> None:
    result = evaluate_expression(
        "response.status_code == 200 and len(response.body['data']) > params['minimum']",
        {
            "response": {"status_code": 200, "body": {"data": [1, 2]}},
            "request": {},
            "context": {},
            "params": {"minimum": 1},
        },
    )
    assert result is True

    with pytest.raises(ExpressionError, match="Only whitelisted"):
        evaluate_expression("__import__('os').getenv('HOME')", {})


def test_default_profile_is_bound_only_to_new_apis() -> None:
    with TestClient(app) as client:
        project = client.post(
            "/api/v1/projects", json={"name": "assertion-default-project"}
        ).json()
        definition = client.post(
            "/api/v1/assertion-definitions",
            json={
                "project_id": project["id"],
                "name": "success-code",
                "engine": "expression",
                "config": {"expression": "response.body['code'] == 0"},
            },
        )
        assert definition.status_code == 201
        profile = client.post(
            "/api/v1/assertion-profiles",
            json={
                "project_id": project["id"],
                "name": "default-http",
                "protocol": "http",
                "is_default": True,
                "bindings": [{"assertion_id": definition.json()["id"], "params": {}}],
            },
        )
        assert profile.status_code == 201

        api_response = client.post(
            "/api/v1/apis",
            json={
                "project_id": project["id"],
                "name": "health-with-default",
                "protocol": "http",
                "request": {"url": "https://example.test"},
            },
        )
        assert api_response.status_code == 201
        assert api_response.json()["assertion_profile_id"] == profile.json()["id"]

        unbound = client.post(
            "/api/v1/apis",
            json={
                "project_id": project["id"],
                "name": "health-explicitly-unbound",
                "protocol": "http",
                "assertion_profile_id": None,
                "request": {"url": "https://example.test"},
            },
        )
        assert unbound.status_code == 201
        assert unbound.json()["assertion_profile_id"] is None


def test_response_variant_collects_profile_schema_and_warning_results() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        project = Project(name="variant-project")
        session.add(project)
        session.flush()
        definition = AssertionDefinition(
            project_id=project.id,
            name="latency-warning",
            engine="expression",
            config={"expression": "response.elapsed_ms < params['max_ms']"},
            default_params={"max_ms": 100},
            severity="warning",
            message="响应较慢",
        )
        session.add(definition)
        session.flush()
        profile = AssertionProfile(
            project_id=project.id,
            name="success",
            protocol="http",
            bindings=[{"assertion_id": definition.id}],
        )
        session.add(profile)
        session.flush()
        api = ApiDefinition(
            project_id=project.id,
            name="order-not-found",
            protocol="http",
            response_variants=[
                {
                    "name": "not-found",
                    "match": "response.status_code == 404",
                    "assertion_profile_ids": [profile.id],
                    "schema": {
                        "type": "object",
                        "required": ["code"],
                        "properties": {"code": {"type": "string"}},
                    },
                    "assertions": [
                        {
                            "assertion_id": "variant:error-code",
                            "name": "错误码",
                            "engine": "path",
                            "config": {
                                "source": "body.code",
                                "operator": "equals",
                                "expected": "NOT_FOUND",
                            },
                        }
                    ],
                }
            ],
        )
        session.add(api)
        session.commit()

        validation = validate_api_response(
            session,
            api,
            request={},
            response={
                "status_code": 404,
                "elapsed_ms": 250,
                "body": {"code": "NOT_FOUND"},
            },
            context={},
        )

        assert validation["passed"] is True
        assert validation["variant"] == "not-found"
        assert len(validation["results"]) == 3
        assert validation["results"][0]["severity"] == "warning"
        assert validation["results"][0]["passed"] is False
