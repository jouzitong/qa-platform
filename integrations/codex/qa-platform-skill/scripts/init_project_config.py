#!/usr/bin/env python3
"""Create a project-local qa-platform service and target-variable configuration."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from project_config import (
    default_success_assertions,
    detect_language,
    normalize_language,
    normalize_project_base_url,
    normalize_storage,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", default=".", help="Project root")
    parser.add_argument("--output", default=None, help="Config path; defaults to .qa-platform.json")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument(
        "--project-base-url",
        required=True,
        help="Required target project host:port, for example 127.0.0.1:9764; no URL scheme",
    )
    parser.add_argument("--api-prefix", default="/api/v1")
    parser.add_argument("--project-id", default=None)
    parser.add_argument("--project-key", default=None)
    parser.add_argument("--project-name", default=None)
    parser.add_argument("--project-description", default="")
    parser.add_argument("--endpoint", choices=("preview", "one-click"), default="preview")
    parser.add_argument("--source", default="workspace")
    parser.add_argument("--language", default=None, help="Primary project language, for example zh-CN or en")
    parser.add_argument(
        "--package-version",
        default=None,
        help="Optional release-version override; otherwise the scanner reads project metadata",
    )
    parser.add_argument("--storage-dir", default="releases", help="Directory for scan manifests and archives")
    parser.add_argument(
        "--no-versioned-storage",
        action="store_true",
        help="Do not create one storage bucket per test version",
    )
    parser.add_argument("--manifest-filename", default="qa-platform-import.json")
    parser.add_argument("--archive-filename", default="qa-platform-import.zip")
    parser.add_argument(
        "--api-document",
        action="append",
        default=[],
        help="Project-local OpenAPI/Swagger document; may be repeated",
    )
    parser.add_argument(
        "--openapi-url",
        action="append",
        default=[],
        help="Explicit runtime OpenAPI/Swagger URL; may be repeated",
    )
    parser.add_argument(
        "--enable-runtime-openapi",
        action="store_true",
        help="Try conventional runtime API-document endpoints when framework evidence exists",
    )
    parser.add_argument(
        "--flow-document",
        action="append",
        default=[],
        help="Markdown/AsciiDoc/JSON/YAML test-flow document; may be repeated",
    )
    parser.add_argument("--force", action="store_true", help="Replace an existing config")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root).expanduser().resolve()
    if not root.is_dir():
        raise SystemExit(f"Project root is not a directory: {root}")
    output = Path(args.output).expanduser() if args.output else root / ".qa-platform.json"
    if not output.is_absolute():
        output = root / output
    if output.exists() and not args.force:
        raise SystemExit(f"Config already exists: {output}; use --force to replace it")
    language = normalize_language(args.language, source="user_config", confidence=1.0) if args.language else detect_language(root)
    project_base_url = normalize_project_base_url(args.project_base_url)
    storage = normalize_storage(
        {
            "directory": args.storage_dir,
            "versioned": not args.no_versioned_storage,
            "manifest_filename": args.manifest_filename,
            "archive_filename": args.archive_filename,
        }
    )
    project_key = args.project_key or re.sub(
        r"[^A-Za-z0-9]+", "-", root.name.lower()
    ).strip("-") or "project"
    config = {
        "base_url": args.base_url.rstrip("/"),
        "project": {
            "key": project_key,
            "name": args.project_name or root.name,
            "description": args.project_description,
        },
        "variables": {"base_url": project_base_url},
        "api_prefix": args.api_prefix,
        "project_id": args.project_id,
        "endpoint": args.endpoint,
        "source": args.source,
        "language": language,
        "package_version": args.package_version,
        "storage": storage,
        "api_templates": [],
        "success_assertions": default_success_assertions(),
        "flow_documents": [
            {"path": path, "required": True} for path in args.flow_document
        ],
        "openapi": {
            "documents": [
                {"path": path, "required": True} for path in args.api_document
            ],
            "urls": [
                {"url": url, "required": False} for url in args.openapi_url
            ],
            "auto_discover": True,
            "runtime_discovery": {
                "enabled": args.enable_runtime_openapi,
                "scheme": "http",
                "paths": [],
                "timeout_seconds": 3,
                "max_bytes": 10485760,
            },
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "config": str(output),
                "base_url": config["base_url"],
                "variables": config["variables"],
                "project": config["project"],
                "endpoint": args.endpoint,
                "language": language,
                "package_version": args.package_version,
                "storage": storage,
                "success_assertions": config["success_assertions"],
                "api_templates": config["api_templates"],
                "flow_documents": config["flow_documents"],
                "openapi": config["openapi"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
