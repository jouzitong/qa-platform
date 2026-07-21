import asyncio
import json
from dataclasses import dataclass
from typing import Any

import httpx
import websockets


@dataclass
class ExecutionResult:
    request: dict[str, Any]
    response: dict[str, Any]


async def execute_http(config: dict[str, Any]) -> ExecutionResult:
    method = str(config.get("method", "GET")).upper()
    url = _resolve_url(config)
    if not url:
        raise ValueError("HTTP API requires request.url")

    timeout = float(config.get("timeout_seconds", 30))
    request_snapshot = {
        "protocol": "http",
        "method": method,
        "url": url,
        "headers": _mask_headers(config.get("headers", {})),
        "query": config.get("query", {}),
        "body": config.get("body"),
    }
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        response = await client.request(
            method,
            url,
            headers=config.get("headers"),
            params=config.get("query"),
            json=config.get("body") if "body" in config else None,
        )

    try:
        body: Any = response.json()
    except json.JSONDecodeError:
        body = response.text
    return ExecutionResult(
        request=request_snapshot,
        response={
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "body": body,
            "elapsed_ms": response.elapsed.total_seconds() * 1000,
        },
    )


async def execute_ws(config: dict[str, Any]) -> ExecutionResult:
    url = _resolve_url(config)
    if not url:
        raise ValueError("WebSocket API requires request.url")

    headers = config.get("headers", {})
    messages = config.get("messages", [])
    receive_count = int(config.get("receive_count", len(messages) or 1))
    timeout = float(config.get("timeout_seconds", 30))
    received: list[Any] = []
    async with websockets.connect(
        url,
        additional_headers=headers or None,
        open_timeout=timeout,
        close_timeout=timeout,
    ) as socket:
        for message in messages:
            payload = (
                message if isinstance(message, str) else json.dumps(message, ensure_ascii=False)
            )
            await socket.send(payload)
        for _ in range(receive_count):
            raw = await asyncio.wait_for(socket.recv(decode=False), timeout=timeout)
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="replace")
            try:
                received.append(json.loads(raw))
            except (json.JSONDecodeError, TypeError):
                received.append(raw)

    return ExecutionResult(
        request={
            "protocol": "ws",
            "url": url,
            "headers": _mask_headers(headers),
            "messages": messages,
            "receive_count": receive_count,
        },
        response={"messages": received},
    )


def _mask_headers(headers: dict[str, Any]) -> dict[str, Any]:
    sensitive = {"authorization", "proxy-authorization", "cookie", "set-cookie", "x-api-key"}
    return {
        key: "***" if key.lower() in sensitive else value
        for key, value in headers.items()
    }


def _resolve_url(config: dict[str, Any]) -> str | None:
    if config.get("url"):
        return str(config["url"])
    base_url = config.get("base_url")
    if not base_url:
        return None
    path = str(config.get("path", ""))
    return f"{str(base_url).rstrip('/')}/{path.lstrip('/')}" if path else str(base_url)
