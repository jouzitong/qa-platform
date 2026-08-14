"""Shared project configuration, language detection, and artifact path helpers."""

from __future__ import annotations

import configparser
import json
import locale
import os
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 compatibility for the standalone Skill.
    tomllib = None  # type: ignore[assignment]


DEFAULT_CONFIG_NAMES = (".qa-platform.json", "qa-platform.json")
DEFAULT_STORAGE = {
    "directory": "releases",
    "versioned": True,
    "manifest_filename": "qa-platform-import.json",
    "archive_filename": "qa-platform-import.zip",
}
SUCCESS_ASSERTION_PROTOCOLS = ("http", "ws")
DEFAULT_SUCCESS_ASSERTIONS: dict[str, Any] = {
    "default_assertion": {
        "http": "config:http-success-status",
        "ws": "config:ws-success-messages",
    },
    "definitions": [
        {
            "key": "config:http-success-status",
            "name": "默认 HTTP 成功状态码",
            "engine": "expression",
            "description": "默认 HTTP 成功断言：响应状态码必须在 200–299 范围内。",
            "config": {"expression": "response.status_code >= 200 and response.status_code <= 299"},
            "default_params": {},
            "severity": "success",
            "message": "HTTP 状态码不在 200–299 范围内",
        },
        {
            "key": "config:ws-success-messages",
            "name": "默认 WebSocket 成功消息",
            "engine": "expression",
            "description": "默认 WebSocket 成功断言：至少收到一条消息。",
            "config": {"expression": "len(response.messages) >= params['minimum']"},
            "default_params": {"minimum": 1},
            "severity": "success",
            "message": "WebSocket 未收到成功消息",
        },
    ],
}
DEFAULT_PACKAGE_VERSION = "v1.0.0"
SNAPSHOT_SUFFIX_RE = re.compile(r"(?i)(?:[-_.]?snapshot)$")
LANGUAGE_LABELS = {
    "zh-cn": "中文",
    "zh": "中文",
    "en": "English",
    "ja": "日本語",
    "ko": "한국어",
    "ru": "Русский",
    "es": "Español",
    "fr": "Français",
    "de": "Deutsch",
}
LANGUAGE_ALIASES = {
    "zh": "zh-CN",
    "zh-cn": "zh-CN",
    "zh_cn": "zh-CN",
    "cn": "zh-CN",
    "en-us": "en",
    "en_us": "en",
    "en-gb": "en",
    "en_gb": "en",
    "ja-jp": "ja",
    "ja_jp": "ja",
    "ko-kr": "ko",
    "ko_kr": "ko",
}
SOURCE_SUFFIXES = {
    ".py",
    ".java",
    ".kt",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".vue",
    ".go",
    ".rb",
    ".php",
    ".json",
    ".yaml",
    ".yml",
    ".md",
    ".adoc",
}
SKIP_DIRS = {
    ".git",
    ".codegraph",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "dist",
    "build",
    "target",
    "coverage",
    "__pycache__",
}
COMMENT_RE = re.compile(
    r"""
    /\*[\s\S]*?\*/
    |<!--[\s\S]*?-->
    |^[ \t]*\#.*$
    |^[ \t]*//.*$
    |^[ \t]*--.*$
    |'''[\s\S]*?'''
    |\"\"\"[\s\S]*?\"\"\"
    """,
    re.MULTILINE | re.VERBOSE,
)


def _canonical_language_code(value: str) -> str:
    raw = value.strip().replace("_", "-")
    if not raw:
        return "zh-CN"
    return LANGUAGE_ALIASES.get(raw.lower(), raw)


