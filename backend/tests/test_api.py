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
                "name": "health",
                "protocol": "http",
                "request": {"method": "GET", "path": "/health"},
            },
        )
        assert response.status_code == 201
        api_id = response.json()["id"]

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
