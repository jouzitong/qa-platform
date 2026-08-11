from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app


QA_PLATFORM_ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = QA_PLATFORM_ROOT / "integrations" / "codex" / "qa-platform-skill"
SCAN_PROJECT = SKILL_ROOT / "scripts" / "scan_project.py"
BUILD_ARCHIVE = SKILL_ROOT / "scripts" / "build_import_archive.py"


def test_bundled_skill_archive_can_be_previewed_and_approved() -> None:
    """Keep the scanner's executable ZIP contract compatible with the running platform."""
    project_key = f"skill-contract-{uuid4().hex}"
    with tempfile.TemporaryDirectory() as directory:
        source_root = Path(directory) / "source"
        source_root.mkdir()
        (source_root / ".qa-platform.json").write_text(
            json.dumps({"variables": {"base_url": "127.0.0.1:9764"}}), encoding="utf-8"
        )
        (source_root / "app.py").write_text(
            """
from fastapi import FastAPI

app = FastAPI()

@app.get("/health")
def health():
    return {"status": "ok"}
""".strip(),
            encoding="utf-8",
        )
        manifest = Path(directory) / "qa-platform-import.json"
        archive = Path(directory) / "qa-platform-import.zip"
        subprocess.run(
            [
                sys.executable,
                str(SCAN_PROJECT),
                str(source_root),
                "--project-key",
                project_key,
                "--project-name",
                project_key,
                "--package-version",
                "1.0.0",
                "--output",
                str(manifest),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            [sys.executable, str(BUILD_ARCHIVE), str(manifest), "--output", str(archive)],
            check=True,
            capture_output=True,
            text=True,
        )

        with TestClient(app) as client:
            preview = client.post(
                "/api/v1/imports/preview",
                content=archive.read_bytes(),
                headers={"X-Import-Filename": archive.name},
            )
            assert preview.status_code == 201, preview.text
            preview_body = preview.json()
            assert preview_body["status"] == "pending"
            assert preview_body["errors"] == []

            approved = client.post(f"/api/v1/imports/{preview_body['id']}/approve")
            assert approved.status_code == 200, approved.text
            assert approved.json()["status"] == "applied"

            project = next(
                item
                for item in client.get("/api/v1/projects").json()
                if item["name"] == project_key
            )
            apis = client.get(f"/api/v1/apis?project_id={project['id']}").json()
            assert [(item["protocol"], item["request"].get("path")) for item in apis] == [
                ("http", "/health")
            ]