def normalize_language(
    value: Any,
    *,
    source: str | None = None,
    confidence: float | None = None,
) -> dict[str, Any]:
    """Return the stable language metadata shape used by config and manifests."""
    if isinstance(value, dict):
        code_value = value.get("code") or value.get("locale") or value.get("language")
        source = source or (str(value.get("source")) if value.get("source") else None)
        confidence = confidence if confidence is not None else value.get("confidence")
    else:
        code_value = value
    code = _canonical_language_code(str(code_value or "zh-CN"))
    label = LANGUAGE_LABELS.get(code.lower(), code)
    try:
        score = float(confidence if confidence is not None else 1.0)
    except (TypeError, ValueError):
        score = 1.0
    return {
        "code": code,
        "label": label,
        "source": source or "config",
        "confidence": round(max(0.0, min(score, 1.0)), 3),
    }


def _comment_text(text: str) -> str:
    return "\n".join(match.group(0) for match in COMMENT_RE.finditer(text))


def _language_scores(text: str) -> dict[str, int]:
    return {
        "zh-CN": len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]", text)),
        "ja": len(re.findall(r"[\u3040-\u30ff]", text)),
        "ko": len(re.findall(r"[\uac00-\ud7af]", text)),
        "ru": len(re.findall(r"[\u0400-\u04ff]", text)),
        "en": len(re.findall(r"[A-Za-z]", text)),
    }


def _iter_candidate_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in SOURCE_SUFFIXES:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        yield path


def system_language() -> str | None:
    known = {"zh-cn", "en", "ja", "ko", "ru", "es", "fr", "de"}
    for value in (
        os.environ.get("LC_ALL"),
        os.environ.get("LC_MESSAGES"),
        os.environ.get("LANG"),
    ):
        if value:
            code = _canonical_language_code(value.split(".", 1)[0])
            if code.lower() in known:
                return code
    try:
        value = locale.getlocale()[0]
    except (ValueError, AttributeError):
        value = None
    if not value:
        return None
    code = _canonical_language_code(value)
    return code if code.lower() in known else None


def detect_language(root: Path, files: Iterable[Path] | None = None) -> dict[str, Any]:
    """Infer the project's writing language from comments, then locale, then Chinese."""
    comment_texts: list[str] = []
    candidates = files if files is not None else _iter_candidate_files(root)
    for path in candidates:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")[:1_000_000]
        except OSError:
            continue
        comments = _comment_text(text)
        if comments.strip():
            comment_texts.append(comments)

    scores = _language_scores("\n".join(comment_texts))
    total = sum(scores.values())
    if total >= 4:
        code, score = max(scores.items(), key=lambda item: item[1])
        if score >= 2:
            return normalize_language(
                code,
                source="project_comments",
                confidence=max(0.5, min(0.99, score / total)),
            )

    locale_code = system_language()
    if locale_code:
        return normalize_language(locale_code, source="system_locale", confidence=0.6)
    return normalize_language("zh-CN", source="default", confidence=0.2)


def load_project_config(root: Path, explicit: str | None = None) -> tuple[dict[str, Any], Path | None]:
    candidates = [Path(explicit).expanduser()] if explicit else [root / name for name in DEFAULT_CONFIG_NAMES]
    for path in candidates:
        if not path.is_absolute():
            path = root / path
        if not path.is_file():
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
        return value, path.resolve()
    return {}, None


def default_success_assertions() -> dict[str, Any]:
    """Return an independent starter success-assertion configuration."""
    return deepcopy(DEFAULT_SUCCESS_ASSERTIONS)


