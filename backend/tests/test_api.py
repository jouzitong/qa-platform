from fastapi.testclient import TestClient

from app.main import app


def test_project_api_round_trip() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/projects",
            json={"name": "api-test", "variables": {"base_url": "https://example.test"}},
        )
        assert response.status_code == 201
        project_id = response.json()["id"]

        response = client.get(f"/api/v1/projects/{project_id}")
        assert response.status_code == 200
        assert response.json()["variables"]["base_url"] == "https://example.test"

        response = client.patch(
            f"/api/v1/projects/{project_id}", json={"description": "updated"}
        )
        assert response.status_code == 200
        assert response.json()["description"] == "updated"

        response = client.post(
            "/api/v1/api-templates",
            json={
                "project_id": project_id,
                "name": "common-http",
                "protocol": "http",
                "request": {
                    "base_url": "{{ base_url }}",
                    "headers": {"X-Client": "qa-platform"},
                },
            },
        )
        assert response.status_code == 201
        template_id = response.json()["id"]

        response = client.post(
            "/api/v1/apis",
            json={
                "project_id": project_id,
                "template_id": template_id,
                "key": "health",
                "name": "health",
                "protocol": "http",
                "request": {"method": "GET", "path": "/health"},
                "request_schema": {
                    "accept": "application/vnd.health+json",
                    "schema": {"type": "object", "required": ["status"]},
                },
                "response_schema": {
                    "type": "object",
                    "required": ["status"],
                    "properties": {"status": {"type": "string", "example": "ok"}},
                },
            },
        )
        assert response.status_code == 201
        assert response.json()["key"] == "health"
        assert response.json()["request"]["headers"] == {
            "X-trade-id": "{{ random.uuid(32) }}",
            "Accept": "application/vnd.health+json",
        }
        assert response.json()["request_schema"]["accept"] == "application/vnd.health+json"
        assert response.json()["request_schema"]["schema"]["required"] == ["status"]
        assert response.json()["response_schema"]["properties"]["status"]["example"] == "ok"
        assert response.json()["success_contract"]["body_schema"] == response.json()["response_schema"]
        api_id = response.json()["id"]

        updated_response_schema = {
            "type": "object",
            "required": ["code"],
            "properties": {"code": {"type": "integer", "const": 0}},
        }
        response = client.patch(
            f"/api/v1/apis/{api_id}",
            json={"response_schema": updated_response_schema},
        )
        assert response.status_code == 200
        assert response.json()["response_schema"] == updated_response_schema
        assert response.json()["success_contract"]["body_schema"] == updated_response_schema

        websocket_response = client.post(
            "/api/v1/apis",
            json={
                "project_id": project_id,
                "key": "health-events",
                "name": "health-events",
                "protocol": "ws",
                "request": {"url": "wss://example.test/events"},
            },
        )
        assert websocket_response.status_code == 201
        assert websocket_response.json()["success_contract"] == {
            "messages": {"min": 1},
            "body_schema": {},
        }

        response = client.get(f"/api/v1/api-templates/{template_id}")
        assert response.status_code == 200
        assert response.json()["usage_count"] == 1

        response = client.delete(f"/api/v1/api-templates/{template_id}")
        assert response.status_code == 409

        response = client.patch(f"/api/v1/apis/{api_id}", json={"template_id": None})
        assert response.status_code == 200
        assert response.json()["template_id"] is None

        response = client.delete(f"/api/v1/api-templates/{template_id}")
        assert response.status_code == 204


def test_asset_keys_are_unique_within_a_project() -> None:
    with TestClient(app) as client:
        project = client.post("/api/v1/projects", json={"name": "asset-key-project"}).json()
        api_payload = {
            "project_id": project["id"],
            "key": "health",
            "name": "健康检查",
            "protocol": "http",
            "request": {"url": "https://example.test/health"},
        }
        api_response = client.post("/api/v1/apis", json=api_payload)
        assert api_response.status_code == 201

        duplicate_api = client.post("/api/v1/apis", json={**api_payload, "name": "健康检查 2"})
        assert duplicate_api.status_code == 409

        assertion_payload = {
            "project_id": project["id"],
            "key": "success",
            "name": "成功响应",
            "engine": "expression",
            "config": {"expression": "response.status_code == 200"},
        }
        assertion_response = client.post("/api/v1/assertion-definitions", json=assertion_payload)
        assert assertion_response.status_code == 201
        duplicate_assertion = client.post(
            "/api/v1/assertion-definitions",
            json={**assertion_payload, "name": "成功响应 2"},
        )
        assert duplicate_assertion.status_code == 409

        flow_payload = {
            "project_id": project["id"],
            "key": "health-smoke",
            "name": "健康冒烟",
            "steps": [
                {
                    "id": "health",
                    "name": "健康检查",
                    "api_id": api_response.json()["id"],
                }
            ],
        }
        flow_response = client.post("/api/v1/flows", json=flow_payload)
        assert flow_response.status_code == 201
        duplicate_flow = client.post(
            "/api/v1/flows", json={**flow_payload, "name": "健康冒烟 2"}
        )
        assert duplicate_flow.status_code == 409


