#!/usr/bin/env python3
"""Compare two qa-platform import manifests by stable external keys."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

SECTIONS = (
    "interfaces.http",
    "interfaces.ws",
    "features",
    "test_cases",
    "flows",
    "test_plans",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("old_manifest")
    parser.add_argument("new_manifest")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser.parse_args()


def value_at(document: dict[str, Any], section: str) -> list[dict[str, Any]]:
    value: Any = document
    for part in section.split("."):
        value = value.get(part, {}) if isinstance(value, dict) else {}
    return value if isinstance(value, list) else []


def keyed(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(item["key"]): item for item in items if isinstance(item, dict) and item.get("key")}


def diff(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for section in SECTIONS:
        before = keyed(value_at(old, section))
        after = keyed(value_at(new, section))
        created = sorted(set(after) - set(before))
        deleted = sorted(set(before) - set(after))
        changed = sorted(key for key in set(before) & set(after) if before[key] != after[key])
        result[section] = {
            "created": created,
            "updated": changed,
            "deleted": deleted,
            "unchanged": len(set(before) & set(after)) - len(changed),
        }
    return result


def main() -> int:
    args = parse_args()
    old = json.loads(Path(args.old_manifest).read_text(encoding="utf-8"))
    new = json.loads(Path(args.new_manifest).read_text(encoding="utf-8"))
    result = diff(old, new)
    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    for section, changes in result.items():
        print(f"{section}: +{len(changes['created'])} ~{len(changes['updated'])} -{len(changes['deleted'])} = {changes['unchanged']}")
        for label in ("created", "updated", "deleted"):
            for key in changes[label]:
                print(f"  {label}: {key}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