def normalize_success_assertions(value: Any) -> dict[str, Any] | None:
    """Validate project-configured success conditions."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise SystemExit("qa-platform success_assertions must be an object")

    raw_defaults = value.get("default_assertion")
    if isinstance(raw_defaults, str):
        raw_defaults = {"http": raw_defaults}
    if not isinstance(raw_defaults, dict) or not raw_defaults:
        raise SystemExit(
            "qa-platform success_assertions.default_assertion must map http and/or ws to a condition key"
        )
    default_assertions: dict[str, str] = {}
    for protocol, assertion_key in raw_defaults.items():
        normalized_protocol = str(protocol).lower()
        if normalized_protocol not in SUCCESS_ASSERTION_PROTOCOLS:
            raise SystemExit(
                "qa-platform success_assertions.default_assertion supports only http and ws"
            )
        normalized_key = str(assertion_key or "").strip()
        if not normalized_key:
            raise SystemExit(
                f"qa-platform success_assertions.default_assertion.{normalized_protocol} must be a non-empty condition key"
            )
        default_assertions[normalized_protocol] = normalized_key

    raw_definitions = value.get("definitions", [])
    if not isinstance(raw_definitions, list):
        raise SystemExit("qa-platform success_assertions.definitions must be a list")

    definitions: list[dict[str, Any]] = []
    definition_keys: set[str] = set()
    for index, raw_definition in enumerate(raw_definitions):
        if not isinstance(raw_definition, dict):
            raise SystemExit(f"qa-platform success_assertions.definitions[{index}] must be an object")
        definition = deepcopy(raw_definition)
        key = str(definition.get("key") or "").strip()
        name = str(definition.get("name") or "").strip()
        engine = str(definition.get("engine") or "").strip()
        if not key or not name or not engine:
            raise SystemExit(
                f"qa-platform success_assertions.definitions[{index}] requires key, name, and engine"
            )
        if key in definition_keys:
            raise SystemExit(f"qa-platform success_assertions has duplicate definition key: {key}")
        if not isinstance(definition.get("config", {}), dict):
            raise SystemExit(f"qa-platform success_assertions.definitions[{index}].config must be an object")
        if not isinstance(definition.get("default_params", {}), dict):
            raise SystemExit(
                f"qa-platform success_assertions.definitions[{index}].default_params must be an object"
            )
        definition["key"] = key
        definition["name"] = name
        definition["engine"] = engine
        definition.setdefault("description", "")
        definition.setdefault("config", {})
        definition.setdefault("default_params", {})
        definition.setdefault("severity", "success")
        definition.setdefault("message", "")
        definition_keys.add(key)
        definitions.append(definition)

    for protocol, assertion_key in default_assertions.items():
        if assertion_key not in definition_keys:
            raise SystemExit(
                f"qa-platform success_assertions.default_assertion.{protocol} references unknown condition: {assertion_key}"
            )
    return {
        "default_assertions": default_assertions,
        "definitions": definitions,
    }


def normalize_project_metadata(value: Any) -> dict[str, str]:
    """Normalize optional project identity and descriptive metadata."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise SystemExit("qa-platform project must be an object")
    result: dict[str, str] = {}
    for field in ("key", "name", "description"):
        if field not in value:
            continue
        normalized = str(value.get(field) or "").strip()
        if field in {"key", "name"} and not normalized:
            raise SystemExit(f"qa-platform project.{field} must be a non-empty string")
        result[field] = normalized
    return result


