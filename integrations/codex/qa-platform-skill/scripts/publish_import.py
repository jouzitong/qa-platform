#!/usr/bin/env python3
"""Send an existing qa-platform ZIP to the preview or one-click endpoint."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

DEFAULT_CONFIG_NAMES = (".qa-platform.json", "qa-platform.json")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", help="Existing qa-platform ZIP")
    parser.add_argument("--root", default=".", help="Project root used to find config")
    parser.add_argument("--config", default=None, help="Explicit JSON config path")
    parser.add_argument("--base-url", default=None, help="Override configured service URL")
    parser.add_argument("--api-prefix", default=None, help="Override configured API prefix")
    parser.add_argument("--project-id", default=None, help="Override target project ID")
    parser.add_argument("--endpoint", choices=("preview", "one-click"), default=None)
    parser.add_argument("--source", default=None)
    parser.add_argument("--timeout", type=float, default=None)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def load_config(root: Path, explicit: str | None) -> tuple[dict, str]:
    candidates = [Path(explicit).expanduser()] if explicit else [root / name for name in DEFAULT_CONFIG_NAMES]
    for path in candidates:
        if not path.is_absolute():
            path = root / path
        if not path.exists():
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SystemExit(f"Unable to read qa-platform config {path}: {exc}") from None
        if not isinstance(value, dict):
            raise SystemExit(f"qa-platform config must be an object: {path}")
        nested = value.get("qa_platform")
        if isinstance(nested, dict):
            value = nested
        return value, str(path)
    return {}, "defaults"


def service_url(config: dict, base_url: str | None, api_prefix: str | None) -> str:
    base = str(base_url or config.get("base_url") or "http://localhost:8000").rstrip("/")
    prefix = str(api_prefix or config.get("api_prefix") or "/api/v1").strip("/")
    if not base.startswith(("http://", "https://")):
        raise SystemExit("qa-platform base_url must use http:// or https://")
    if prefix and not base.endswith(f"/{prefix}"):
        base = f"{base}/{prefix}"
    return base


def main() -> int:
    args = parse_args()
    archive = Path(args.archive).expanduser().resolve()
    if not archive.is_file():
        raise SystemExit(f"Archive does not exist: {archive}")
    if archive.suffix.lower() != ".zip":
        raise SystemExit("Only ZIP archives can be sent to qa-platform")
    root = Path(args.root).expanduser().resolve()
    config, config_source = load_config(root, args.config)
    endpoint = args.endpoint or str(config.get("endpoint") or "preview")
    project_id = args.project_id if args.project_id is not None else config.get("project_id")
    source = args.source or str(config.get("source") or ("external" if endpoint == "one-click" else "workspace"))
    timeout = args.timeout if args.timeout is not None else float(config.get("timeout_seconds") or 30)
    base = service_url(config, args.base_url, args.api_prefix)
    query = urlencode({"project_id": project_id}) if project_id else ""
    url = f"{base}/imports/{endpoint}" + (f"?{query}" if query else "")
    headers = {
        "Content-Type": "application/zip",
        "X-Import-Filename": archive.name,
        "X-Import-Source": source,
    }
    token = os.environ.get("QA_PLATFORM_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if args.dry_run:
        print(json.dumps({"url": url, "headers": headers, "config_source": config_source}, ensure_ascii=False, indent=2))
        return 0

    request = Request(url, data=archive.read_bytes(), headers=headers, method="POST")
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            result = json.loads(body) if body else {}
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"qa-platform import request failed ({exc.code}): {detail}") from None
    except URLError as exc:
        raise SystemExit(f"Unable to connect to qa-platform at {url}: {exc.reason}") from None
    print(json.dumps({"config_source": config_source, "endpoint": endpoint, "result": result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
