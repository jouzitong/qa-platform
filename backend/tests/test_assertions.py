import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.execution.expression import ExpressionError, evaluate_expression
from app.execution.validation import validate_api_response
from app.main import app
from app.models import ApiDefinition, AssertionDefinition, Project
from app.success_contract import default_success_contract


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


def test_random_expression_helpers_support_lengths_and_ranges() -> None:
    uuid_value = evaluate_expression("random.uuid(32)", {})
    string_value = evaluate_expression("random.string(10)", {})
    integer_value = evaluate_expression("random.int(5, 8)", {})
    float_value = evaluate_expression("random.float(1.5, 2.5)", {})

    assert len(uuid_value) == 32
    assert len(string_value) == 10
    assert 5 <= integer_value <= 8
    assert 1.5 <= float_value <= 2.5


def test_success_assertion_type_is_recorded_and_blocks_when_condition_fails() -> None:
    from app.execution.assertions import evaluate_assertion_rules

    passed = evaluate_assertion_rules(
        {"status_code": 200},
        [{
            "assertion_id": "success-status",
            "engine": "path",
            "config": {"source": "status_code", "operator": "equals", "expected": 200},
            "severity": "success",
        }],
    )
    assert passed["passed"] is True
    assert passed["results"][0]["severity"] == "success"

    failed = evaluate_assertion_rules(
        {"status_code": 500},
        [{
            "assertion_id": "success-status",
            "engine": "path",
            "config": {"source": "status_code", "operator": "equals", "expected": 200},
            "severity": "success",
        }],
    )
    assert failed["passed"] is False

    failed_warning = evaluate_assertion_rules(
        {"status_code": 500},
        [{
            "assertion_id": "warning-shaped-success-condition",
            "engine": "path",
            "config": {"source": "status_code", "operator": "equals", "expected": 200},
            "severity": "warning",
        }],
    )
    assert failed_warning["passed"] is False
    assert failed_warning["results"][0]["severity"] == "success"


def test_success_contract_requires_status_and_success_body() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        project = Project(name="success-contract-project")
        session.add(project)
        session.flush()
        api = ApiDefinition(
            project_id=project.id,
            key="login",
            name="登录",
            protocol="http",
            success_contract=default_success_contract(),
        )
        session.add(api)
        session.commit()

        passed = validate_api_response(
            session,
            api,
            request={},
            response={"status_code": 200, "body": {"code": 0, "data": {"token": "ok"}}},
            context={},
        )
        assert passed["passed"] is True
        assert passed["success_contract"] is True

        wrong_body = validate_api_response(
            session,
            api,
            request={},
            response={"status_code": 200, "body": {"code": 1, "data": {}}},
            context={},
        )
        assert wrong_body["passed"] is False

        wrong_status = validate_api_response(
            session,
            api,
            request={},
            response={"status_code": 500, "body": {"code": 0, "data": {}}},
            context={},
        )
        assert wrong_status["passed"] is False

        disabled_system_rules = validate_api_response(
            session,
            api,
            request={},
            response={"status_code": 500, "body": {"code": 1}},
            context={},
            step_disabled_assertion_ids=[
                "system:success-status", "system:success-body-schema"
            ],
        )
        assert disabled_system_rules["passed"] is False


def test_success_assertion_is_the_source_of_truth_over_legacy_contract() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        project = Project(name="success-condition-project")
        session.add(project)
        session.flush()
        definition = AssertionDefinition(
            project_id=project.id,
            key="business-ok",
            name="业务成功",
            engine="path",
            config={"source": "body.ok", "operator": "equals", "expected": True},
            severity="success",
        )
        session.add(definition)
        session.flush()
        api = ApiDefinition(
            project_id=project.id,
            key="assertion-driven",
            name="assertion-driven",
            protocol="http",
            success_assertion_id=definition.id,
            success_contract=default_success_contract(),
        )
        session.add(api)
        session.commit()

        validation = validate_api_response(
            session,
            api,
            request={},
            response={"status_code": 500, "body": {"ok": True}},
            context={},
        )

        assert validation["passed"] is True
        assert validation["success_contract"] is False
        assert validation["success_assertion_id"] == definition.id


def test_api_directly_references_one_success_assertion() -> None:
    with TestClient(app) as client:
        project = client.post(
            "/api/v1/projects", json={"name": "assertion-default-project"}
        ).json()
        definition = client.post(
            "/api/v1/assertion-definitions",
            json={
                "project_id": project["id"],
                "key": "success-code",
                "name": "success-code",
                "engine": "expression",
                "config": {"expression": "response.body['code'] == 0"},
                "severity": "success",
            },
        )
        assert definition.status_code == 201
        assert definition.json()["severity"] == "success"
        api_response = client.post(
            "/api/v1/apis",
            json={
                "project_id": project["id"],
                "key": "health-with-default",
                "name": "health-with-default",
                "protocol": "http",
                "success_assertion_id": definition.json()["id"],
                "request": {"url": "https://example.test"},
            },
        )
        assert api_response.status_code == 201
        assert api_response.json()["success_assertion_id"] == definition.json()["id"]

        unbound = client.post(
            "/api/v1/apis",
            json={
                "project_id": project["id"],
                "key": "health-explicitly-unbound",
                "name": "health-explicitly-unbound",
                "protocol": "http",
                "request": {"url": "https://example.test"},
            },
        )
        assert unbound.status_code == 201
        assert unbound.json()["success_assertion_id"] is None
        assert client.get("/api/v1/assertion-profiles").status_code == 404


def test_legacy_response_variant_collects_assertion_and_schema_results() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        project = Project(name="variant-project")
        session.add(project)
        session.flush()
        definition = AssertionDefinition(
            project_id=project.id,
            key="latency-warning",
            name="latency-warning",
            engine="expression",
            config={"expression": "response.elapsed_ms < params['max_ms']"},
            default_params={"max_ms": 100},
            severity="success",
            message="响应较慢",
        )
        session.add(definition)
        session.flush()
        api = ApiDefinition(
            project_id=project.id,
            key="order-not-found",
            name="order-not-found",
            protocol="http",
            response_variants=[
                {
                    "name": "not-found",
                    "match": "response.status_code == 404",
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
                "elapsed_ms": 50,
                "body": {"code": "NOT_FOUND"},
            },
            context={},
        )

        assert validation["passed"] is True
        assert validation["variant"] == "not-found"
        assert len(validation["results"]) == 2
        assert validation["results"][0]["severity"] == "success"
        assert validation["results"][0]["passed"] is True