def normalize_api_templates(value: Any) -> list[dict[str, Any]]:
    """Validate reusable API templates declared by the target project."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise SystemExit("qa-platform api_templates must be a list")
    result: list[dict[str, Any]] = []
    names: set[str] = set()
    aliases: set[str] = set()
    for index, raw in enumerate(value):
        if not isinstance(raw, dict):
            raise SystemExit(f"qa-platform api_templates[{index}] must be an object")
        template = deepcopy(raw)
        name = str(template.get("name") or "").strip()
        if not name:
            raise SystemExit(f"qa-platform api_templates[{index}].name is required")
        if name in names or name in aliases:
            raise SystemExit(f"qa-platform api_templates has duplicate name: {name}")
        protocol = str(template.get("protocol") or "http").lower()
        if protocol not in {"http", "ws"}:
            raise SystemExit(
                f"qa-platform api_templates[{index}].protocol must be http or ws"
            )
        key = str(template.get("key") or name).strip()
        if not key:
            raise SystemExit(f"qa-platform api_templates[{index}].key must be non-empty")
        if key in aliases or (key in names and key != name):
            raise SystemExit(f"qa-platform api_templates has duplicate key: {key}")
        for field in ("request", "match"):
            if field in template and not isinstance(template[field], dict):
                raise SystemExit(
                    f"qa-platform api_templates[{index}].{field} must be an object"
                )
        for field in ("parameters", "examples"):
            if field in template and not isinstance(template[field], list):
                raise SystemExit(
                    f"qa-platform api_templates[{index}].{field} must be a list"
                )
        template["key"] = key
        template["name"] = name
        template["protocol"] = protocol
        template.setdefault("description", "")
        template.setdefault("request", {})
        template.setdefault("parameters", [])
        template.setdefault("examples", [])
        names.add(name)
        aliases.update({key, name})
        result.append(template)
    return result


def normalize_flow_documents(value: Any) -> list[dict[str, Any]]:
    """Normalize project documents that guide or define test flows."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise SystemExit("qa-platform flow_documents must be a list")
    result: list[dict[str, Any]] = []
    paths: set[str] = set()
    for index, raw in enumerate(value):
        document = {"path": raw} if isinstance(raw, str) else deepcopy(raw)
        if not isinstance(document, dict):
            raise SystemExit(f"qa-platform flow_documents[{index}] must be a path or object")
        path = str(document.get("path") or "").strip()
        if not path:
            raise SystemExit(f"qa-platform flow_documents[{index}].path is required")
        if path in paths:
            raise SystemExit(f"qa-platform flow_documents has duplicate path: {path}")
        document["path"] = path
        document["required"] = bool(document.get("required", True))
        document["format"] = str(document.get("format") or "auto").lower()
        if document["format"] not in {
            "auto",
            "markdown",
            "asciidoc",
            "json",
            "yaml",
            "text",
        }:
            raise SystemExit(
                f"qa-platform flow_documents[{index}].format is unsupported"
            )
        paths.add(path)
        result.append(document)
    return result


def _normalize_openapi_source(raw: Any, field: str, index: int) -> dict[str, Any]:
    source_key = "url" if field == "urls" else "path"
    source = {source_key: raw} if isinstance(raw, str) else deepcopy(raw)
    if not isinstance(source, dict):
        raise SystemExit(f"qa-platform openapi.{field}[{index}] must be a string or object")
    value = str(source.get(source_key) or "").strip()
    if not value:
        raise SystemExit(f"qa-platform openapi.{field}[{index}].{source_key} is required")
    source[source_key] = value
    source["required"] = bool(source.get("required", field == "documents"))
    return source


def normalize_openapi_config(value: Any) -> dict[str, Any]:
    """Normalize deterministic local/runtime OpenAPI and Swagger sources."""
    if value is None:
        value = {}
    if isinstance(value, list):
        value = {"documents": value}
    if not isinstance(value, dict):
        raise SystemExit("qa-platform openapi must be an object")
    documents = value.get("documents", [])
    urls = value.get("urls", [])
    if not isinstance(documents, list) or not isinstance(urls, list):
        raise SystemExit("qa-platform openapi.documents and openapi.urls must be lists")
    runtime = value.get("runtime_discovery", {})
    if isinstance(runtime, bool):
        runtime = {"enabled": runtime}
    if not isinstance(runtime, dict):
        raise SystemExit("qa-platform openapi.runtime_discovery must be an object or boolean")
    paths = runtime.get("paths", [])
    if not isinstance(paths, list):
        raise SystemExit("qa-platform openapi.runtime_discovery.paths must be a list")
    try:
        timeout_seconds = float(runtime.get("timeout_seconds", 3))
    except (TypeError, ValueError):
        raise SystemExit(
            "qa-platform openapi.runtime_discovery.timeout_seconds must be numeric"
        ) from None
    try:
        max_bytes = int(runtime.get("max_bytes", 10 * 1024 * 1024))
    except (TypeError, ValueError):
        raise SystemExit(
            "qa-platform openapi.runtime_discovery.max_bytes must be an integer"
        ) from None
    if timeout_seconds <= 0 or max_bytes <= 0:
        raise SystemExit(
            "qa-platform openapi runtime timeout_seconds and max_bytes must be positive"
        )
    return {
        "documents": [
            _normalize_openapi_source(item, "documents", index)
            for index, item in enumerate(documents)
        ],
        "urls": [
            _normalize_openapi_source(item, "urls", index)
            for index, item in enumerate(urls)
        ],
        "auto_discover": bool(value.get("auto_discover", True)),
        "runtime_discovery": {
            "enabled": bool(runtime.get("enabled", False)),
            "scheme": str(runtime.get("scheme") or "http").lower(),
            "paths": [str(item).strip() for item in paths if str(item).strip()],
            "timeout_seconds": timeout_seconds,
            "max_bytes": max_bytes,
        },
    }


