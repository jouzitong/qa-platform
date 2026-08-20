"""Canonical API-directory path helpers shared by scan and import validation."""

from __future__ import annotations

import re
from typing import Any

GROUP_PATH_MAX_LENGTH = 240


def normalize_group_path(value: Any) -> str:
    """Normalize a project/API directory path to ``/segment/segment`` form."""
    raw = str(value or "").strip()
    if not raw or raw == "/":
        return "/"

    segments: list[str] = []
    for raw_segment in re.split(r"[/\\]", raw):
        segment = raw_segment.strip()
        if not segment:
            continue
        if segment in {".", ".."}:
            raise ValueError("API group path cannot contain '.' or '..'")
        if any(ord(char) < 32 for char in segment):
            raise ValueError("API group path cannot contain control characters")
        segments.append(segment)

    normalized = "/" + "/".join(segments) if segments else "/"
    if len(normalized) > GROUP_PATH_MAX_LENGTH:
        raise ValueError(
            f"API group path cannot exceed {GROUP_PATH_MAX_LENGTH} characters"
        )
    return normalized


def group_path_error(value: Any, *, require_canonical: bool = True) -> str | None:
    """Return a validation message for an imported API directory path."""
    if not isinstance(value, str):
        return "must be a string"
    raw = value.strip()
    if not raw:
        return "must not be empty"
    if raw == "/":
        return None
    if not raw.startswith("/"):
        return "must start with '/'"
    if "\\" in raw:
        return "must use '/' separators"
    if "//" in raw or raw.endswith("/"):
        return "must not contain empty path segments"
    segments = raw[1:].split("/")
    if any(not segment.strip() for segment in segments):
        return "must not contain empty path segments"
    if any(segment in {".", ".."} for segment in segments):
        return "must not contain '.' or '..'"
    if any(any(ord(char) < 32 for char in segment) for segment in segments):
        return "must not contain control characters"
    try:
        normalized = normalize_group_path(raw)
    except ValueError as exc:
        return str(exc)
    if require_canonical and normalized != raw:
        return f"must be canonical: {normalized}"
    return None


def group_path_from_segments(segments: list[str]) -> str:
    """Build a canonical path while dropping unsafe/empty heuristic segments."""
    cleaned: list[str] = []
    for raw_segment in segments:
        segment = str(raw_segment or "").strip().strip("/\\")
        if not segment or segment in {".", ".."}:
            continue
        segment = re.sub(r"\s+", " ", segment)
        if segment not in cleaned:
            cleaned.append(segment)
    return normalize_group_path("/" + "/".join(cleaned))
