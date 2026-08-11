"""Regression checks for cross-ecosystem package-version resolution."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
SCAN = SKILL_ROOT / "scripts" / "scan_project.py"
BUILD_ARCHIVE = SKILL_ROOT / "scripts" / "build_import_archive.py"
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from scan_project import build_assets


def write_fastapi_route(root: Path) -> None:
    (root / "app.py").write_text(
        """
        from fastapi import FastAPI

        app = FastAPI()

        @app.get("/health")
        def health():
            return {"status": "ok"}
        """,
        encoding="utf-8",
    )


def scan(root: Path, *extra_args: str) -> dict[str, object]:
    subprocess.run(
        [sys.executable, str(SCAN), str(root), "--language", "en", *extra_args],
        check=True,
        capture_output=True,
        text=True,
    )
    if "--output" in extra_args:
        output_index = extra_args.index("--output")
        return json.loads(Path(extra_args[output_index + 1]).read_text(encoding="utf-8"))
    manifest_paths = sorted(root.glob("releases/*/qa-platform-import.json"))
    return json.loads(manifest_paths[-1].read_text(encoding="utf-8"))


class VersionResolutionTests(unittest.TestCase):
    def test_maven_revision_drives_manifest_plan_bucket_and_archive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".qa-platform.json").write_text(
                json.dumps({"variables": {"base_url": "127.0.0.1:9764"}}),
                encoding="utf-8",
            )
            (root / "pom.xml").write_text(
                """<project xmlns="http://maven.apache.org/POM/4.0.0">
                  <modelVersion>4.0.0</modelVersion>
                  <groupId>example</groupId>
                  <artifactId>demo</artifactId>
                  <version>${revision}</version>
                  <properties><revision>0.1.2-SNAPSHOT</revision></properties>
                </project>""",
                encoding="utf-8",
            )
            write_fastapi_route(root)

            manifest = scan(root, "--project-key", "demo")
            manifest_path = root / "releases" / "0.1.2" / "qa-platform-import.json"
            archive_path = root / "releases" / "0.1.2" / "qa-platform-import.zip"

            self.assertTrue(manifest_path.is_file())
            self.assertEqual(manifest["package_version"], "0.1.2")
            self.assertEqual(manifest["storage"]["version_directory"], "releases/0.1.2")
            self.assertEqual(
                manifest["source"]["release_version"],
                {
                    "value": "0.1.2",
                    "source": "maven.revision",
                    "raw": "0.1.2-SNAPSHOT",
                    "path": "pom.xml",
                },
            )
            self.assertEqual(len(manifest["test_plans"]), 1)
            self.assertEqual(manifest["test_plans"][0]["version"], "0.1.2")
            self.assertEqual(manifest["test_plans"][0]["key"], "plan:demo:0-1-2:smoke")

            subprocess.run(
                [sys.executable, str(BUILD_ARCHIVE), str(manifest_path)],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertTrue(archive_path.is_file())
            with zipfile.ZipFile(archive_path) as archive:
                self.assertIn("0.1.2/api.json", archive.namelist())
                self.assertIn("0.1.2/flow.json", archive.namelist())
                self.assertIn("0.1.2/plans.json", archive.namelist())
                self.assertEqual(
                    json.loads(archive.read("manifest.json"))["package_version"],
                    "0.1.2",
                )

    def test_python_pyproject_version_is_resolved_without_maven(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "pyproject.toml").write_text(
                """[project]
name = "demo-python"
version = "2.4.0-SNAPSHOT"
""",
                encoding="utf-8",
            )
            write_fastapi_route(root)

            manifest = scan(root)

            self.assertEqual(manifest["package_version"], "2.4.0")
            self.assertEqual(manifest["storage"]["version_directory"], "releases/2.4.0")
            self.assertEqual(manifest["source"]["release_version"]["source"], "python.pyproject.project")
            self.assertEqual(manifest["source"]["release_version"]["path"], "pyproject.toml")

    def test_cli_override_wins_over_config_and_project_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "pyproject.toml").write_text(
                """[project]
name = "demo-python"
version = "1.0.0"
""",
                encoding="utf-8",
            )
            (root / ".qa-platform.json").write_text(
                json.dumps(
                    {
                        "package_version": "2.0.0-SNAPSHOT",
                        "variables": {"base_url": "127.0.0.1:9764"},
                    }
                ),
                encoding="utf-8",
            )
            write_fastapi_route(root)

            config_manifest = scan(root)
            self.assertEqual(config_manifest["package_version"], "2.0.0")
            self.assertEqual(config_manifest["source"]["release_version"]["source"], "config")

            output = root / "cli-override.json"
            cli_manifest = scan(
                root,
                "--plan-version",
                "3.0.0-SNAPSHOT",
                "--output",
                str(output),
            )
            self.assertEqual(cli_manifest["package_version"], "3.0.0")
            self.assertEqual(cli_manifest["source"]["release_version"]["source"], "cli")
            self.assertTrue(output.is_file())

    def test_one_version_plan_aggregates_flows_and_uncovered_apis(self) -> None:
        interfaces = {
            "http": {
                "users.login": {
                    "key": "users.login",
                    "method": "POST",
                    "path": "/users/login",
                    "confidence": 0.9,
                    "source_refs": [{"file": "users.py", "line": 10}],
                },
                "health.check": {
                    "key": "health.check",
                    "method": "GET",
                    "path": "/health",
                    "confidence": 0.9,
                    "source_refs": [{"file": "health.py", "line": 5}],
                },
            },
            "ws": {},
        }
        features = {
            "feature:users": {
                "key": "feature:users",
                "business_key": "users",
                "name": "Users",
                "related_interfaces": ["users.login"],
                "confidence": 0.7,
                "source_refs": [{"file": "users.py", "line": 10}],
            }
        }

        _cases, flows, plans = build_assets(interfaces, features, "0.1.2", "demo-project")

        self.assertEqual([flow["key"] for flow in flows], ["flow:users"])
        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0]["key"], "plan:demo-project:0-1-2:smoke")
        self.assertEqual(
            plans[0]["items"],
            [
                {"id": "flow-item-1", "type": "flow", "target_key": "flow:users", "enabled": False},
                {"id": "api-item-1", "type": "api", "target_key": "health.check", "enabled": False},
            ],
        )


if __name__ == "__main__":
    unittest.main()
