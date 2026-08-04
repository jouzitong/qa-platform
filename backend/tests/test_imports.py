from __future__ import annotations

import io
import json
import zipfile

from fastapi.testclient import TestClient

from app.main import app


def make_archive(*, name: str = "imported-project", api_name: str = "健康检查") -> bytes:
    files = {
        "manifest.json": json.dumps(
            {"package_version": "v1.0.0", "source": {"system": "scanner"}},
            ensure_ascii=False,
        ),
        "project.json": json.dumps(
            {
                "name": name,
                "description": "导入的项目",
                "variables": {"base_url": "https://example.test"},
            },
            ensure_ascii=False,
        ),
        "v1.0.0/api.json": json.dumps(
            [
                {
                    "id": "source-api-1",
                    "key": "health",
                    "name": api_name,
                    "protocol": "http",
                    "request": {"method": "GET", "path": "/health"},
                }
            ],
            ensure_ascii=False,
        ),
        "v1.0.0/assertions.json": json.dumps(
            [
                {
                    "id": "source-assertion-1",
                    "key": "success",
                    "name": "成功响应",
                    "engine": "expression",
                    "config": {"expression": "response.status_code == 200"},
                }
            ],
            ensure_ascii=False,
        ),
        "v1.0.0/profiles.json": json.dumps(
            [
                {
                    "id": "source-profile-1",
                    "name": "默认成功集合",
                    "protocol": "http",
                    "bindings": [{"assertion_id": "source-assertion-1", "enabled": True}],
                }
            ],
            ensure_ascii=False,
        ),
        "v1.0.0/flow.json": json.dumps(
            [
                {
                    "key": "smoke",
                    "name": "冒烟流程",
                    "steps": [{"id": "health-step", "name": "健康检查", "api_key": "health"}],
                }
            ],
            ensure_ascii=False,
        ),
        "v1.0.0/plans.json": json.dumps(
            [
                {
                    "key": "release",
                    "version": "v1.0.0",
                    "name": "发布计划",
                    "items": [{"id": "health-item", "type": "api", "target_key": "health"}],
                }
            ],
            ensure_ascii=False,
        ),
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, content in files.items():
            archive.writestr(path, content)
    return output.getvalue()


def test_import_preview_requires_approval_and_applies_assets_atomically() -> None:
    with TestClient(app) as client:
        archive = make_archive()
        response = client.post(
            "/api/v1/imports/preview",
            content=archive,
            headers={"Content-Type": "application/zip", "X-Import-Filename": "qa.zip"},
        )
        assert response.status_code == 201
        preview = response.json()
        assert preview["status"] == "pending"
        assert preview["package_version"] == "v1.0.0"
        assert preview["preview"]["summary"]["create"] >= 5

        projects = client.get("/api/v1/projects").json()
        assert not any(project["name"] == "imported-project" for project in projects)

        applied = client.post(f"/api/v1/imports/{preview['id']}/approve")
        assert applied.status_code == 200
        assert applied.json()["status"] == "applied"
        project = next(
            project
            for project in client.get("/api/v1/projects").json()
            if project["name"] == "imported-project"
        )
        apis = client.get(f"/api/v1/apis?project_id={project['id']}").json()
        flows = client.get(f"/api/v1/flows?project_id={project['id']}").json()
        plans = client.get(f"/api/v1/test-plans?project_id={project['id']}").json()
        profiles = client.get(f"/api/v1/assertion-profiles?project_id={project['id']}").json()
        assert apis[0]["name"] == "健康检查"
        assert apis[0]["request"]["headers"]["Accept"] == "application/json"
        assert flows[0]["steps"][0]["api_id"] == apis[0]["id"]
        assert plans[0]["items"][0]["target_id"] == apis[0]["id"]
        assertion = client.get(f"/api/v1/assertion-definitions?project_id={project['id']}").json()[
            0
        ]
        assert profiles[0]["bindings"][0]["assertion_id"] == assertion["id"]


def test_import_update_preview_and_reject_do_not_apply() -> None:
    with TestClient(app) as client:
        first = client.post(
            "/api/v1/imports/preview",
            content=make_archive(name="import-update-project"),
            headers={"X-Import-Filename": "qa.zip"},
        ).json()
        assert client.post(f"/api/v1/imports/{first['id']}/approve").status_code == 200
        project = next(
            project
            for project in client.get("/api/v1/projects").json()
            if project["name"] == "import-update-project"
        )
        second = client.post(
            f"/api/v1/imports/preview?project_id={project['id']}",
            content=make_archive(name="import-update-project", api_name="更新后的健康检查"),
            headers={"X-Import-Filename": "qa.zip"},
        ).json()
        assert second["preview"]["summary"]["update"] >= 1
        assert client.post(f"/api/v1/imports/{second['id']}/reject").json()["status"] == "rejected"
        api = client.get(f"/api/v1/apis?project_id={project['id']}").json()[0]
        assert api["name"] == "健康检查"


def test_one_click_is_pending_and_rar_is_explicitly_rejected() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/imports/one-click",
            content=make_archive(name="one-click-project"),
            headers={"X-Import-Filename": "qa.zip", "X-Import-Source": "partner"},
        )
        assert response.status_code == 201
        assert response.json()["status"] == "pending"
        assert response.json()["source"]["channel"] == "partner"

        rar = client.post(
            "/api/v1/imports/preview",
            content=b"not a rar",
            headers={"X-Import-Filename": "qa.rar"},
        )
        assert rar.status_code == 422
        assert "RAR" in rar.json()["detail"]
