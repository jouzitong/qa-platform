"""Regression tests for modular scan output and project flow guidance."""

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
VALIDATE = SKILL_ROOT / "scripts" / "validate-import.py"
BUILD_ARCHIVE = SKILL_ROOT / "scripts" / "build_import_archive.py"


class ModuleBundleAndFlowDocumentTests(unittest.TestCase):
    def test_modules_are_authoritative_and_packaged_as_zip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            docs = root / "docs"
            docs.mkdir()
            (docs / "test-flows.md").write_text(
                """# 登录流程说明

用户提交账号信息后完成登录。

```qa-platform-flow
{
  "key": "flow:user-login",
  "name": "用户登录流程",
  "description": "按产品文档执行登录。",
  "steps": [
    {
      "name": "提交登录请求",
      "interface_key": "http:POST:/auth/login",
      "request": {"body": {"username": "{{ username }}"}}
    }
  ]
}
```
""",
                encoding="utf-8",
            )
            (root / ".qa-platform.json").write_text(
                json.dumps(
                    {
                        "project": {
                            "key": "auth-service",
                            "name": "认证服务",
                            "description": "认证服务接口与流程。",
                        },
                        "variables": {"base_url": "127.0.0.1:9764"},
                        "api_templates": [
                            {
                                "key": "auth-template",
                                "name": "认证请求模板",
                                "protocol": "http",
                                "description": "认证接口公共配置。",
                                "request": {"headers": {"X-Client": "qa"}},
                                "parameters": [],
                                "examples": [],
                                "match": {
                                    "protocol": "http",
                                    "methods": ["POST"],
                                    "path_prefix": "/auth/",
                                },
                            }
                        ],
                        "flow_documents": ["docs/test-flows.md"],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (root / "app.py").write_text(
                """from fastapi import FastAPI
app = FastAPI()
@app.post('/auth/login')
def login(): return {'ok': True}
""",
                encoding="utf-8",
            )

            subprocess.run(
                [sys.executable, str(SCAN), str(root), "--language", "zh-CN"],
                check=True,
                capture_output=True,
                text=True,
            )
            bundle = root / "releases" / "v1.0.0"
            expected_files = {
                "manifest.json",
                "project.json",
                "api_templates.json",
                "assertion_definitions.json",
                "inventory.json",
                "flow_documents.json",
                "api.json",
                "flow.json",
                "plans.json",
                "qa-platform-import.json",
            }
            self.assertTrue(expected_files.issubset({path.name for path in bundle.iterdir()}))

            index = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(index["format"], "qa-platform-scan-bundle")
            self.assertEqual(index["inventory"]["flow_documents"], 1)
            api = json.loads((bundle / "api.json").read_text(encoding="utf-8"))[0]
            self.assertEqual(api["template_key"], "auth-template")
            context = json.loads(
                (bundle / "flow_documents.json").read_text(encoding="utf-8")
            )
            self.assertIn("用户提交账号信息", context["documents"][0]["content"])
            aggregate = json.loads(
                (bundle / "qa-platform-import.json").read_text(encoding="utf-8")
            )
            self.assertNotIn("content", aggregate["flow_documents"]["documents"][0])

            subprocess.run(
                [sys.executable, str(VALIDATE), str(bundle)],
                check=True,
                capture_output=True,
                text=True,
            )

            flows = json.loads((bundle / "flow.json").read_text(encoding="utf-8"))
            self.assertEqual([flow["key"] for flow in flows], ["flow:user-login"])
            flows[0]["name"] = "AI 补全后的用户登录流程"
            (bundle / "flow.json").write_text(
                json.dumps(flows, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            subprocess.run(
                [sys.executable, str(BUILD_ARCHIVE), str(bundle)],
                check=True,
                capture_output=True,
                text=True,
            )
            archive_path = bundle / "qa-platform-import.zip"
            with zipfile.ZipFile(archive_path) as archive:
                names = set(archive.namelist())
                self.assertIn("api_templates.json", names)
                self.assertIn("flow_documents.json", names)
                packaged_flows = json.loads(archive.read("v1.0.0/flow.json"))
                packaged_apis = json.loads(archive.read("v1.0.0/api.json"))
            self.assertEqual(packaged_flows[0]["name"], "AI 补全后的用户登录流程")
            self.assertEqual(packaged_apis[0]["template_key"], "auth-template")


if __name__ == "__main__":
    unittest.main()