def normalize_project_base_url(value: Any, *, allow_http_scheme: bool = False) -> str:
    """Validate the target project's host:port variable.

    qa-platform prepends ``http://`` when resolving the project variable, so
    project variables intentionally do not contain a URL scheme.
    """
    raw = str(value or "").strip().rstrip("/")
    if allow_http_scheme and raw.startswith(("http://", "https://")):
        parsed = None
        try:
            parsed = urlsplit(raw)
            parsed_port = parsed.port
            parsed_hostname = parsed.hostname
        except ValueError:
            parsed_port = None
            parsed_hostname = None
        if (
            parsed is None
            or parsed_port is None
            or not parsed_hostname
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
        ):
            raise SystemExit("Project variables.base_url must resolve to host:port without a path")
        raw = f"{parsed_hostname}:{parsed_port}"
    if "://" in raw or "/" in raw or any(char.isspace() for char in raw):
        raise SystemExit("Project variables.base_url must be an IP/host:port without http://")
    if raw.startswith("["):
        closing = raw.find("]")
        host = raw[1:closing] if closing > 0 else ""
        port_text = raw[closing + 2 :] if closing > 0 and raw[closing + 1 : closing + 2] == ":" else ""
    else:
        host, separator, port_text = raw.rpartition(":")
    if not host or not port_text.isdigit() or not 1 <= int(port_text) <= 65535:
        raise SystemExit("Project variables.base_url must be an IP/host:port without http://")
    return raw


def normalize_project_variables(
    value: Any, *, require_base_url: bool = False, allow_http_scheme: bool = False
) -> dict[str, Any]:
    """Normalize project variables and enforce the required target base_url."""
    if value is None:
        variables: dict[str, Any] = {}
    elif isinstance(value, dict):
        variables = dict(value)
    else:
        raise SystemExit("qa-platform project variables must be an object")
    if require_base_url or "base_url" in variables:
        if not str(variables.get("base_url") or "").strip():
            raise SystemExit("qa-platform project variables must define required variables.base_url")
        variables["base_url"] = normalize_project_base_url(
            variables["base_url"], allow_http_scheme=allow_http_scheme
        )
    return variables


def resolve_language(
    root: Path,
    config: dict[str, Any],
    files: Iterable[Path] | None = None,
    override: str | None = None,
) -> dict[str, Any]:
    if override:
        return normalize_language(override, source="cli", confidence=1.0)
    configured = config.get("language")
    if configured:
        return normalize_language(configured)
    return detect_language(root, files)


def normalize_package_version(value: Any, fallback: str = DEFAULT_PACKAGE_VERSION) -> str:
    """Normalize a release version without changing non-SNAPSHOT qualifiers."""
    raw = str(value or "").strip()
    raw = SNAPSHOT_SUFFIX_RE.sub("", raw).strip()
    return raw or fallback


def _version_source(value: Any, source: str, path: Path | None = None) -> dict[str, Any] | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    result: dict[str, Any] = {
        "value": normalize_package_version(raw),
        "source": source,
    }
    if raw != result["value"]:
        result["raw"] = raw
    if path is not None:
        result["path"] = path.name
    return result


