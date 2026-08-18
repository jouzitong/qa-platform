"""Stable OpenAPI 3 and Swagger 2 conversion checks."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCAN = SKILL_ROOT / "scripts" / "scan_project.py"
VALIDATE = SKILL_ROOT / "scripts" / "validate-import.py"


class OpenApiConversionTests(unittest.TestCase):
    def test_explicit_runtime_springdoc_url_is_scanned(self) -> None:
        document = json.dumps(
            {
                "openapi": "3.0.3",
                "paths": {
                    "/runtime/health": {
                        "get": {
                            "summary": "运行时健康检查",
                            "description": "来自运行中的 springdoc 文档。",
                            "responses": {
                                "200": {
                                    "description": "ok",
                                    "content": {
                                        "application/json": {
                                            "schema": {
                                                "type": "object",
                                                "properties": {
                                                    "status": {
                                                        "type": "string",
                                                        "description": "服务状态。",
                                                    }
                                                },
                                            }
                                        }
                                    },
                                }
                            },
                        }
                    }
                },
            },
            ensure_ascii=False,
        ).encode()

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(document)

            def log_message(self, _format: str, *args: object) -> None:
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                port = server.server_address[1]
                (root / ".qa-platform.json").write_text(
                    json.dumps(
                        {
                            "variables": {"base_url": f"127.0.0.1:{port}"},
                            "openapi": {
                                "urls": [
                                    {
                                        "url": f"http://127.0.0.1:{port}/v3/api-docs",
                                        "required": True,
                                    }
                                ]
                            },
                        }
                    ),
                    encoding="utf-8",
                )
                output = root / "runtime.json"
                subprocess.run(
                    [
                        sys.executable,
                        str(SCAN),
                        str(root),
                        "--language",
                        "zh-CN",
                        "--output",
                        str(output),
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                manifest = json.loads(output.read_text(encoding="utf-8"))
                api = manifest["interfaces"]["http"][0]
                self.assertEqual(api["key"], "http:GET:/runtime/health")
                self.assertEqual(api["name"], "运行时健康检查")
                self.assertEqual(
                    manifest["source"]["api_documents"][0]["kind"], "url"
                )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_openapi_and_swagger_preserve_descriptions_examples_and_schemas(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".qa-platform.json").write_text(
                json.dumps(
                    {
                        "variables": {"base_url": "127.0.0.1:9764"},
                        "openapi": {
                            "documents": [
                                "contracts/openapi.json",
                                "contracts/swagger.json",
                            ]
                        },
                    }
                ),
                encoding="utf-8",
            )
            contracts = root / "contracts"
            contracts.mkdir()
            (contracts / "openapi.json").write_text(
                json.dumps(
                    {
                        "openapi": "3.0.3",
                        "components": {
                            "parameters": {
                                "orderId": {
                                    "name": "orderId",
                                    "in": "path",
                                    "required": True,
                                    "description": "订单唯一标识。",
                                    "schema": {
                                        "type": "integer",
                                        "format": "int64",
                                        "minimum": 1,
                                        "example": 42,
                                    },
                                }
                            },
                            "schemas": {
                                "OrderName": {
                                    "type": "object",
                                    "required": ["name"],
                                    "properties": {
                                        "name": {
                                            "type": "string",
                                            "description": "订单名称。",
                                            "minLength": 2,
                                        }
                                    },
                                },
                                "CreateOrder": {
                                    "allOf": [
                                        {"$ref": "#/components/schemas/OrderName"},
                                        {
                                            "type": "object",
                                            "properties": {
                                                "quantity": {
                                                    "type": "integer",
                                                    "description": "购买数量。",
                                                    "default": 1,
                                                    "minimum": 1,
                                                },
                                                "metadata": {
                                                    "type": "object",
                                                    "description": "订单元数据。",
                                                    "required": ["source"],
                                                    "properties": {
                                                        "source": {
                                                            "type": "string",
                                                            "description": "元数据来源。",
                                                            "example": "checkout",
                                                        },
                                                        "retry": {
                                                            "type": "object",
                                                            "properties": {
                                                                "count": {
                                                                    "type": "integer",
                                                                    "description": "重试次数。",
                                                                    "default": 2,
                                                                    "example": 2,
                                                                }
                                                            },
                                                        },
                                                    },
                                                }
                                            },
                                        },
                                    ]
                                },
                                "OrderResponse": {
                                    "type": "object",
                                    "required": ["id", "status"],
                                    "properties": {
                                        "id": {
                                            "type": "integer",
                                            "description": "创建后的订单 ID。",
                                        },
                                        "status": {
                                            "type": "string",
                                            "description": "订单当前状态。",
                                            "enum": ["created", "paid"],
                                        },
                                    },
                                },
                            },
                            "requestBodies": {
                                "CreateOrderBody": {
                                    "required": True,
                                    "content": {
                                        "application/json": {
                                            "schema": {
                                                "$ref": "#/components/schemas/CreateOrder"
                                            },
                                            "example": {"name": "Codex Order", "quantity": 2},
                                        }
                                    },
                                }
                            },
                            "responses": {
                                "CreatedOrder": {
                                    "description": "订单创建成功。",
                                    "content": {
                                        "application/vnd.order+json": {
                                            "schema": {
                                                "$ref": "#/components/schemas/OrderResponse"
                                            },
                                            "example": {"id": 1001, "status": "created"},
                                        }
                                    },
                                }
                            },
                        },
                        "paths": {
                            "/orders/{orderId}": {
                                "parameters": [
                                    {"$ref": "#/components/parameters/orderId"}
                                ],
                                "post": {
                                    "operationId": "createOrder",
                                    "summary": "创建订单",
                                    "description": "创建订单并返回完整订单结构。",
                                    "tags": ["orders"],
                                    "security": [],
                                    "parameters": [
                                        {
                                            "name": "dryRun",
                                            "in": "query",
                                            "description": "是否仅校验不落库。",
                                            "schema": {
                                                "type": "boolean",
                                                "default": False,
                                            },
                                        }
                                    ],
                                    "requestBody": {
                                        "$ref": "#/components/requestBodies/CreateOrderBody"
                                    },
                                    "responses": {
                                        "201": {
                                            "$ref": "#/components/responses/CreatedOrder"
                                        }
                                    },
                                },
                            }
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (contracts / "swagger.json").write_text(
                json.dumps(
                    {
                        "swagger": "2.0",
                        "consumes": ["application/json"],
                        "produces": ["application/json"],
                        "definitions": {
                            "LoginRequest": {
                                "type": "object",
                                "required": ["username"],
                                "properties": {
                                    "username": {
                                        "type": "string",
                                        "description": "登录账号。",
                                        "example": "user@example.com",
                                    },
                                    "profile": {
                                        "type": "object",
                                        "required": ["locale"],
                                        "properties": {
                                            "locale": {
                                                "type": "string",
                                                "description": "登录语言。",
                                                "default": "zh-CN",
                                                "example": "zh-CN",
                                            }
                                        },
                                    }
                                },
                            },
                            "LoginResponse": {
                                "type": "object",
                                "required": ["tokenType"],
                                "properties": {
                                    "tokenType": {
                                        "type": "string",
                                        "description": "令牌类型。",
                                    }
                                },
                            },
                        },
                        "paths": {
                            "/legacy/login": {
                                "post": {
                                    "summary": "旧版登录",
                                    "description": "Swagger 2 登录契约。",
                                    "parameters": [
                                        {
                                            "name": "body",
                                            "in": "body",
                                            "required": True,
                                            "schema": {
                                                "$ref": "#/definitions/LoginRequest"
                                            },
                                        }
                                    ],
                                    "responses": {
                                        "200": {
                                            "description": "登录成功。",
                                            "schema": {
                                                "$ref": "#/definitions/LoginResponse"
                                            },
                                            "examples": {
                                                "application/json": {
                                                    "tokenType": "Bearer"
                                                }
                                            },
                                        }
                                    },
                                }
                            }
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            manifest_path = root / "result.json"
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
            subprocess.run(
                [sys.executable, str(VALIDATE), str(manifest_path)],
                check=True,
                capture_output=True,
                text=True,
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            apis = {
                (item["method"], item["path"]): item
                for item in manifest["interfaces"]["http"]
            }

            order = apis[("POST", "/orders/{orderId}")]
            self.assertEqual(order["name"], "创建订单")
            self.assertEqual(order["description"], "创建订单并返回完整订单结构。")
            self.assertEqual(order["discovery_method"], "openapi")
            self.assertEqual(order["auth"], "none")
            self.assertEqual(
                order["request_schema"]["accept"], "application/vnd.order+json"
            )
            self.assertEqual(
                order["request"]["headers"]["Content-Type"], "application/json"
            )
            request_schema = order["request_schema"]["schema"]
            self.assertEqual(
                set(request_schema["properties"]), {"name", "quantity", "metadata"}
            )
            self.assertEqual(request_schema["properties"]["name"]["example"], "Codex Order")
            self.assertEqual(request_schema["properties"]["quantity"]["example"], 2)
            parameters = {(item["in"], item["name"]): item for item in order["parameters"]}
            self.assertEqual(parameters[("path", "orderId")]["description"], "订单唯一标识。")
            self.assertEqual(parameters[("path", "orderId")]["example"], 42)
            self.assertEqual(parameters[("query", "dryRun")]["default"], False)
            self.assertEqual(parameters[("body", "quantity")]["minimum"], 1)
            metadata = parameters[("body", "metadata")]
            self.assertNotIn("in", metadata["children"][0])
            self.assertEqual(
                [(item["name"], item["type"], item["required"]) for item in metadata["children"]],
                [("source", "string", True), ("retry", "object", False)],
            )
            retry = next(item for item in metadata["children"] if item["name"] == "retry")
            self.assertEqual(retry["children"][0]["name"], "count")
            self.assertEqual(retry["children"][0]["default"], 2)
            self.assertEqual(order["response_schema"]["properties"]["id"]["example"], 1001)
            self.assertEqual(
                order["response_schema"]["properties"]["status"]["example"],
                "created",
            )

            legacy = apis[("POST", "/legacy/login")]
            self.assertEqual(legacy["discovery_method"], "swagger")
            self.assertEqual(legacy["request_schema"]["accept"], "application/json")
            self.assertEqual(
                legacy["request"]["headers"]["Content-Type"], "application/json"
            )
            self.assertEqual(
                legacy["request_schema"]["schema"]["properties"]["username"][
                    "description"
                ],
                "登录账号。",
            )
            self.assertEqual(
                legacy["response_schema"]["properties"]["tokenType"]["example"],
                "Bearer",
            )
            legacy_parameters = {
                (item["in"], item["name"]): item for item in legacy["parameters"]
            }
            profile = legacy_parameters[("body", "profile")]
            self.assertEqual(profile["children"][0]["name"], "locale")
            self.assertEqual(profile["children"][0]["default"], "zh-CN")

            broken = json.loads(manifest_path.read_text(encoding="utf-8"))
            broken_order = next(
                item
                for item in broken["interfaces"]["http"]
                if item["path"] == "/orders/{orderId}"
            )
            del broken_order["response_schema"]["properties"]["status"]["description"]
            broken_path = root / "broken-response.json"
            broken_path.write_text(json.dumps(broken), encoding="utf-8")
            validation = subprocess.run(
                [sys.executable, str(VALIDATE), str(broken_path), "--json"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(validation.returncode, 0)
            self.assertIn(
                "response_schema.properties.status.description",
                validation.stdout,
            )

    def test_openapi_response_envelope_is_unpacked_but_plain_response_is_not(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".qa-platform.json").write_text(
                json.dumps({"variables": {"base_url": "127.0.0.1:9764"}}),
                encoding="utf-8",
            )
            (root / "openapi.json").write_text(
                json.dumps(
                    {
                        "openapi": "3.0.3",
                        "paths": {
                            "/wrapped": {
                                "get": {
                                    "summary": "包装响应",
                                    "responses": {
                                        "200": {
                                            "description": "ok",
                                            "content": {
                                                "application/json": {
                                                    "schema": {
                                                        "type": "object",
                                                        "required": ["code", "data"],
                                                        "properties": {
                                                            "code": {
                                                                "type": "integer",
                                                                "const": 0,
                                                                "description": "业务响应码。",
                                                            },
                                                            "data": {
                                                                "type": "object",
                                                                "required": ["id"],
                                                                "properties": {
                                                                    "id": {
                                                                        "type": "string",
                                                                        "description": "资源 ID。",
                                                                        "example": "u001",
                                                                    }
                                                                },
                                                            },
                                                        },
                                                    }
                                                }
                                            },
                                        }
                                    },
                                }
                            },
                            "/plain": {
                                "get": {
                                    "summary": "普通响应",
                                    "responses": {
                                        "200": {
                                            "description": "ok",
                                            "content": {
                                                "application/json": {
                                                    "schema": {
                                                        "type": "object",
                                                        "properties": {
                                                            "status": {
                                                                "type": "string",
                                                                "description": "状态。",
                                                                "example": "ok",
                                                            }
                                                        },
                                                    }
                                                }
                                            },
                                        }
                                    },
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
                [sys.executable, str(SCAN), str(root), "--output", str(output)],
                check=True,
                capture_output=True,
                text=True,
            )
            manifest = json.loads(output.read_text(encoding="utf-8"))

        apis = {item["path"]: item for item in manifest["interfaces"]["http"]}
        wrapped = apis["/wrapped"]
        self.assertEqual(wrapped["response_unpack"]["source"], "body.data")
        self.assertEqual(wrapped["response_schema"]["properties"]["id"]["example"], "u001")
        self.assertEqual(
            wrapped["response_unpack"]["envelope_schema"]["properties"]["code"]["const"],
            0,
        )
        self.assertNotIn("response_unpack", apis["/plain"])


if __name__ == "__main__":
    unittest.main()
