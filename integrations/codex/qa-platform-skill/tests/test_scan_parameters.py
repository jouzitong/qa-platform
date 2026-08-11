"""Regression checks for executable API parameter construction."""

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

from scan_project import detect_architecture, discover_files


class ScanParameterTests(unittest.TestCase):
    def test_spring_websocket_configurer_handlers_are_discovered_with_context_path(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".qa-platform.json").write_text(
                json.dumps({"variables": {"base_url": "127.0.0.1:9764"}}),
                encoding="utf-8",
            )
            config = (
                root / "service" / "src" / "main" / "resources" / "application.properties"
            )
            config.parent.mkdir(parents=True)
            config.write_text("server.servlet.context-path=/chat\n", encoding="utf-8")
            configuration = (
                root
                / "service"
                / "src"
                / "main"
                / "java"
                / "ChatWebSocketConfiguration.java"
            )
            configuration.parent.mkdir(parents=True)
            configuration.write_text(
                """
                import org.springframework.context.annotation.Configuration;
                import org.springframework.web.socket.config.annotation.*;

                @Configuration
                @EnableWebSocket
                public class ChatWebSocketConfiguration implements WebSocketConfigurer {
                    @Override
                    public void registerWebSocketHandlers(
                            WebSocketHandlerRegistry registry) {
                        registry.addHandler(handler, "/ws/chat", "/ws/legacy");
                    }
                }
                """,
                encoding="utf-8",
            )
            manifest_path = root / "manifest.json"
            subprocess.run(
                [
                    sys.executable,
                    str(SCAN),
                    str(root),
                    "--language",
                    "zh-CN",
                    "--output",
                    str(manifest_path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        websocket_routes = {item["url"]: item for item in manifest["interfaces"]["ws"]}
        self.assertEqual(set(websocket_routes), {"/chat/ws/chat", "/chat/ws/legacy"})
        self.assertEqual(
            {item["name"] for item in websocket_routes.values()},
            {
                "聊天 WebSocket接口（WS /chat/ws/chat）",
                "聊天 WebSocket接口（WS /chat/ws/legacy）",
            },
        )
        for item in websocket_routes.values():
            source_files = {ref["file"] for ref in item["source_refs"]}
            self.assertIn(
                "service/src/main/java/ChatWebSocketConfiguration.java",
                source_files,
            )
            self.assertIn(
                "service/src/main/resources/application.properties",
                source_files,
            )
            self.assertEqual(item["confidence"], 0.95)
            self.assertIn(
                "WebSocket message contract is not statically discovered",
                item["warnings"],
            )

    def test_spring_websocket_configurer_name_combines_class_and_method_docs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".qa-platform.json").write_text(
                json.dumps({"variables": {"base_url": "127.0.0.1:9764"}}),
                encoding="utf-8",
            )
            configuration = root / "ChatWebSocketConfiguration.java"
            configuration.write_text(
                """
                import org.springframework.context.annotation.Configuration;
                import org.springframework.web.socket.config.annotation.*;

                /** 聊天会话推送通道。 */
                @Configuration
                @EnableWebSocket
                public class ChatWebSocketConfiguration implements WebSocketConfigurer {
                    /** 注册会话推送连接。 */
                    @Override
                    public void registerWebSocketHandlers(WebSocketHandlerRegistry registry) {
                        registry.addHandler(handler, "/ws/chat");
                    }
                }
                """,
                encoding="utf-8",
            )
            manifest_path = root / "manifest.json"
            subprocess.run(
                [
                    sys.executable,
                    str(SCAN),
                    str(root),
                    "--language",
                    "zh-CN",
                    "--output",
                    str(manifest_path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        websocket = manifest["interfaces"]["ws"][0]
        self.assertEqual(
            websocket["name"],
            "聊天会话推送通道 - 注册会话推送连接",
        )

    def test_spring_application_prefix_is_added_to_http_and_websocket_routes(self) -> None:
        variants = (
            ("application.properties", "server.servlet.context-path=/chat\n", "/chat"),
            (
                "application.yaml",
                "server:\n  servlet:\n    context-path: /chat\n",
                "/chat",
            ),
            ("application.yml", "server.servlet.context-path: /chat\n", "/chat"),
            ("application.yaml", "spring:\n  mvc:\n    servlet:\n      path: /api\n", "/api"),
        )

        for filename, config_text, expected_prefix in variants:
            with self.subTest(filename=filename, config=config_text):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    module = root / "service"
                    config = module / "src" / "main" / "resources" / filename
                    config.parent.mkdir(parents=True)
                    config.write_text(config_text, encoding="utf-8")
                    controller = module / "src" / "main" / "java" / "DemoController.java"
                    controller.parent.mkdir(parents=True)
                    controller.write_text(
                        """
                        import org.springframework.web.bind.annotation.GetMapping;
                        import org.springframework.web.bind.annotation.MessageMapping;
                        import org.springframework.web.bind.annotation.RestController;

                        @RestController
                        public class DemoController {
                            @GetMapping("/users")
                            public String users() { return "ok"; }

                            @MessageMapping("/events")
                            public void events() { }
                        }
                        """,
                        encoding="utf-8",
                    )
                    manifest_path = root / "manifest.json"
                    subprocess.run(
                        [
                            sys.executable,
                            str(SCAN),
                            str(root),
                            "--language",
                            "en",
                            "--output",
                            str(manifest_path),
                        ],
                        check=True,
                        capture_output=True,
                        text=True,
                    )
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

                http = {(item["method"], item["path"]): item for item in manifest["interfaces"]["http"]}
                self.assertIn(("GET", f"{expected_prefix}/users"), http)
                self.assertIn(
                    f"service/src/main/resources/{filename}",
                    {ref["file"] for ref in http[("GET", f"{expected_prefix}/users")]["source_refs"]},
                )
                self.assertIn(
                    f"{expected_prefix}/events",
                    {item["url"] for item in manifest["interfaces"]["ws"]},
                )

    def test_system_success_assertion_profile_is_referenced_by_generated_api(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".qa-platform.json").write_text(
                json.dumps({"variables": {"base_url": "127.0.0.1:9764"}}),
                encoding="utf-8",
            )
            (root / "ResultCodes.java").write_text(
                "public final class ResultCodes { public static final int SUCCESS_CODE = 1; }",
                encoding="utf-8",
            )
            (root / "DemoController.java").write_text(
                """
                import org.springframework.web.bind.annotation.GetMapping;
                import org.springframework.web.bind.annotation.RestController;

                @RestController
                public class DemoController {
                    @GetMapping("/health")
                    public String health() { return "ok"; }
                }
                """,
                encoding="utf-8",
            )
            manifest_path = root / "manifest.json"
            subprocess.run(
                [
                    sys.executable,
                    str(SCAN),
                    str(root),
                    "--language",
                    "en",
                    "--output",
                    str(manifest_path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

            api = next(item for item in manifest["interfaces"]["http"] if item["path"] == "/health")
            profile_key = api["assertion_profile_key"]
            profile = next(item for item in manifest["assertion_profiles"] if item["name"] == profile_key)
            definitions = {item["key"]: item for item in manifest["assertion_definitions"]}
            binding_keys = {item["assertion_id"] for item in profile["bindings"]}

            self.assertIn("system:success-status", binding_keys)
            body_key = next(
                key
                for key in binding_keys
                if key == "system:success-body-schema" or key.startswith("system:success-body-schema:")
            )
            self.assertEqual(definitions[body_key]["config"]["schema"]["properties"]["code"], {"const": 1})
            self.assertEqual(manifest["success_assertions"]["detected_success_codes"][0]["value"], 1)

            archive_path = root / "qa-platform-import.zip"
            subprocess.run(
                [sys.executable, str(BUILD_ARCHIVE), str(manifest_path), "--output", str(archive_path)],
                check=True,
                capture_output=True,
                text=True,
            )
            with zipfile.ZipFile(archive_path) as archive:
                self.assertIn("assertion_definitions.json", archive.namelist())
                self.assertIn("assertion_profiles.json", archive.namelist())
                project = json.loads(archive.read("project.json"))
                self.assertEqual(project["variables"]["base_url"], "127.0.0.1:9764")
                imported_api = json.loads(archive.read("v1.0.0/api.json"))[0]
                self.assertEqual(imported_api["assertion_profile_key"], profile_key)

    def test_gateway_module_config_infers_local_gateway_address(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "app" / "app-gateway" / "boot" / "src" / "main" / "resources" / "application.yaml"
            config.parent.mkdir(parents=True)
            config.write_text(
                """server:
  port: 9764
spring:
  cloud:
    gateway:
      mvc:
        routes: []
""",
                encoding="utf-8",
            )
            for path in (
                root / "app" / "app-gateway" / "pom.xml",
                root / "app" / "app-gateway" / "boot" / "pom.xml",
                root / "app" / "app-platform-user" / "boot" / "pom.xml",
            ):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("<project/>", encoding="utf-8")

            architecture = detect_architecture(root, discover_files(root))

        gateway = architecture["gateway"]
        self.assertTrue(gateway["detected"])
        self.assertEqual(gateway["address"]["value"], "http://localhost:9764")
        self.assertEqual(gateway["address"]["kind"], "inferred")
        self.assertIn("网关地址由 server.port 推断，导入前请人工确认 host 和协议", gateway["warnings"])
        self.assertIn(
            "gateway-module-config",
            [item["marker"] for item in architecture["evidence"]["gateway_markers"]],
        )
        self.assertEqual(
            {item["root"] for item in architecture["services"]},
            {"app/app-gateway", "app/app-platform-user"},
        )

    def test_validator_rejects_invalid_parameter_identities(self) -> None:
        manifest = {
            "format": "qa-platform-import",
            "version": "1.0",
            "package_version": "v1.0.0",
            "project": {"key": "demo", "name": "Demo"},
            "interfaces": {
                "http": [
                    {
                        "key": "items.get",
                        "method": "GET",
                        "path": "/items/{id}",
                        "parameters": [
                            {"name": "id", "in": "path", "type": "string", "required": False},
                            {"name": "X-Trace", "in": "header", "type": "string", "required": False},
                            {"name": "x-trace", "in": "header", "type": "string", "required": False},
                        ],
                        "source_refs": [],
                    }
                ],
                "ws": [],
            },
            "features": [],
            "test_cases": [],
            "flows": [],
            "test_plans": [],
        }
        with tempfile.TemporaryDirectory() as directory:
            manifest_path = Path(directory) / "invalid.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(VALIDATE), str(manifest_path), "--json"],
                check=False,
                capture_output=True,
                text=True,
            )
        report = json.loads(result.stdout)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("path parameters must be required", "\n".join(report["errors"]))
        self.assertIn("duplicate parameter identity: header:x-trace", report["errors"])

    def test_validator_enforces_one_plan_for_each_package_version(self) -> None:
        manifest = {
            "format": "qa-platform-import",
            "version": "1.0",
            "package_version": "0.1.2",
            "project": {"key": "demo", "name": "Demo"},
            "interfaces": {"http": [], "ws": []},
            "features": [],
            "test_cases": [],
            "flows": [],
            "test_plans": [
                {
                    "key": "plan:demo:0-1-2:smoke",
                    "version": "0.1.2",
                    "items": [],
                    "source_refs": [],
                },
                {
                    "key": "plan:demo:0-1-2:secondary",
                    "version": "0.1.3",
                    "items": [],
                    "source_refs": [],
                },
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            manifest_path = Path(directory) / "invalid-plans.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(VALIDATE), str(manifest_path), "--json"],
                check=False,
                capture_output=True,
                text=True,
            )
        report = json.loads(result.stdout)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("test_plans must contain at most one plan for package_version", report["errors"])
        self.assertIn("test_plans[1].version must equal package_version", report["errors"])

    def test_spring_and_openapi_parameters_are_executable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".qa-platform.json").write_text(
                json.dumps({"variables": {"base_url": "127.0.0.1:9764"}}),
                encoding="utf-8",
            )
            (root / "DemoController.java").write_text(
                """
                import jakarta.validation.constraints.NotBlank;
                import jakarta.validation.constraints.Min;
                import org.springframework.web.bind.annotation.*;

                @RestController
                @RequestMapping("/users")
                public class DemoController {
                    @GetMapping("/{id}")
                    public String get(
                            @PathVariable Long id,
                            @RequestParam(value = "page", defaultValue = "1") Integer page,
                            @RequestHeader(value = "X-Locale", required = false) String locale) {
                        return "ok";
                    }

                    @PostMapping
                    public void create(@RequestBody DemoRequest request) { }

                    public static class DemoRequest {
                        @NotBlank
                        private String name;
                        @Min(1)
                        private Long quantity;
                        private Boolean enabled;
                    }
                }
                """,
                encoding="utf-8",
            )
            (root / "openapi.json").write_text(
                json.dumps(
                    {
                        "openapi": "3.0.3",
                        "components": {
                            "parameters": {
                                "orderId": {
                                    "name": "orderId",
                                    "in": "path",
                                    "required": True,
                                    "schema": {"type": "integer"},
                                }
                            },
                            "schemas": {
                                "CreateOrder": {
                                    "type": "object",
                                    "required": ["name"],
                                    "properties": {
                                        "name": {"type": "string", "example": "sample"},
                                        "quantity": {"type": "integer", "minimum": 1},
                                        "metadata": {"type": "object"},
                                    },
                                }
                            },
                        },
                        "paths": {
                            "/orders/{orderId}": {
                                "parameters": [{"$ref": "#/components/parameters/orderId"}],
                                "get": {
                                    "operationId": "getOrder",
                                    "parameters": [
                                        {
                                            "name": "page",
                                            "in": "query",
                                            "schema": {"type": "integer", "default": 1},
                                        },
                                        {
                                            "name": "X-Trace",
                                            "in": "header",
                                            "schema": {"type": "string"},
                                        },
                                    ],
                                    "responses": {"200": {"description": "ok"}},
                                },
                                "post": {
                                    "operationId": "createOrder",
                                    "requestBody": {
                                        "required": True,
                                        "content": {
                                            "application/json": {
                                                "schema": {"$ref": "#/components/schemas/CreateOrder"}
                                            }
                                        },
                                    },
                                    "responses": {"201": {"description": "created"}},
                                },
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            manifest_path = root / "manifest.json"
            subprocess.run(
                [
                    sys.executable,
                    str(SCAN),
                    str(root),
                    "--plan-version",
                    "v1.2.3",
                    "--language",
                    "en-US",
                    "--output",
                    str(manifest_path),
                    "--openapi",
                    "openapi.json",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                [sys.executable, str(VALIDATE), str(manifest_path)],
                check=True,
                capture_output=True,
                text=True,
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            interfaces = {
                (item["method"], item["path"]): item
                for item in manifest["interfaces"]["http"]
            }

            spring_get = interfaces[("GET", "/users/{id}")]
            self.assertEqual(
                [(item["in"], item["name"], item["type"], item["required"])
                for item in spring_get["parameters"]],
                [
                    ("path", "id", "integer", True),
                    ("query", "page", "integer", False),
                    ("header", "X-Locale", "string", False),
                ],
            )
            self.assertEqual(
                next(item for item in spring_get["parameters"] if item["name"] == "page")["default"],
                1,
            )
            spring_post = interfaces[("POST", "/users/")]
            self.assertEqual(
                {(item["in"], item["name"], item["type"], item["required"])
                for item in spring_post["parameters"]},
                {
                    ("body", "name", "string", True),
                    ("body", "quantity", "integer", False),
                    ("body", "enabled", "boolean", False),
                },
            )

            order_get = interfaces[("GET", "/orders/{orderId}")]
            self.assertEqual(
                {(item["in"], item["name"], item["type"]) for item in order_get["parameters"]},
                {
                    ("path", "orderId", "integer"),
                    ("query", "page", "integer"),
                    ("header", "X-Trace", "string"),
                },
            )
            order_post = interfaces[("POST", "/orders/{orderId}")]
            self.assertEqual(
                {(item["in"], item["name"], item["type"], item["required"])
                for item in order_post["parameters"]},
                {
                    ("path", "orderId", "integer", True),
                    ("body", "name", "string", True),
                    ("body", "quantity", "integer", False),
                    ("body", "metadata", "object", False),
                },
            )
            for interface in manifest["interfaces"]["http"] + manifest["interfaces"]["ws"]:
                for parameter in interface["parameters"]:
                    self.assertIsInstance(parameter["description"], str)
                    self.assertTrue(parameter["description"].strip())
                    self.assertIn("example", parameter)
                    self.assertIsNotNone(parameter["example"])
                    if isinstance(parameter["example"], str):
                        self.assertTrue(parameter["example"].strip())
            order_name = next(item for item in order_post["parameters"] if item["name"] == "name")
            self.assertEqual(order_name["example"], "sample")

            archive_path = root / "qa-platform-import.zip"
            subprocess.run(
                [sys.executable, str(BUILD_ARCHIVE), str(manifest_path), "--output", str(archive_path)],
                check=True,
                capture_output=True,
                text=True,
            )
            with zipfile.ZipFile(archive_path) as archive:
                assets = json.loads(archive.read("v1.2.3/api.json"))
            imported_order = next(item for item in assets if item["key"] == order_post["key"])
            self.assertEqual(imported_order["parameters"], order_post["parameters"])

    def test_configured_success_assertions_are_exported_and_used_by_all_apis(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = {
                "variables": {"base_url": "127.0.0.1:9764"},
                "success_assertions": {
                    "default_profile": {
                        "http": "review:http-success",
                        "ws": "review:ws-success",
                    },
                    "definitions": [
                        {
                            "key": "review:http-status",
                            "name": "HTTP 状态成功",
                            "engine": "expression",
                            "description": "状态码为 2xx。",
                            "config": {"expression": "response.status_code >= 200"},
                            "default_params": {},
                            "severity": "success",
                            "message": "HTTP 请求失败",
                        },
                        {
                            "key": "review:ws-message",
                            "name": "WS 消息成功",
                            "engine": "expression",
                            "description": "至少收到一条消息。",
                            "config": {"expression": "len(response.messages) >= 1"},
                            "default_params": {},
                            "severity": "success",
                            "message": "未收到消息",
                        },
                    ],
                    "profiles": [
                        {
                            "name": "review:http-success",
                            "protocol": "http",
                            "description": "审核中的 HTTP 默认成功集合。",
                            "is_default": False,
                            "bindings": [{"assertion_id": "review:http-status", "enabled": True}],
                        },
                        {
                            "name": "review:ws-success",
                            "protocol": "ws",
                            "description": "审核中的 WS 默认成功集合。",
                            "is_default": False,
                            "bindings": [{"assertion_id": "review:ws-message", "enabled": True}],
                        },
                    ],
                },
            }
            (root / ".qa-platform.json").write_text(
                json.dumps(config, ensure_ascii=False), encoding="utf-8"
            )
            (root / "app.py").write_text(
                """
                from fastapi import FastAPI
                app = FastAPI()
                @app.get('/health')
                def health(): return {'ok': True}
                @app.websocket('/events')
                async def events(ws): pass
                """,
                encoding="utf-8",
            )
            manifest_path = root / "manifest.json"
            subprocess.run(
                [sys.executable, str(SCAN), str(root), "--language", "en", "--output", str(manifest_path)],
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                [sys.executable, str(VALIDATE), str(manifest_path)],
                check=True,
                capture_output=True,
                text=True,
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["success_assertions"]["source"], "project_config")
            self.assertEqual(
                {item["assertion_profile_key"] for item in manifest["interfaces"]["http"]},
                {"review:http-success"},
            )
            self.assertEqual(
                {item["assertion_profile_key"] for item in manifest["interfaces"]["ws"]},
                {"review:ws-success"},
            )
            self.assertEqual(
                {item["key"] for item in manifest["assertion_definitions"]},
                {"review:http-status", "review:ws-message"},
            )
            self.assertTrue(
                all(item["is_default"] for item in manifest["assertion_profiles"])
            )

            archive_path = root / "qa-platform-import.zip"
            subprocess.run(
                [sys.executable, str(BUILD_ARCHIVE), str(manifest_path), "--output", str(archive_path)],
                check=True,
                capture_output=True,
                text=True,
            )
            with zipfile.ZipFile(archive_path) as archive:
                profiles = json.loads(archive.read("assertion_profiles.json"))
                apis = json.loads(archive.read("v1.0.0/api.json"))
            self.assertEqual({item["name"] for item in profiles}, {"review:http-success", "review:ws-success"})
            self.assertEqual(
                {item["assertion_profile_key"] for item in apis},
                {"review:http-success", "review:ws-success"},
            )

    def test_invalid_configured_success_profile_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".qa-platform.json").write_text(
                json.dumps(
                    {
                        "variables": {"base_url": "127.0.0.1:9764"},
                        "success_assertions": {
                            "default_profile": {"http": "missing:http-success"},
                            "definitions": [],
                            "profiles": [],
                        },
                    }
                ),
                encoding="utf-8",
            )
            (root / "app.py").write_text(
                "from fastapi import FastAPI\napp = FastAPI()\n@app.get('/health')\ndef health(): return {}\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [sys.executable, str(SCAN), str(root), "--output", str(root / "manifest.json")],
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("references unknown profile", result.stderr)

    def test_java_doc_names_combine_controller_and_method_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".qa-platform.json").write_text(
                json.dumps({"variables": {"base_url": "127.0.0.1:9764"}}),
                encoding="utf-8",
            )
            (root / "VirtualCatalogController.java").write_text(
                """
                import org.springframework.web.bind.annotation.*;

                /** 虚拟目录管理接口。 */
                @RestController
                @RequestMapping("/virtual-catalog")
                public class VirtualCatalogController {
                    /** 查询已发布的虚拟目录。 */
                    @GetMapping("/published")
                    public String list() { return "ok"; }

                    /** 删除指定的虚拟目录。 */
                    @DeleteMapping("/{catalogId}")
                    public void delete(@PathVariable Long catalogId) { }
                }
                """,
                encoding="utf-8",
            )
            (root / "SystemSettingInternalApi.java").write_text(
                """
                import org.springframework.web.bind.annotation.*;
                public interface SystemSettingInternalApi {
                    @GetMapping("/value")
                    String queryValueByKey(@RequestParam("key") String key);
                }
                """,
                encoding="utf-8",
            )
            manifest_path = root / "manifest.json"
            subprocess.run(
                [sys.executable, str(SCAN), str(root), "--language", "zh-CN", "--output", str(manifest_path)],
                check=True,
                capture_output=True,
                text=True,
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        names_by_path = {
            item["path"]: item["name"] for item in manifest["interfaces"]["http"]
        }
        self.assertEqual(
            names_by_path["/virtual-catalog/published"],
            "虚拟目录管理接口 - 查询已发布的虚拟目录",
        )
        self.assertEqual(
            names_by_path["/virtual-catalog/{catalogId}"],
            "虚拟目录管理接口 - 删除指定的虚拟目录",
        )
        self.assertEqual(names_by_path["/value"], "系统设置 - 按键查询值")
        self.assertEqual(len(names_by_path), len(set(names_by_path.values())))
        self.assertTrue(
            all("_name_source" not in item for item in manifest["interfaces"]["http"])
        )

    def test_validator_rejects_missing_parameter_description_and_example(self) -> None:
        manifest = {
            "format": "qa-platform-import",
            "version": "1.0",
            "package_version": "v1.0.0",
            "project": {
                "key": "demo",
                "name": "Demo",
                "variables": {"base_url": "127.0.0.1:9764"},
            },
            "assertion_definitions": [{"key": "success", "name": "success"}],
            "assertion_profiles": [
                {
                    "name": "default:http",
                    "protocol": "http",
                    "bindings": [{"assertion_id": "success", "enabled": True}],
                }
            ],
            "interfaces": {
                "http": [
                    {
                        "key": "demo.get",
                        "method": "GET",
                        "path": "/demo/{id}",
                        "assertion_profile_key": "default:http",
                        "parameters": [
                            {"name": "id", "in": "path", "type": "string", "required": True, "description": "", "example": "id-1"},
                            {"name": "page", "in": "query", "type": "integer", "required": False, "description": "页码", "example": ""},
                        ],
                        "source_refs": [],
                    }
                ],
                "ws": [],
            },
            "features": [],
            "test_cases": [],
            "flows": [],
            "test_plans": [],
        }
        with tempfile.TemporaryDirectory() as directory:
            manifest_path = Path(directory) / "invalid-parameters.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(VALIDATE), str(manifest_path), "--json"],
                check=False,
                capture_output=True,
                text=True,
            )
        report = json.loads(result.stdout)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "interfaces.http[0].parameters[0].description must be a non-empty string",
            report["errors"],
        )
        self.assertIn(
            "interfaces.http[0].parameters[1].example must be populated",
            report["errors"],
        )


if __name__ == "__main__":
    unittest.main()