def _read_json_object(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _maven_property_value(raw: str, properties: dict[str, str]) -> tuple[str, str | None]:
    match = re.fullmatch(r"\$\{(?P<name>[^}]+)\}", raw.strip())
    if not match:
        return raw, None
    name = match.group("name")
    return properties.get(name, raw), name


def _maven_version(root: Path) -> dict[str, Any] | None:
    pom = root / "pom.xml"
    if not pom.is_file():
        return None
    try:
        document = ET.fromstring(pom.read_text(encoding="utf-8"))
    except (OSError, ET.ParseError):
        return None

    def children(element: ET.Element, name: str) -> list[ET.Element]:
        return [child for child in element if child.tag.rsplit("}", 1)[-1] == name]

    properties: dict[str, str] = {}
    for properties_element in children(document, "properties"):
        for child in properties_element:
            value = (child.text or "").strip()
            if value:
                properties[child.tag.rsplit("}", 1)[-1]] = value

    direct_versions = children(document, "version")
    if direct_versions:
        raw = (direct_versions[0].text or "").strip()
        resolved, property_name = _maven_property_value(raw, properties)
        return _version_source(
            resolved,
            "maven.revision" if property_name == "revision" else "maven.version",
            pom,
        )
    return _version_source(properties.get("revision"), "maven.revision", pom)


def _pyproject_version(root: Path) -> dict[str, Any] | None:
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        return None
    try:
        text = pyproject.read_text(encoding="utf-8")
    except OSError:
        return None

    if tomllib is not None:
        try:
            document = tomllib.loads(text)
        except (TypeError, ValueError):
            document = {}
        project = document.get("project") if isinstance(document, dict) else None
        if isinstance(project, dict):
            result = _version_source(project.get("version"), "python.pyproject.project", pyproject)
            if result:
                return result
        tool = document.get("tool") if isinstance(document, dict) else None
        poetry = tool.get("poetry") if isinstance(tool, dict) else None
        if isinstance(poetry, dict):
            result = _version_source(poetry.get("version"), "python.pyproject.poetry", pyproject)
            if result:
                return result

    section: str | None = None
    for line in text.splitlines():
        section_match = re.match(r"\s*\[(?P<section>[^]]+)]\s*$", line)
        if section_match:
            section = section_match.group("section").strip().lower()
            continue
        if section not in {"project", "tool.poetry"}:
            continue
        version_match = re.match(r"\s*version\s*=\s*['\"](?P<version>[^'\"]+)['\"]", line)
        if version_match:
            source = "python.pyproject.project" if section == "project" else "python.pyproject.poetry"
            return _version_source(version_match.group("version"), source, pyproject)
    return None


def _python_version(root: Path) -> dict[str, Any] | None:
    result = _pyproject_version(root)
    if result:
        return result

    setup_cfg = root / "setup.cfg"
    if setup_cfg.is_file():
        parser = configparser.ConfigParser(interpolation=None)
        try:
            parser.read(setup_cfg, encoding="utf-8")
        except (OSError, configparser.Error):
            pass
        else:
            if parser.has_option("metadata", "version"):
                result = _version_source(parser.get("metadata", "version"), "python.setup_cfg", setup_cfg)
                if result:
                    return result

    setup_py = root / "setup.py"
    if setup_py.is_file():
        try:
            text = setup_py.read_text(encoding="utf-8")
        except OSError:
            text = ""
        match = re.search(r"\bversion\s*=\s*['\"](?P<version>[^'\"]+)['\"]", text)
        if match:
            return _version_source(match.group("version"), "python.setup_py", setup_py)
    return None


def _node_version(root: Path) -> dict[str, Any] | None:
    package = root / "package.json"
    if not package.is_file():
        return None
    document = _read_json_object(package)
    return _version_source((document or {}).get("version"), "node.package_json", package)


def _gradle_version(root: Path) -> dict[str, Any] | None:
    for filename in ("build.gradle", "build.gradle.kts"):
        build_file = root / filename
        if not build_file.is_file():
            continue
        try:
            text = build_file.read_text(encoding="utf-8")
        except OSError:
            continue
        match = re.search(r"(?m)^\s*version\s*=\s*['\"](?P<version>[^'\"]+)['\"]", text)
        if match:
            return _version_source(match.group("version"), "gradle.version", build_file)
    return None


def _version_file(root: Path) -> dict[str, Any] | None:
    for filename in ("VERSION", "version.txt", ".version"):
        path = root / filename
        if not path.is_file():
            continue
        try:
            raw = next((line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()), "")
        except OSError:
            continue
        result = _version_source(raw, "version_file", path)
        if result:
            return result
    return None


def _configured_package_version(config: dict[str, Any]) -> Any:
    for key in ("package_version", "release_version", "plan_version"):
        if config.get(key):
            return config[key]
    version = config.get("version")
    if isinstance(version, dict):
        for key in ("override", "package_version", "value"):
            if version.get(key):
                return version[key]
    return None


def resolve_package_version(
    root: Path,
    config: dict[str, Any],
    override: str | None = None,
) -> dict[str, Any]:
    """Resolve the target release version with transparent source evidence."""
    if override:
        return _version_source(override, "cli") or {"value": DEFAULT_PACKAGE_VERSION, "source": "fallback"}
    configured = _configured_package_version(config)
    if configured:
        return _version_source(configured, "config") or {"value": DEFAULT_PACKAGE_VERSION, "source": "fallback"}
    for resolver in (_maven_version, _python_version, _node_version, _gradle_version, _version_file):
        result = resolver(root)
        if result:
            return result
    return {"value": DEFAULT_PACKAGE_VERSION, "source": "fallback"}


def normalize_storage(value: Any = None) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {"directory": value} if value else {}
    directory = str(raw.get("directory") or DEFAULT_STORAGE["directory"]).strip()
    return {
        "directory": directory or DEFAULT_STORAGE["directory"],
        "versioned": bool(raw.get("versioned", DEFAULT_STORAGE["versioned"])),
        "manifest_filename": safe_filename(raw.get("manifest_filename"), DEFAULT_STORAGE["manifest_filename"]),
        "archive_filename": safe_filename(raw.get("archive_filename"), DEFAULT_STORAGE["archive_filename"]),
    }


def safe_filename(value: Any, fallback: str) -> str:
    name = Path(str(value or fallback)).name
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip(".")
    return name or fallback


def version_bucket(value: Any) -> str:
    raw = normalize_package_version(value)
    raw = re.sub(r"[^A-Za-z0-9._-]+", "-", raw).strip(".")
    if not raw or raw in {"-", ".."}:
        raw = DEFAULT_PACKAGE_VERSION
    return raw


def storage_paths(root: Path, storage: dict[str, Any], version: str) -> tuple[Path, Path]:
    directory = Path(str(storage.get("directory") or DEFAULT_STORAGE["directory"])).expanduser()
    base = directory if directory.is_absolute() else root / directory
    bucket = base / version_bucket(version) if storage.get("versioned", True) else base
    return (
        bucket / safe_filename(storage.get("manifest_filename"), DEFAULT_STORAGE["manifest_filename"]),
        bucket / safe_filename(storage.get("archive_filename"), DEFAULT_STORAGE["archive_filename"]),
    )


def _display_path(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def storage_metadata(root: Path, storage: dict[str, Any], version: str) -> dict[str, Any]:
    manifest_path, archive_path = storage_paths(root, storage, version)
    return {
        **normalize_storage(storage),
        "version": normalize_package_version(version),
        "version_directory": _display_path(root, manifest_path.parent),
        "manifest_path": _display_path(root, manifest_path),
        "archive_path": _display_path(root, archive_path),
    }
