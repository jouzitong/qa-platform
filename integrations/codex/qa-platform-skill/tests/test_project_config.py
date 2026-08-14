"""Regression checks for required target project variables."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
INIT_CONFIG = SKILL_ROOT / "scripts" / "init_project_config.py"
SCAN = SKILL_ROOT / "scripts" / "scan_project.py"


class ProjectConfigTests(unittest.TestCase):
    def test_init_requires_scheme_less_project_base_url(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            missing = subprocess.run(
                [sys.executable, str(INIT_CONFIG), str(root)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(missing.returncode, 0)
            self.assertIn("--project-base-url", missing.stderr)

            invalid = subprocess.run(
                [
                    sys.executable,
                    str(INIT_CONFIG),
                    str(root),
                    "--project-base-url",
                    "http://127.0.0.1:9764",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(invalid.returncode, 0)
            self.assertIn("without http://", invalid.stderr)

    def test_init_writes_project_variable_and_scanner_preserves_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(
                [
                    sys.executable,
                    str(INIT_CONFIG),
                    str(root),
                    "--base-url",
                    "http://localhost:8000",
                    "--project-base-url",
                    "127.0.0.1:9764",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            config = json.loads((root / ".qa-platform.json").read_text(encoding="utf-8"))
            self.assertEqual(config["base_url"], "http://localhost:8000")
            self.assertEqual(config["project"]["name"], root.name)
            self.assertEqual(config["variables"], {"base_url": "127.0.0.1:9764"})
            self.assertEqual(config["api_templates"], [])
            self.assertEqual(config["flow_documents"], [])
            self.assertTrue(config["openapi"]["auto_discover"])
            self.assertFalse(config["openapi"]["runtime_discovery"]["enabled"])
            self.assertEqual(
                config["success_assertions"]["default_assertion"]["http"],
                "config:http-success-status",
            )
            self.assertEqual(
                config["success_assertions"]["default_assertion"]["ws"],
                "config:ws-success-messages",
            )

            (root / "app.py").write_text(
                "from fastapi import FastAPI\napp = FastAPI()\n@app.get('/health')\ndef health(): return {'ok': True}\n",
                encoding="utf-8",
            )
            manifest = root / "manifest.json"
            subprocess.run(
                [sys.executable, str(SCAN), str(root), "--output", str(manifest)],
                check=True,
                capture_output=True,
                text=True,
            )
            result = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(result["project"]["variables"], {"base_url": "127.0.0.1:9764"})
            self.assertEqual(result["success_assertions"]["source"], "project_config")
            self.assertEqual(
                result["interfaces"]["http"][0]["success_assertion_key"],
                "config:http-success-status",
            )


if __name__ == "__main__":
    unittest.main()
