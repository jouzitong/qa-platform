"""HTTP response views used by assertions, schemas, and flow extractors."""

from copy import deepcopy
from typing import Any

from app.execution.context import get_path


class ResponseUnpackError(ValueError):
    """Raised when a configured response envelope cannot be unwrapped."""


def attach_payload(
    response: dict[str, Any], response_unpack: dict[str, Any] | None
) -> dict[str, Any]:
    """Keep the wire body intact and attach a stable logical ``payload`` view.

    The runner historically exposed the decoded wire body as ``response.body``.
    Keeping that value unchanged preserves existing assertions and run snapshots;
    ``response.payload`` is the response body after the optional envelope path is
    resolved.  When unwrapping is disabled, payload is simply the raw body.
    """
    result = deepcopy(response)
    config = response_unpack if isinstance(response_unpack, dict) else {}
    if not config.get("enabled"):
        result["payload"] = deepcopy(response.get("body"))
        result["payload_source"] = "body"
        return result

    source = str(config.get("source") or "").strip()
    if not source:
        raise ResponseUnpackError("响应解包已启用，但未配置解包路径")
    try:
        payload = get_path(response, source)
    except KeyError:
        raise ResponseUnpackError(f"响应解包路径不存在：{source}") from None
    result["payload"] = deepcopy(payload)
    result["payload_source"] = source
    return result
