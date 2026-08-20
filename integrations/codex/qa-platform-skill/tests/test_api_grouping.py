"""Regression checks for API directory assignment and import validation."""

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
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from api_grouping import group_path_error, normalize_group_path


class ApiGroupingTests(unittest.TestCase):
    def test_group_paths_are_canonical_and_reject_traversal(self) -> None:
        self.assertEqual(normalize_group_path(r"\\用户服务\\用户管理//"), "/用户服务/用户管理")
        self.assertIsNone(group_path_error("/用户服务/用户管理"))
        self.assertIn("empty path segments", group_path_error("/用户//管理") or "")
        self.assertIn("'..'", group_path_error("/用户/../管理") or "")

    def test_project_rules_win_over_openapi_extensions_and_tags_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            contracts = root / "contracts"
            contracts.mkdir()
            (root / ".qa-platform.json").write_text(
                json.dumps(
                    {
                        "variables": {"base_url": "127.0.0.1:9764"},
                        "api_grouping": {
                            "rules": [
                                {
                                    "group_path": "/用户服务/用户管理",
                                    "match": {"tags": ["users"]},
                                },
                                {
                                    "group_path": "/系统",
                                    "match": {"path": "/health"},
                                },
                            ]
                        },
                        "openapi": {"documents": ["contracts/openapi.json"]},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (contracts / "openapi.json").write_text(
                json.dumps(
                    {
                        "openapi": "3.0.3",
                        "tags": [{"name": "orders"}],
                        "paths": {
                            "/users": {
                                "get": {
                                    "tags": ["users"],
                                    "summary": "用户列表",
                                    "responses": {"200": {"description": "ok"}},
                                }
                            },
                            "/health": {
                                "get": {
                                    "summary": "健康检查",
                                    "responses": {"200": {"description": "ok"}},
                                }
                            },
                            "/orders": {
                                "get": {
                                    "tags": ["orders"],
                                    "x-qa-platform-group-path": "/交易/订单",
                                    "summary": "订单列表",
                                    "responses": {"200": {"description": "ok"}},
                                }
                            },
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            output = root / "manifest.json"
            subprocess.run(
                [sys.executable, str(SCAN), str(root), "--language", "zh-CN", "--output", str(output)],
                check=True,
                capture_output=True,
                text=True,
            )
            manifest = json.loads(output.read_text(encoding="utf-8"))
            by_path = {item["path"]: item for item in manifest["interfaces"]["http"]}

            self.assertEqual(by_path["/users"]["group_path"], "/用户服务/用户管理")
            self.assertEqual(by_path["/health"]["group_path"], "/系统")
            self.assertEqual(by_path["/orders"]["group_path"], "/交易/订单")
            self.assertEqual(manifest["api_grouping"]["rules"][0]["group_path"], "/用户服务/用户管理")

    def test_generated_group_path_survives_module_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".qa-platform.json").write_text(
                json.dumps({"variables": {"base_url": "127.0.0.1:9764"}}),
                encoding="utf-8",
            )
            (root / "app.py").write_text(
                "from fastapi import FastAPI\napp = FastAPI()\n@app.get('/users')\ndef users(): return {'ok': True}\n",
                encoding="utf-8",
            )
            output = root / "manifest.json"
            subprocess.run(
                [sys.executable, str(SCAN), str(root), "--output", str(output)],
                check=True,
                capture_output=True,
                text=True,
            )
            bundle = root / "manifest.modules"
            api_path = bundle / "api.json"
            api_records = json.loads(api_path.read_text(encoding="utf-8"))
            self.assertEqual(api_records[0]["group_path"], "/users")

            subprocess.run(
                [sys.executable, str(BUILD_ARCHIVE), str(bundle)],
                check=True,
                capture_output=True,
                text=True,
            )
            with zipfile.ZipFile(bundle / "qa-platform-import.zip") as archive:
                packaged = json.loads(archive.read("v1.0.0/api.json"))
            self.assertEqual(packaged[0]["group_path"], "/users")

            api_records[0]["group_path"] = "/users//invalid"
            api_path.write_text(json.dumps(api_records, ensure_ascii=False), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(VALIDATE), str(bundle)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("empty path segments", result.stdout)

    def test_service_topology_adds_external_prefix_and_service_business_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service_root = root / "app" / "app-platform-user"
            controller = service_root / "api" / "src" / "UserManageController.java"
            controller.parent.mkdir(parents=True)
            controller.write_text(
                """
                import org.springframework.web.bind.annotation.*;

                /** 用户管理。 */
                @RestController
                @RequestMapping("/api/v1/users")
                public class UserManageController {
                    /**
                     * 查询工具归属用户。
                     * @param toolCode 工具业务编码
                     */
                    @GetMapping("/{toolCode}")
                    public String detail(@PathVariable String toolCode) { return "ok"; }
                }
                """,
                encoding="utf-8",
            )
            sibling_config = service_root / "boot" / "src" / "main" / "resources" / "application.yml"
            sibling_config.parent.mkdir(parents=True)
            sibling_config.write_text(
                "server:\n  servlet:\n    context-path: /user\n",
                encoding="utf-8",
            )
            topology = {
                "gateway": {},
                "services": [
                    {
                        "key": "app-platform-user",
                        "name": "用户服务",
                        "source_roots": ["app/app-platform-user"],
                        "route_prefix": "/user",
                        "group_path": "/用户服务",
                        "server": {"context_path": "/user", "port": 13105},
                        "gateway": {"service_id": "user", "path_prefix": "/user"},
                    }
                ],
            }
            (root / ".qa-platform.json").write_text(
                json.dumps(
                    {
                        "variables": {"base_url": "127.0.0.1:9764"},
                        "service_topology": topology,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            output = root / "manifest.json"
            subprocess.run(
                [sys.executable, str(SCAN), str(root), "--language", "zh-CN", "--output", str(output)],
                check=True,
                capture_output=True,
                text=True,
            )
            manifest = json.loads(output.read_text(encoding="utf-8"))
            api = next(item for item in manifest["interfaces"]["http"] if item["method"] == "GET")

            self.assertEqual(api["path"], "/user/api/v1/users/{toolCode}")
            self.assertEqual(api["service"], "app-platform-user")
            self.assertEqual(api["group_path"], "/用户服务/UserManage")
            tool_code = next(item for item in api["parameters"] if item["name"] == "toolCode")
            self.assertEqual(tool_code["description"], "工具业务编码")
            self.assertEqual(manifest["service_topology"], topology)

            bundle = root / "manifest.modules"
            index = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(index["service_topology"], topology)
            subprocess.run(
                [sys.executable, str(BUILD_ARCHIVE), str(bundle)],
                check=True,
                capture_output=True,
                text=True,
            )
            with zipfile.ZipFile(bundle / "qa-platform-import.zip") as archive:
                packaged_manifest = json.loads(archive.read("manifest.json"))
                packaged_api = json.loads(archive.read("v1.0.0/api.json"))[0]
            self.assertEqual(packaged_manifest["service_topology"], topology)
            self.assertEqual(packaged_api["group_path"], "/用户服务/UserManage")


if __name__ == "__main__":
    unittest.main()
