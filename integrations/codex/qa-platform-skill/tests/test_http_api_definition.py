"""Contract tests for the canonical http-api/v1 definition shape."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from build_import_archive import convert_interface


class HttpApiDefinitionTests(unittest.TestCase):
    def test_template_request_is_materialized_with_accept_and_references(self) -> None:
        template_path = SKILL_ROOT / "assets" / "http_api.json"
        definition = json.loads(template_path.read_text(encoding="utf-8"))

        converted = convert_interface(definition)

        self.assertEqual(converted["key"], "http:POST:/api/v1/auths/signin")
        self.assertEqual(converted["group_path"], "/认证")
        self.assertEqual(
            converted["request"],
            {
                "method": "POST",
                "path": "/api/v1/auths/signin",
                "headers": {
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                "body": {
                    "username": "{{ username }}",
                    "password": "{{ password }}",
                },
                "timeout_seconds": 20,
            },
        )
        self.assertEqual(converted["template_key"], "athena-auth")
        self.assertEqual(converted["success_assertion_key"], "system:success-status")
        self.assertEqual(converted["request_schema"]["accept"], "application/json")
        self.assertEqual(converted["request_schema"]["schema"]["required"], ["username", "password"])

    def test_route_key_must_match_http_method_and_path(self) -> None:
        with self.assertRaisesRegex(SystemExit, "HTTP API key must equal"):
            convert_interface(
                {
                    "key": "http:GET:/api/v1/auths/signin",
                    "protocol": "http",
                    "method": "POST",
                    "path": "/api/v1/auths/signin",
                }
            )

    def test_legacy_business_keys_remain_import_compatible(self) -> None:
        converted = convert_interface(
            {
                "key": "health",
                "protocol": "http",
                "method": "GET",
                "path": "/health",
            }
        )

        self.assertEqual(converted["key"], "health")
        self.assertEqual(converted["group_path"], "/")
        self.assertEqual(converted["request"], {"method": "GET", "path": "/health", "headers": {}})


if __name__ == "__main__":
    unittest.main()
