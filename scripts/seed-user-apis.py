#!/usr/bin/env python3
"""Seed a small, complete user-management API set for local API-directory demos."""

from __future__ import annotations

import argparse
import os
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-name",
        default="AI Assist Platform",
        help="Target project name (default: AI Assist Platform)",
    )
    parser.add_argument("--project-id", help="Target project ID; takes precedence over name")
    parser.add_argument(
        "--database",
        default=str(BACKEND / "qa-platform.db"),
        help="SQLite database path (default: backend/qa-platform.db)",
    )
    return parser.parse_args()


def envelope(data_schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["code", "data"],
        "properties": {
            "code": {"type": "integer", "const": 0, "example": 0},
            "message": {"type": "string", "example": "ok"},
            "data": deepcopy(data_schema),
        },
    }


def field(
    name: str,
    type_name: str,
    description: str,
    *,
    required: bool = False,
    example: Any = None,
    default: Any = None,
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "name": name,
        "type": type_name,
        "required": required,
        "description": description,
    }
    if example is not None:
        value["example"] = example
    if default is not None:
        value["default"] = default
    return value


def body_parameter(children: list[dict[str, Any]], example: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": "body",
        "in": "body",
        "type": "object",
        "required": True,
        "description": "用户管理请求体；字段在 body 下递归维护。",
        "example": example,
        "children": children,
    }


def user_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["id", "username", "displayName", "email", "status"],
        "properties": {
            "id": {"type": "string", "example": "usr_10001"},
            "username": {"type": "string", "example": "zhangsan"},
            "displayName": {"type": "string", "example": "张三"},
            "email": {"type": "string", "format": "email", "example": "zhangsan@example.com"},
            "status": {"type": "string", "enum": ["active", "disabled"], "example": "active"},
            "createdAt": {
                "type": "string",
                "format": "date-time",
                "example": "2026-08-19T09:00:00Z",
            },
        },
    }