def test_response_unpack_round_trip_and_protocol_validation() -> None:
    with TestClient(app) as client:
        project = client.post(
            "/api/v1/projects",
            json={"name": "response-unpack-project", "variables": {"base_url": "127.0.0.1:8080"}},
        ).json()
        payload = {
            "project_id": project["id"],
            "key": "wrapped-health",
            "name": "包装响应健康检查",
            "protocol": "http",
            "request": {"method": "GET", "path": "/health"},
            "response_schema": {
                "type": "object",
                "properties": {"status": {"type": "string", "example": "ok"}},
            },
            "response_unpack": {"enabled": True, "source": "body.data"},
        }
        created = client.post("/api/v1/apis", json=payload)
        assert created.status_code == 201
        api = created.json()
        assert api["response_unpack"] == {"enabled": True, "source": "body.data"}
        assert api["response_schema"] == payload["response_schema"]
        assert api["success_contract"]["body_schema"] == payload["response_schema"]

        updated = client.patch(
            f"/api/v1/apis/{api['id']}",
            json={"response_unpack": {"enabled": False, "source": "body.data"}},
        )
        assert updated.status_code == 200
        assert updated.json()["response_unpack"] == {"enabled": False}

        ws = client.post(
            "/api/v1/apis",
            json={
                "project_id": project["id"],
                "key": "wrapped-events",
                "name": "包装消息通道",
                "protocol": "ws",
                "request": {"url": "wss://example.test/events"},
                "response_unpack": {"enabled": True, "source": "body.data"},
            },
        )
        assert ws.status_code == 422

        invalid = client.post(
            "/api/v1/apis",
            json={**payload, "key": "invalid-source", "response_unpack": {"enabled": True, "source": "payload.data"}},
        )
        assert invalid.status_code == 422


def test_test_plan_round_trip_and_key_conflict() -> None:
    with TestClient(app) as client:
        project = client.post("/api/v1/projects", json={"name": "test-plan-project"}).json()
        api_response = client.post(
            "/api/v1/apis",
            json={
                "project_id": project["id"],
                "key": "orders.health",
                "name": "订单健康检查",
                "protocol": "http",
                "request": {"url": "https://example.test/health"},
            },
        )
        assert api_response.status_code == 201
        flow_response = client.post(
            "/api/v1/flows",
            json={
                "project_id": project["id"],
                "key": "orders.smoke",
                "name": "订单冒烟流程",
                "steps": [
                    {
                        "id": "health",
                        "name": "订单健康检查",
                        "api_id": api_response.json()["id"],
                    }
                ],
            },
        )
        assert flow_response.status_code == 201

        plan_payload = {
            "project_id": project["id"],
            "key": "release.orders.v1",
            "version": "v1.0.0",
            "name": "订单服务发布回归",
            "description": "覆盖订单服务核心影响范围",
            "items": [
                {
                    "id": "orders-api",
                    "type": "api",
                    "target_id": api_response.json()["id"],
                },
                {
                    "id": "orders-flow",
                    "type": "flow",
                    "target_id": flow_response.json()["id"],
                },
            ],
        }
        response = client.post("/api/v1/test-plans", json=plan_payload)
        assert response.status_code == 201
        plan = response.json()
        assert plan["key"] == "release.orders.v1"
        assert len(plan["items"]) == 2

        duplicate = client.post(
            "/api/v1/test-plans", json={**plan_payload, "name": "订单服务发布回归 2"}
        )
        assert duplicate.status_code == 409

        empty_plan = client.post(
            "/api/v1/test-plans",
            json={
                "project_id": project["id"],
                "key": "release.orders.empty",
                "version": "v1.0.0",
                "name": "空计划",
            },
        )
        assert empty_plan.status_code == 201
        empty_run = client.post(f"/api/v1/test-plans/{empty_plan.json()['id']}/runs", json={})
        assert empty_run.status_code == 422
