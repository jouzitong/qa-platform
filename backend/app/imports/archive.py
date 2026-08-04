from __future__ import annotations

import io
import json
import posixpath
import zipfile
from typing import Any


class ImportArchiveError(ValueError):
    """Raised when an import archive cannot be safely parsed."""


MAX_ARCHIVE_BYTES = 25 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 100 * 1024 * 1024
MAX_FILE_COUNT = 500

_ASSET_FILES = {
    "project": ("project.json",),
    "api_templates": ("api_templates.json", "api-template.json", "templates.json", "template.json"),
    "apis": ("apis.json", "api.json", "api-definitions.json"),
    "assertion_definitions": (
        "assertion_definitions.json",
        "assertions.json",
        "assertion.json",
    ),
    "assertion_profiles": (
        "assertion_profiles.json",
        "assertion-profiles.json",
        "profiles.json",
        "profile.json",
    ),
    "flows": ("flows.json", "flow.json"),
    "test_plans": ("test_plans.json", "plans.json", "plan.json"),
}


def _safe_name(name: str) -> str:
    normalized = posixpath.normpath(name.replace("\\", "/"))
    if normalized in {"", "."} or normalized.startswith("/") or normalized == "..":
        raise ImportArchiveError(f"压缩包包含不安全的路径：{name}")
    if normalized.startswith("../") or "/../" in normalized:
        raise ImportArchiveError(f"压缩包包含不安全的路径：{name}")
    return normalized


def _records(value: Any, label: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, list):
        values = value
    elif isinstance(value, dict):
        values = value.get(label)
        if values is None:
            values = value.get(label.rstrip("s"))
        if values is None and any(key in value for key in ("key", "name", "id")):
            values = [value]
        if values is None and all(isinstance(item, dict) for item in value.values()):
            values = [
                dict(item, key=key) if "key" not in item else item for key, item in value.items()
            ]
        if values is None:
            raise ImportArchiveError(f"{label} 文件必须是对象或数组")
    else:
        raise ImportArchiveError(f"{label} 文件必须是对象或数组")
    if not all(isinstance(item, dict) for item in values):
        raise ImportArchiveError(f"{label} 中的每个条目必须是对象")
    return [dict(item) for item in values]


def _read_json(files: dict[str, Any], names: tuple[str, ...], label: str) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for path, value in files.items():
        if path.rsplit("/", 1)[-1].lower() in names:
            selected.extend(_records(value, label))
    return selected


def _manifest_value(manifest: dict[str, Any], key: str, default: Any = None) -> Any:
    if key in manifest:
        return manifest[key]
    package = manifest.get("package")
    if isinstance(package, dict):
        return package.get(key, default)
    return default


def parse_import_archive(filename: str, content: bytes) -> dict[str, Any]:
    """Parse a versioned QA Platform ZIP into a safe, JSON-serializable package."""
    if len(content) > MAX_ARCHIVE_BYTES:
        raise ImportArchiveError("导入包不能超过 25 MB")
    suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if suffix == "rar":
        raise ImportArchiveError("暂不支持 RAR 压缩包，请先导出为 ZIP 格式")
    if suffix and suffix != "zip":
        raise ImportArchiveError("仅支持 ZIP 压缩包；RAR 将在后续版本支持")

    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except (zipfile.BadZipFile, OSError):
        raise ImportArchiveError("无法读取压缩包，请确认文件是有效的 ZIP") from None

    files: dict[str, Any] = {}
    total_size = 0
    try:
        infos = archive.infolist()
        if len(infos) > MAX_FILE_COUNT:
            raise ImportArchiveError("压缩包文件数量不能超过 500 个")
        for info in infos:
            safe_name = _safe_name(info.filename)
            if info.is_dir():
                continue
            if info.flag_bits & 0x1:
                raise ImportArchiveError(f"压缩包文件已加密，无法读取：{safe_name}")
            total_size += info.file_size
            if total_size > MAX_UNCOMPRESSED_BYTES:
                raise ImportArchiveError("压缩包解压后的内容不能超过 100 MB")
            if not safe_name.lower().endswith(".json"):
                continue
            try:
                files[safe_name] = json.loads(archive.read(info).decode("utf-8-sig"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ImportArchiveError(f"JSON 文件无法解析：{safe_name}（{exc}）") from None
    finally:
        archive.close()

    if not files:
        raise ImportArchiveError("压缩包中没有可解析的 JSON 文件")

    manifest = files.get("manifest.json", {})
    if not isinstance(manifest, dict):
        raise ImportArchiveError("manifest.json 必须是对象")
    project = files.get("project.json")
    if not isinstance(project, dict):
        project = _manifest_value(manifest, "project", {})
    if project is None:
        project = {}
    if not isinstance(project, dict):
        raise ImportArchiveError("project 必须是对象")

    package: dict[str, Any] = {
        "package_version": str(
            _manifest_value(manifest, "package_version")
            or _manifest_value(manifest, "version")
            or next(
                (
                    path.split("/", 1)[0]
                    for path in files
                    if "/" in path and path.split("/", 1)[0].startswith("v")
                ),
                "1.0",
            )
        ),
        "project": project,
        "source": _manifest_value(manifest, "source", {}),
        "api_templates": [],
        "apis": [],
        "assertion_definitions": [],
        "assertion_profiles": [],
        "flows": [],
        "test_plans": [],
        "warnings": list(_manifest_value(manifest, "warnings", []) or []),
    }
    for label, names in _ASSET_FILES.items():
        if label == "project":
            continue
        package[label] = _read_json(files, names, label)

    interfaces = manifest.get("interfaces", {})
    if isinstance(interfaces, dict):
        package["apis"].extend(_records(interfaces.get("http"), "apis"))
        package["apis"].extend(_records(interfaces.get("ws"), "apis"))

    if manifest.get("features"):
        package["warnings"].append("导入包包含 features，但当前平台没有独立功能资产模型，已跳过")
    if manifest.get("test_cases"):
        package["warnings"].append("导入包包含 test_cases，但当前平台没有独立测试用例模型，已跳过")
    package["source"] = package["source"] if isinstance(package["source"], dict) else {}
    return package