def definitions() -> list[dict[str, Any]]:
    group_path = "/用户服务/用户管理"
    logical_user = user_schema()
    list_data = {
        "type": "object",
        "required": ["items", "total"],
        "properties": {
            "items": {"type": "array", "items": logical_user, "example": []},
            "total": {"type": "integer", "example": 1},
        },
    }
    common = {
        "group_path": group_path,
        "template_id": None,
        "success_assertion_id": None,
        "request_schema": {"accept": "application/json", "schema": {}},
        "examples": [],
        "response_variants": [],
    }

    def path_parameter(name: str) -> dict[str, Any]:
        return field(
            name,
            "string",
            "用户唯一标识",
            required=True,
            example="usr_10001",
        ) | {"in": "path"}

    create_body = {
        "username": "zhangsan",
        "displayName": "张三",
        "email": "zhangsan@example.com",
        "status": "active",
    }
    update_body = {"displayName": "张三（更新）", "status": "active"}

    def item(
        key: str,
        name: str,
        method: str,
        path: str,
        response: dict[str, Any],
        parameters: list[dict[str, Any]],
        *,
        description: str,
        request_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        request: dict[str, Any] = {
            "method": method,
            "path": path,
            "headers": {"Accept": "application/json"},
        }
        if request_body is not None:
            request["body"] = request_body
            request["headers"]["Content-Type"] = "application/json"
        return {
            **deepcopy(common),
            "key": key,
            "name": name,
            "protocol": "http",
            "description": description,
            "request": request,
            "parameters": parameters,
            "response_schema": response,
            "response_unpack": {
                "enabled": True,
                "source": "body.data",
                "envelope_schema": envelope(response),
            },
            "success_contract": {
                "status_codes": {"min": 200, "max": 299},
                "body_schema": response,
            },
        }

    return [
        item(
            "http:GET:/api/v1/users",
            "查询用户列表",
            "GET",
            "/api/v1/users",
            list_data,
            [
                field("keyword", "string", "按用户名、显示名或邮箱模糊查询", example="zhang")
                | {"in": "query"},
                field("page", "integer", "页码，从 1 开始", example=1, default=1)
                | {"in": "query"},
                field("pageSize", "integer", "每页返回数量", example=20, default=20)
                | {"in": "query"},
            ],
            description="分页查询用户列表。",
        ),
        item(
            "http:GET:/api/v1/users/{userId}",
            "查询用户详情",
            "GET",
            "/api/v1/users/{userId}",
            logical_user,
            [path_parameter("userId")],
            description="按用户 ID 查询用户详情。",
        ),
        item(
            "http:POST:/api/v1/users",
            "创建用户",
            "POST",
            "/api/v1/users",
            logical_user,
            [
                body_parameter(
                    [
                        field(
                            "username", "string", "登录用户名，项目内唯一",
                            required=True, example="zhangsan",
                        ),
                        field(
                            "displayName", "string", "用户显示名称",
                            required=True, example="张三",
                        ),
                        field(
                            "email", "string", "用户邮箱地址",
                            required=True, example="zhangsan@example.com",
                        ),
                        field(
                            "status", "string", "用户状态",
                            example="active", default="active",
                        ) | {"enum": ["active", "disabled"]},
                    ],
                    create_body,
                )
            ],
            description="创建一个新的平台用户。",
            request_body=create_body,
        ),
        item(
            "http:PATCH:/api/v1/users/{userId}",
            "更新用户",
            "PATCH",
            "/api/v1/users/{userId}",
            logical_user,
            [
                path_parameter("userId"),
                body_parameter(
                    [
                        field("displayName", "string", "用户显示名称", example="张三（更新）"),
                        field("email", "string", "用户邮箱地址", example="zhangsan@example.com"),
                        field("status", "string", "用户状态", example="active")
                        | {"enum": ["active", "disabled"]},
                    ],
                    update_body,
                ),
            ],
            description="更新用户资料或启用状态。",
            request_body=update_body,
        ),
        item(
            "http:DELETE:/api/v1/users/{userId}",
            "删除用户",
            "DELETE",
            "/api/v1/users/{userId}",
            {
                "type": "object",
                "required": ["deleted"],
                "properties": {"deleted": {"type": "boolean", "example": True}},
            },
            [path_parameter("userId")],
            description="删除指定用户。",
        ),
    ]


def main() -> int:
    args = parse_args()
    database_path = Path(args.database).expanduser().resolve()
    os.environ["DATABASE_URL"] = f"sqlite:///{database_path}"

    from app.database import Base, SessionLocal, engine, ensure_schema_compatibility
    from app.models import ApiDefinition, ApiTemplate, AssertionDefinition, Project

    Base.metadata.create_all(engine)
    ensure_schema_compatibility()
    with SessionLocal() as session:
        project = session.get(Project, args.project_id) if args.project_id else session.scalar(
            select(Project).where(Project.name == args.project_name)
        )
        if project is None:
            print(f"Project not found: {args.project_id or args.project_name}", file=sys.stderr)
            return 2

        template = session.scalar(
            select(ApiTemplate).where(
                ApiTemplate.project_id == project.id,
                ApiTemplate.protocol == "http",
                ApiTemplate.name.like("%网关鉴权%"),
            )
        )
        assertion = session.scalar(
            select(AssertionDefinition).where(
                AssertionDefinition.project_id == project.id,
                AssertionDefinition.key == "config:http-success-status",
            )
        )
        created = 0
        updated = 0
        for payload in definitions():
            payload["template_id"] = template.id if template else None
            payload["success_assertion_id"] = assertion.id if assertion else None
            existing = session.scalar(
                select(ApiDefinition).where(
                    ApiDefinition.project_id == project.id,
                    ApiDefinition.key == payload["key"],
                )
            )
            if existing is None:
                session.add(ApiDefinition(project_id=project.id, **payload))
                created += 1
            else:
                for field_name, value in payload.items():
                    setattr(existing, field_name, value)
                updated += 1
        session.commit()
        print(
            f"Seeded {created + updated} user APIs in {project.name}: "
            f"created={created}, updated={updated}, group=/用户服务/用户管理"
        )
        if template is None:
            print("Note: no gateway HTTP template found; APIs were created without a template.")
        if assertion is None:
            print(
                "Note: no config:http-success-status assertion found; "
                "APIs use compatibility contract."
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
