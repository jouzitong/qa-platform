#!/usr/bin/env python3
"""Create a conservative qa-platform import manifest from a source tree.

The scanner intentionally uses only the Python standard library. It combines
local OpenAPI JSON, common backend route declarations, and frontend route
objects. It is an inventory/bootstrap tool, not a runtime crawler.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from copy import deepcopy
from datetime import datetime, timezone
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

from api_grouping import group_path_from_segments, normalize_group_path
from flow_documents import load_flow_documents
from module_bundle import ModuleBundleError, load_import_source, write_module_bundle
from parameter_protocol import (
    add_parameters,
    add_path_parameters,
    normalize_openapi_parameter,
    parameter_from_schema,
    parameters_from_object_schema,
)
from project_config import (
    load_project_config,
    normalize_api_grouping,
    normalize_api_templates,
    normalize_api_template_discovery,
    normalize_flow_documents,
    normalize_openapi_config,
    normalize_package_version,
    normalize_project_metadata,
    normalize_project_variables,
    normalize_service_topology,
    normalize_success_assertions,
    normalize_storage,
    resolve_language,
    resolve_package_version,
    storage_metadata,
    storage_paths,
)
from success_assertions import build_success_assertion_assets, discover_success_code_values

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
    "releases",
    "__pycache__",
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
}
BUILD_METADATA_NAMES = {"pom.xml", "build.gradle", "build.gradle.kts", "go.mod", "package.json"}
ARCHITECTURE_SUFFIXES = {".properties"}
HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE"}
JAVA_TYPE_MARKER = "x-qa-platform-java-type"
API_DISPLAY_NAME_MAX_LENGTH = 120
SPRING_APPLICATION_CONFIG_RE = re.compile(
    r"^(?:application|bootstrap)(?:[-.][A-Za-z0-9_.-]+)?\.(?:properties|ya?ml|json)$",
    re.IGNORECASE,
)
SPRING_PREFIX_KEYS = {
    "server.servlet.contextpath",
    "server.contextpath",
    "spring.mvc.servlet.path",
    "spring.webflux.basepath",
}
SPRING_PREFIX_KEY_ORDER = {
    "server.contextpath": 0,
    "server.servlet.contextpath": 0,
    "spring.mvc.servlet.path": 1,
    "spring.webflux.basepath": 1,
}
SPRING_PREFIX_GROUPS = (
    (
        "context",
        {"server.servlet.contextpath": 0, "server.contextpath": 1},
    ),
    (
        "dispatcher",
        {"spring.mvc.servlet.path": 0, "spring.webflux.basepath": 1},
    ),
)
ROUTE_RE = re.compile(
    r"@(?P<object>[A-Za-z_][\w.]*)\.(?P<method>get|post|put|patch|delete|head|options|trace|route|api_route|websocket)\s*\((?P<args>[^\n)]*)\)",
    re.IGNORECASE,
)
SPRING_RE = re.compile(
    r"@(?P<annotation>GetMapping|PostMapping|PutMapping|PatchMapping|DeleteMapping|RequestMapping|MessageMapping)\s*(?:\((?P<args>[^\n)]*)\))?",
)
NODE_RE = re.compile(
    r"\b(?P<object>[A-Za-z_$][\w$]*)\.(?P<method>get|post|put|patch|delete|head|options|trace|all)\s*\(\s*['\"](?P<path>[^'\"]+)",
    re.IGNORECASE,
)
GO_RE = re.compile(
    r"\b(?P<object>[A-Za-z_][\w.]*)\.(?P<method>GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS|Any|Handle)\s*\(\s*['\"](?P<path>[^'\"]+)",
)
NODE_WS_RE = re.compile(
    r"\b(?P<object>app|router|server|wss|ws)\.(?:ws|handleUpgrade|on)\s*\(\s*['\"](?P<path>[^'\"]+)",
    re.IGNORECASE,
)
JAVA_WS_RE = re.compile(
    r"@(?:ServerEndpoint|Endpoint)\s*\(\s*['\"](?P<path>[^'\"]+)",
)
SPRING_WS_CONFIG_RE = re.compile(
    r"\b(?:EnableWebSocket|WebSocketConfigurer|WebSocketHandlerRegistry)\b"
)
SPRING_WS_HANDLER_RE = re.compile(
    r"\b[A-Za-z_$][\w$]*\.addHandler\s*\(\s*[^,\n]+\s*,\s*"
    r"(?P<paths>(?:['\"][^'\"]+['\"]\s*,?\s*)+)\)"
)
FRONTEND_ROUTE_RE = re.compile(r"\bpath\s*:\s*['\"](?P<path>[^'\"]+)['\"]")
LITERAL_RE = re.compile(
    r"(?P<quote>['\"])(?P<value>(?:\\.|(?!(?P=quote)).)*)(?P=quote)"
)
METHOD_LIST_RE = re.compile(r"methods\s*=\s*\[([^]]+)\]", re.IGNORECASE)
GATEWAY_MARKERS = (
    "spring.cloud.gateway",
    "spring-cloud-starter-gateway",
    "zuul.routes",
    "spring-cloud-starter-netflix-zuul",
    "gateway.routes",
    "proxy_pass",
    "traefik",
    "kong",
    "envoy",
)
SERVICE_DISCOVERY_MARKERS = ("eureka", "nacos", "consul", "spring-cloud-starter")
GATEWAY_URL_RE = re.compile(
    r"(?im)^\s*(?P<key>api[_-]?gateway[_-]?(?:url|address)?|gateway[_-]?(?:url|address)|api[_-]?base[_-]?url|vite_api_base_url|base_url)\s*[:=]\s*[\"']?(?P<url>https?://[^\"'\s,}]+)"
)
SERVER_PORT_RE = re.compile(r"(?im)^\s*(?:server\.port|port)\s*[:=]\s*(?P<port>\d{2,5})\b")
DEFAULT_API_DOCUMENT_NAMES = {
    "openapi.json",
    "openapi.yaml",
    "openapi.yml",
    "swagger.json",
    "swagger.yaml",
    "swagger.yml",
    "asyncapi.json",
    "asyncapi.yaml",
    "asyncapi.yml",
}
DISCOVERY_PRIORITIES = {
    "inferred": 0,
    "source": 1,
    "documentation": 2,
    "swagger": 3,
    "openapi": 3,
    "asyncapi": 3,
}
JAVA_TYPE_DECL_RE = re.compile(
    r"\b(?P<kind>class|record|enum)\s+(?P<name>[A-Za-z_$][\w$]*)\b"
)
JAVA_METHOD_DECL_RE = re.compile(
    r"(?m)^\s*(?:(?:public|protected|private|static|final|default|abstract|synchronized)\s+)*"
    r"(?:<[^>]+>\s+)?(?P<return_type>[A-Za-z_$][\w$.$<>, ?\[\]&]*)\s+"
    r"(?P<name>[A-Za-z_$][\w$]*)\s*\("
)
JAVA_REQUIRED_ANNOTATION_RE = re.compile(r"@(?:[\w$.]+\.)?(?:NotNull|NotBlank|NotEmpty|NonNull)\b")
JAVA_MULTIPART_TYPE_RE = re.compile(r"\b(?:MultipartFile|Part|FilePart)\b")
JAVA_RESPONSE_UNWRAP_TYPES = {
    "completionstage",
    "completablefuture",
    "future",
    "httpentity",
    "optional",
    "responseentity",
}
JAVA_RESPONSE_ENVELOPE_TYPES = {
    "apiresponse",
    "baseresponse",
    "commonresponse",
    "r",
    "result",
}
TEMPLATE_SAFE_HEADER_NAMES = {
    "accept",
    "content-type",
    "x-frontend-environment",
    "x-trace-id",
}
TEMPLATE_AUTH_HEADER_NAMES = {
    "authorization",
    "proxy-authorization",
}


def join_route(prefix: str | None, route: str) -> str:
    """Join literal framework prefixes without changing absolute URLs."""
    route = route.strip()
    prefix = (prefix or "").strip()
    if not prefix or route.startswith(("ws://", "wss://", "http://", "https://")):
        return route
    if not route.startswith("/"):
        route = "/" + route
    if prefix == "/":
        return route
    return "/" + prefix.strip("/") + "/" + route.lstrip("/")


def route_prefixes(text: str) -> dict[str, str]:
    """Find common local router/group prefixes used by Node, Go, and Python."""
    prefixes: dict[str, str] = {}
    declaration = re.compile(
        r"\b(?P<object>[A-Za-z_][\w.]*)\s*=\s*(?:APIRouter|Blueprint|Router|Group)\s*\((?P<args>[^)]*)\)",
        re.IGNORECASE | re.DOTALL,
    )
    for match in declaration.finditer(text):
        prefix_match = re.search(r"(?:prefix|url_prefix)\s*=\s*['\"]([^'\"]+)", match.group("args"), re.IGNORECASE)
        if prefix_match:
            prefixes[match.group("object")] = prefix_match.group(1)

    go_group = re.compile(
        r"\b(?P<object>[A-Za-z_][\w]*)\s*(?::=|=)\s*(?P<parent>[A-Za-z_][\w]*)\.Group\s*\(\s*['\"](?P<prefix>[^'\"]+)"
    )
    for match in go_group.finditer(text):
        prefixes[match.group("object")] = join_route(prefixes.get(match.group("parent")), match.group("prefix"))

    node_use = re.compile(
        r"\b[A-Za-z_$][\w$]*\.use\s*\(\s*['\"](?P<prefix>[^'\"]+)['\"]\s*,\s*(?P<object>[A-Za-z_$][\w$]*)"
    )
    for match in node_use.finditer(text):
        prefixes[match.group("object")] = match.group("prefix")
    return prefixes


def _normalized_config_key(value: str) -> str:
    """Normalize Spring relaxed-binding key spellings for static matching."""
    value = value.strip().strip("'\"").replace("_", "").replace("-", "")
    return re.sub(r"\.+", ".", value).strip(".").lower()


def _strip_config_comment(value: str) -> str:
    quote: str | None = None
    escaped = False
    for index, char in enumerate(value):
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in {"'", '"'}:
            quote = char
        elif char == "#" and (index == 0 or value[index - 1].isspace()):
            return value[:index].rstrip()
    return value.strip()


def _config_literal(value: Any) -> str:
    """Return a scalar configuration value without YAML/Properties quoting."""
    cleaned = _strip_config_comment(str(value or "")).strip()
    if len(cleaned) >= 2 and cleaned[0] in {"'", '"'} and cleaned[-1] == cleaned[0]:
        cleaned = cleaned[1:-1]
    return cleaned.strip()


def _simple_config_entries(path: Path) -> list[dict[str, Any]]:
    """Read literal scalar/list values from common Spring config formats.

    This deliberately understands only the small subset needed for safe
    reusable-template discovery. It does not evaluate placeholders, profile
    expressions, or arbitrary YAML objects.
    """
    entries: list[dict[str, Any]] = []

    def add(key: str, value: Any, line: int) -> None:
        normalized = _normalized_config_key(key)
        literal = _config_literal(value)
        if normalized and literal:
            entries.append({"key": normalized, "value": literal, "line": line})

    suffix = path.suffix.lower()
    text = read_text(path)
    if suffix == ".properties":
        for line_number, raw_line in enumerate(text.splitlines(), 1):
            line = raw_line.strip()
            if not line or line.startswith(("#", "!")):
                continue
            match = re.match(r"(?P<key>[^:=\s]+)\s*(?:=|:)\s*(?P<value>.*)$", line)
            if match:
                add(match.group("key"), match.group("value"), line_number)
        return entries

    if suffix == ".json":
        try:
            document = json.loads(text)
        except (OSError, json.JSONDecodeError):
            return entries

        def visit(value: Any, prefix: tuple[str, ...] = ()) -> None:
            if isinstance(value, dict):
                for key, child in value.items():
                    visit(child, (*prefix, str(key)))
                return
            if isinstance(value, list):
                for child in value:
                    visit(child, prefix)
                return
            if prefix:
                add(".".join(prefix), value, 1)

        visit(document)
        return entries

    stack: list[tuple[int, str]] = []
    for line_number, raw_line in enumerate(text.splitlines(), 1):
        expanded = raw_line.expandtabs(2)
        stripped = expanded.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("---"):
            if stripped == "---":
                stack.clear()
            continue
        indent = len(expanded) - len(expanded.lstrip(" "))
        if stripped.startswith("-"):
            while stack and indent < stack[-1][0]:
                stack.pop()
            value = stripped[1:].strip()
            if stack:
                add(".".join(item[1] for item in stack), value, line_number)
            continue
        match = re.match(r"(?P<key>[^:]+):(?P<value>.*)$", stripped)
        if not match:
            continue
        while stack and indent <= stack[-1][0]:
            stack.pop()
        key = match.group("key").strip().strip("'\"")
        raw_value = match.group("value").strip()
        full_key = ".".join((*[item[1] for item in stack], key))
        if raw_value and raw_value not in {"|", ">"}:
            add(full_key, raw_value, line_number)
        else:
            stack.append((indent, key))
    return entries


def _normalize_spring_prefix(value: str) -> str | None:
    value = _strip_config_comment(value).strip().strip("'\"")
    if not value or value.lower() in {"null", "none", "~"}:
        return None
    if value.startswith("${") or value.startswith("#{"):
        return None
    if value.startswith(("http://", "https://", "ws://", "wss://")):
        return None
    if not value.startswith("/"):
        value = "/" + value
    return value.rstrip("/") or "/"


def _config_scope_root(path: Path, root: Path) -> Path:
    """Map a Spring config file to the module whose routes it configures."""
    relative = path.relative_to(root)
    parts = relative.parts
    for index in range(len(parts) - 2):
        if tuple(part.lower() for part in parts[index : index + 3]) == (
            "src",
            "main",
            "resources",
        ):
            return root / Path(*parts[:index]) if index else root

    for ancestor in (path.parent, *path.parent.parents):
        if ancestor == root.parent:
            break
        if any((ancestor / name).is_file() for name in BUILD_METADATA_NAMES) or (
            ancestor / "src"
        ).is_dir():
            return ancestor
    return root if path.parent == root else path.parent


def _application_config_priority(path: Path) -> int:
    stem = path.stem.lower()
    if stem == "application":
        return 0
    if stem == "bootstrap":
        return 1
    if stem.startswith("application"):
        return 2
    return 3


def _application_config_values(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Extract literal Spring application prefixes without requiring PyYAML."""
    values: list[dict[str, Any]] = []
    unresolved: list[str] = []

    def add_value(key: str, raw_value: str, line: int) -> None:
        normalized_key = _normalized_config_key(key)
        if normalized_key not in SPRING_PREFIX_KEYS:
            return
        prefix = _normalize_spring_prefix(raw_value)
        if prefix is None:
            cleaned = _strip_config_comment(raw_value).strip()
            if cleaned and cleaned.lower() not in {"null", "none", "~"}:
                unresolved.append(f"{path.name}:{line}:{key}={cleaned}")
            return
        values.append(
            {
                "key": normalized_key,
                "value": prefix,
                "line": line,
            }
        )

    suffix = path.suffix.lower()
    if suffix == ".properties":
        for line_number, raw_line in enumerate(read_text(path).splitlines(), 1):
            line = raw_line.strip()
            if not line or line.startswith(("#", "!")):
                continue
            match = re.match(r"(?P<key>[^:=\s]+)\s*(?:=|:)\s*(?P<value>.*)$", line)
            if match:
                add_value(match.group("key"), match.group("value"), line_number)
        return values, unresolved

    if suffix == ".json":
        try:
            document = json.loads(read_text(path))
        except (OSError, json.JSONDecodeError):
            return values, unresolved

        def visit(value: Any, prefix: tuple[str, ...] = ()) -> None:
            if not isinstance(value, dict):
                return
            for key, child in value.items():
                full_key = ".".join((*prefix, str(key)))
                if _normalized_config_key(full_key) in SPRING_PREFIX_KEYS and isinstance(
                    child, (str, int, float)
                ):
                    add_value(full_key, str(child), 1)
                visit(child, (*prefix, str(key)))

        visit(document)
        return values, unresolved

    stack: list[tuple[int, str]] = []
    for line_number, raw_line in enumerate(read_text(path).splitlines(), 1):
        if raw_line.strip() == "---":
            stack.clear()
            continue
        expanded = raw_line.expandtabs(2)
        stripped = expanded.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("-"):
            continue
        match = re.match(r"(?P<key>[^:]+):(?P<value>.*)$", stripped)
        if not match:
            continue
        indent = len(expanded) - len(expanded.lstrip(" "))
        while stack and indent <= stack[-1][0]:
            stack.pop()
        key = match.group("key").strip().strip("'\"")
        raw_value = match.group("value").strip()
        full_key = ".".join((*[item[1] for item in stack], key))
        if _normalized_config_key(full_key) in SPRING_PREFIX_KEYS:
            if raw_value:
                add_value(full_key, raw_value, line_number)
            else:
                unresolved.append(f"{path.name}:{line_number}:{full_key}=<empty>")
        if not raw_value or raw_value in {"|", ">"}:
            stack.append((indent, key))
    return values, unresolved


def _effective_spring_prefix_values(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Select one context key and one dispatcher key before composing a prefix."""
    selected: list[dict[str, Any]] = []
    for _group_name, keys in SPRING_PREFIX_GROUPS:
        candidates = [value for value in values if value["key"] in keys]
        if candidates:
            selected.append(
                min(candidates, key=lambda value: (keys[value["key"]], value["line"]))
            )
    return sorted(selected, key=lambda item: (SPRING_PREFIX_KEY_ORDER[item["key"]], item["line"]))


def discover_spring_context_paths(
    root: Path, files: list[Path]
) -> tuple[list[dict[str, Any]], list[str]]:
    """Find Spring application prefixes and retain their module scope/evidence."""
    candidates: list[dict[str, Any]] = []
    warnings: list[str] = []
    for path in files:
        if not SPRING_APPLICATION_CONFIG_RE.match(path.name):
            continue
        values, unresolved = _application_config_values(path)
        for value in unresolved:
            warnings.append(f"Spring 应用前缀无法静态解析: {value}")
        if not values:
            continue
        prefix = ""
        ordered_values = _effective_spring_prefix_values(values)
        for value in ordered_values:
            prefix = join_route(prefix, value["value"])
        candidates.append(
            {
                "scope": _config_scope_root(path, root),
                "path": path,
                "prefix": prefix,
                "priority": _application_config_priority(path),
                "source_refs": [
                    {
                        "file": path.relative_to(root).as_posix(),
                        "line": value["line"],
                    }
                    for value in ordered_values
                ],
            }
        )
    return candidates, warnings


def resolve_spring_context_path(
    path: Path, candidates: list[dict[str, Any]]
) -> tuple[str | None, list[dict[str, Any]], list[str]]:
    """Resolve the nearest module config, warning when candidates disagree."""
    matches = [candidate for candidate in candidates if _is_relative_to(path, candidate["scope"])]
    if not matches:
        return None, [], []
    deepest_scope = max(len(candidate["scope"].parts) for candidate in matches)
    matches = [candidate for candidate in matches if len(candidate["scope"].parts) == deepest_scope]
    values = sorted({str(candidate["prefix"]) for candidate in matches})
    selected = sorted(matches, key=lambda item: (item["priority"], str(item["path"])))[0]
    warnings: list[str] = []
    if len(values) > 1:
        locations = ", ".join(
            f"{candidate['path'].name}={candidate['prefix']}" for candidate in matches
        )
        warnings.append(
            f"Spring 应用前缀存在多个静态候选，已使用 {selected['path'].name}={selected['prefix']}：{locations}"
        )
    return selected["prefix"], selected["source_refs"], warnings


def resolve_configured_service(
    path: Path,
    root: Path,
    service_topology: dict[str, Any],
) -> tuple[dict[str, Any] | None, list[str]]:
    """Map a source file to the most specific configured service source root."""
    try:
        relative = path.relative_to(root)
    except ValueError:
        return None, []
    matches: list[tuple[int, dict[str, Any], str]] = []
    for service in service_topology.get("services", []):
        if not isinstance(service, dict):
            continue
        for raw_source_root in service.get("source_roots", []):
            source_root = Path(str(raw_source_root))
            if source_root == Path(".") or _is_relative_to(relative, source_root):
                matches.append((len(source_root.parts), service, source_root.as_posix()))
    if not matches:
        return None, []
    deepest = max(match[0] for match in matches)
    selected_matches = [match for match in matches if match[0] == deepest]
    selected_matches.sort(key=lambda match: (str(match[1].get("key") or ""), match[2]))
    selected = selected_matches[0][1]
    warnings: list[str] = []
    service_keys = sorted({str(match[1].get("key") or "") for match in selected_matches})
    if len(service_keys) > 1:
        warnings.append(
            f"Source {relative.as_posix()} matched multiple service_topology entries "
            f"at the same depth; selected {selected.get('key')}: {', '.join(service_keys)}"
        )
    return selected, warnings


def configured_service_context_path(
    service: dict[str, Any] | None,
    discovered_prefix: str | None,
    discovered_refs: list[dict[str, Any]],
) -> tuple[str | None, list[dict[str, Any]], list[str]]:
    """Prefer project-owned external route facts over module-local inference."""
    configured_prefix = str((service or {}).get("route_prefix") or "").strip()
    if not configured_prefix:
        return discovered_prefix, discovered_refs, []
    warnings: list[str] = []
    if discovered_prefix and discovered_prefix != configured_prefix:
        warnings.append(
            f"Service {service.get('key')} route_prefix={configured_prefix} overrides "
            f"the statically discovered Spring prefix {discovered_prefix}"
        )
    return configured_prefix, discovered_refs if discovered_prefix == configured_prefix else [], warnings


def discover_router_prefixes(files: list[Path]) -> dict[str, str]:
    """Resolve simple FastAPI include_router aliases across files."""
    imported_modules: dict[str, str] = {}
    includes: list[tuple[str, str, str]] = []
    import_re = re.compile(
        r"^\s*from\s+[A-Za-z_][\w.]*\.(?P<module>[A-Za-z_][\w]*)\s+import\s+(?P<items>[^\n]+)",
        re.MULTILINE,
    )
    include_re = re.compile(r"\binclude_router\s*\((?P<args>[^\n)]*)\)")
    for path in files:
        text = read_text(path)
        for match in import_re.finditer(text):
            module = match.group("module")
            for raw_item in match.group("items").split(","):
                parts = raw_item.strip().split()
                if not parts:
                    continue
                source_name = parts[0]
                alias = parts[2] if len(parts) >= 3 and parts[1].lower() == "as" else source_name
                if "router" in source_name.lower() or "router" in alias.lower():
                    imported_modules[alias] = f"{module}.{source_name}"
        for match in include_re.finditer(text):
            args = match.group("args")
            target_match = re.match(r"\s*(?P<target>[A-Za-z_][\w.]*)", args)
            prefix_match = re.search(r"\bprefix\s*=\s*['\"](?P<prefix>[^'\"]+)", args)
            if target_match and prefix_match:
                includes.append(
                    (target_match.group("target"), prefix_match.group("prefix"), path.stem)
                )

    prefixes: dict[str, str] = {}
    for target, prefix, _source_module in includes:
        imported = imported_modules.get(target)
        if imported:
            prefixes[imported] = prefix
            continue
        if "." in target:
            prefixes[target] = prefix
            continue
        if target.endswith("_router"):
            prefixes[f"{target.removesuffix('_router')}.router"] = prefix
        else:
            prefixes[target] = prefix
    return prefixes


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", default=".", help="Project root to scan")
    parser.add_argument(
        "--output",
        default=None,
        help="Manifest path; defaults to <storage.directory>/<version>/qa-platform-import.json",
    )
    parser.add_argument(
        "--modules-dir",
        default=None,
        help="Editable module bundle directory; defaults to the version bucket",
    )
    parser.add_argument("--config", default=None, help="Project-local qa-platform config path")
    parser.add_argument("--language", default=None, help="Override generated asset language, for example zh-CN")
    parser.add_argument("--storage-dir", default=None, help="Override configured scan artifact directory")
    parser.add_argument("--project-key", default=None)
    parser.add_argument("--project-name", default=None)
    parser.add_argument(
        "--plan-version",
        "--package-version",
        dest="plan_version",
        default=None,
        help="Override the detected project release version written to generated test plans",
    )
    parser.add_argument(
        "--previous-manifest",
        default=None,
        help="Previous module bundle directory/index or aggregate used for version decisions",
    )
    parser.add_argument(
        "--openapi",
        action="append",
        default=[],
        help="Additional local OpenAPI JSON/YAML document; may be repeated",
    )
    parser.add_argument(
        "--openapi-url",
        action="append",
        default=[],
        help="Explicit runtime OpenAPI/Swagger URL; may be repeated",
    )
    return parser.parse_args()


def slug(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return value or "project"


def business_tokens(value: str) -> list[str]:
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(value or ""))
    return [token.lower() for token in re.findall(r"[A-Za-z0-9]+", value)]


def business_key_from_value(value: str) -> str:
    tokens = business_tokens(value)
    verbs = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}
    if len(tokens) > 1 and tokens[0] in verbs:
        tokens = tokens[1:]
    return ".".join(tokens)


def business_key_from_path(path: str) -> str:
    parsed = urlsplit(path)
    path_value = parsed.path if parsed.scheme or parsed.netloc else path.split("?", 1)[0]
    ignored = {"api", "apis", "v1", "v2", "v3", "v4", "version"}
    segments: list[str] = []
    for raw_segment in path_value.split("/"):
        segment = raw_segment.strip().strip("{}")
        segment = segment.removeprefix(":")
        if not segment or segment.lower() in ignored:
            continue
        tokens = business_tokens(segment)
        if tokens:
            segments.extend(tokens)
    if len(segments) > 4:
        segments = [*segments[:3], segments[-1]]
    return ".".join(segments)


def derive_business_key(
    protocol: str,
    method: str | None,
    path: str,
    name: str | None = None,
    operation_id: str | None = None,
) -> str:
    candidate = business_key_from_value(operation_id or "")
    if not candidate:
        candidate = business_key_from_path(path)
    if not candidate:
        candidate = business_key_from_value(name or "")
    if not candidate:
        candidate = f"{protocol}.{(method or 'message').lower()}"
    return candidate


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def source_ref(path: Path, root: Path, line: int) -> dict[str, Any]:
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError:
        relative = path.name
    return {"file": relative, "line": line}


def service_from_source_ref(root: Path, ref: dict[str, Any]) -> str:
    """Resolve the owning microservice from the conventional app module path."""
    parts = Path(str(ref.get("file") or "")).parts
    if len(parts) >= 2 and parts[0] == "app" and parts[1].startswith("app-"):
        return parts[1]
    return root.name


def add_ref(item: dict[str, Any], ref: dict[str, Any]) -> None:
    refs = item.setdefault("source_refs", [])
    if ref not in refs:
        refs.append(ref)


def interface_key(protocol: str, method: str | None, path: str) -> str:
    if protocol == "http":
        return f"http:{method or 'GET'}:{path}"
    return f"ws:{path}"


def ensure_interface(
    interfaces: dict[str, dict[str, dict[str, Any]]],
    protocol: str,
    path: str,
    root: Path,
    ref: dict[str, Any],
    method: str | None = None,
    name: str | None = None,
    description: str | None = None,
    operation_id: str | None = None,
    business_key: str | None = None,
    discovery_method: str = "source",
    confidence: float = 0.85,
    language: str | None = "en",
    service_key: str | None = None,
) -> dict[str, Any] | None:
    path = path.strip()
    if not path or not path.startswith(("/", "ws://", "wss://", "http://", "https://")):
        return None
    method = method.upper() if method else None
    key_path = path
    route_key = interface_key(protocol, method, key_path)
    bucket = interfaces[protocol]
    item = bucket.get(route_key)
    source_service = str(service_key or service_from_source_ref(root, ref)).strip() or root.name
    if item is None:
        candidate_business_key = business_key or derive_business_key(
            protocol, method, key_path, name=name, operation_id=operation_id
        )
        normalized_name = str(name or "").strip()
        item = {
            # The public API contract uses the route identity as the only
            # external key.  Keep the business grouping hint private so
            # feature localization can still use operation/path semantics.
            "key": route_key,
            "_business_key": candidate_business_key,
            "protocol": protocol,
            "name": normalized_name or (f"{method} {path}" if method else path),
            "_name_source": "source" if normalized_name else "fallback",
            "_name_priority": DISCOVERY_PRIORITIES.get(discovery_method, 1)
            if normalized_name
            else -1,
            "description": str(description or "").strip(),
            "_description_priority": DISCOVERY_PRIORITIES.get(discovery_method, 1)
            if str(description or "").strip()
            else -1,
            "service": source_service,
            "parameters": [],
            "request_schema": {},
            "response_schema": {},
            "response_unpack": {},
            "auth": "unknown",
            "tags": [],
            "source_refs": [],
            "discovery_method": discovery_method,
            "confidence": confidence,
            "warnings": [],
        }
        if protocol == "http":
            item.update({"method": method or "GET", "path": key_path})
        else:
            item.update({"url": key_path, "messages": []})
        bucket[route_key] = item
    elif business_key:
        # A later, higher-signal source may improve feature grouping, but it
        # must not change the stable route key.
        item["_business_key"] = business_key
    current_service = str(item.get("service") or root.name)
    if current_service == root.name and source_service != root.name:
        item["service"] = source_service
    elif source_service != root.name and current_service != source_service:
        warning = (
            f"Route is declared by multiple service modules: {current_service}, {source_service}"
        )
        if warning not in item["warnings"]:
            item["warnings"].append(warning)
    add_ref(item, ref)
    item["confidence"] = max(float(item.get("confidence", 0)), confidence)
    incoming_priority = DISCOVERY_PRIORITIES.get(discovery_method, 1)
    current_priority = DISCOVERY_PRIORITIES.get(str(item.get("discovery_method")), 1)
    if incoming_priority > current_priority:
        item["discovery_method"] = discovery_method
    normalized_name = str(name or "").strip()
    if normalized_name and incoming_priority >= int(item.get("_name_priority", -1)):
        item["name"] = normalized_name
        item["_name_source"] = "source"
        item["_name_priority"] = incoming_priority
    normalized_description = str(description or "").strip()
    if normalized_description and incoming_priority >= int(
        item.get("_description_priority", -1)
    ):
        item["description"] = normalized_description
        item["_description_priority"] = incoming_priority
    # Every scanner source shares route placeholders.  Seed them here so a
    # framework route without richer metadata is still executable after a
    # reviewer supplies a value; richer OpenAPI/Spring facts merge below.
    add_path_parameters(item, key_path, language=language)
    return item


def first_literal(args: str) -> str | None:
    match = LITERAL_RE.search(args)
    return match.group("value") if match else None


JAVA_DOC_RE = re.compile(r"/\*\*(?P<body>[\s\S]*?)\*/")
JAVA_DOC_LINK_RE = re.compile(r"\{@(?:link|code|value)\s+([^}\s]+)(?:\s+[^}]*)?\}")
JAVA_DOC_HTML_RE = re.compile(r"<[^>]+>")


def _clean_java_doc_text(
    value: str, *, trim_terminal_punctuation: bool = True
) -> str:
    value = JAVA_DOC_LINK_RE.sub(r"\1", value)
    value = JAVA_DOC_HTML_RE.sub(" ", value)
    value = " ".join(value.split()).strip()
    if trim_terminal_punctuation:
        value = value.rstrip("。！？.!?").strip()
    return value


def _java_doc_summary(value: str) -> str:
    """Extract the first human-facing sentence from a nearby JavaDoc block."""
    text = _java_doc_description(value)
    if not text:
        return ""
    sentence = re.split(r"(?<=[。！？.!?])\s*", text, maxsplit=1)[0]
    return sentence.strip().rstrip("。！？.!?").strip()


def _java_doc_description(value: str) -> str:
    """Extract human-facing JavaDoc prose while excluding structured tags."""
    lines: list[str] = []
    for raw_line in value.splitlines():
        line = re.sub(r"^\s*\*?\s?", "", raw_line).strip()
        if not line or line.startswith("@"):
            if lines and line.startswith("@"):
                break
            continue
        # Keep sentence punctuation until after sentence splitting. Removing it
        # here would merge a short summary line with every following JavaDoc
        # line and turn the whole paragraph into an API display name.
        line = _clean_java_doc_text(line, trim_terminal_punctuation=False)
        if line:
            lines.append(line)
    return " ".join(lines).strip()


def _java_doc_block_before(text: str, position: int) -> str:
    """Return the full nearby JavaDoc body, including structured tags."""
    start = max(0, position - 8_000)
    prefix = text[start:position]
    matches = list(JAVA_DOC_RE.finditer(prefix))
    if not matches:
        return ""
    match = matches[-1]
    gap = prefix[match.end() :]
    if re.search(r"[};]", gap) or gap.count("\n") > 48:
        return ""
    return match.group("body")


def _java_doc_before(text: str, position: int) -> str:
    """Return JavaDoc prose when it belongs to the declaration at position."""
    return _java_doc_description(_java_doc_block_before(text, position))


def _java_doc_param_descriptions(value: str) -> dict[str, str]:
    """Parse JavaDoc ``@param`` descriptions, including continuation lines."""
    result: dict[str, str] = {}
    active_name: str | None = None
    active_lines: list[str] = []

    def flush() -> None:
        nonlocal active_name, active_lines
        if active_name:
            description = _clean_java_doc_text(" ".join(active_lines))
            if description:
                result[active_name] = description
        active_name = None
        active_lines = []

    for raw_line in value.splitlines():
        line = re.sub(r"^\s*\*?\s?", "", raw_line).strip()
        match = re.match(r"@param\s+(?P<name><[^>]+>|[A-Za-z_$][\w$]*)\s*(?P<body>.*)", line)
        if match:
            flush()
            name = match.group("name")
            if not name.startswith("<"):
                active_name = name
                active_lines = [match.group("body")]
            continue
        if line.startswith("@"):
            flush()
            continue
        if active_name and line:
            active_lines.append(line)
    flush()
    return result


def _java_identifier_label(value: str, language: str | None) -> str:
    """Turn a Java type/method identifier into a conservative display fallback."""
    tokens = business_tokens(value)
    ignored = {
        "api",
        "controller",
        "service",
        "impl",
        "implementation",
        "internal",
        "external",
        "i",
        "configuration",
        "web",
        "socket",
        "handler",
        "handlers",
    }
    tokens = [token for token in tokens if token not in ignored]
    if not tokens:
        return ""
    if not str(language or "").lower().startswith("zh"):
        return " ".join(token.capitalize() for token in tokens)
    labels = [ZH_TOKEN_LABELS.get(token, token) for token in tokens]
    if "by" in tokens:
        by_index = tokens.index("by")
        before = labels[:by_index]
        after = labels[by_index + 1 :]
        if before and after:
            return f"按{''.join(after)}{''.join(before)}"
    return "".join(label for token, label in zip(tokens, labels) if token != "by")


def _spring_name_and_description(
    class_summary: str,
    method_summary: str,
    *,
    class_identifier: str = "",
    method_identifier: str = "",
    language: str | None = "en",
) -> tuple[str | None, str | None]:
    class_description = class_summary.strip()
    method_description = method_summary.strip()
    class_name = _java_doc_summary(class_description) or _java_identifier_label(
        class_identifier, language
    )
    method_name = _java_doc_summary(method_description) or _java_identifier_label(
        method_identifier, language
    )
    description_parts = [
        value.rstrip("。！？.!?").strip()
        for value in (class_description, method_description)
        if value.strip()
    ]
    description = "。".join(description_parts)
    if description:
        description += "。"
    if method_name and class_name:
        if method_name == class_name or method_name in class_name:
            return class_name, description or class_name
        if class_name in method_name:
            return method_name, description or method_name
        return f"{class_name} - {method_name}", description or f"{class_name}。{method_name}。"
    if method_name:
        return method_name, description or method_name
    if class_name:
        return class_name, description or class_name
    return None, None


def _bounded_display_name(value: Any, max_length: int = API_DISPLAY_NAME_MAX_LENGTH) -> str:
    """Return a compact UI label that always fits the platform contract."""
    normalized = " ".join(str(value or "").split()).strip()
    if len(normalized) <= max_length:
        return normalized
    if max_length <= 1:
        return normalized[:max_length]
    prefix = normalized[: max_length - 1].rstrip(" -—/:：，,。；;")
    return f"{prefix or normalized[: max_length - 1]}…"


def _display_name_with_suffix(name: str, suffix: str) -> str:
    """Fit a collision suffix without dropping the method/route discriminator."""
    normalized_suffix = " ".join(str(suffix or "").split()).strip()
    if len(normalized_suffix) >= API_DISPLAY_NAME_MAX_LENGTH:
        normalized_suffix = _bounded_display_name(
            normalized_suffix, API_DISPLAY_NAME_MAX_LENGTH // 2
        )
    available = max(1, API_DISPLAY_NAME_MAX_LENGTH - len(normalized_suffix))
    return f"{_bounded_display_name(name, available)}{normalized_suffix}"


def parse_python_routes(
    text: str,
    path: Path,
    root: Path,
    interfaces: dict[str, dict[str, dict[str, Any]]],
    router_prefixes: dict[str, str] | None = None,
    language: str | None = "en",
) -> None:
    if path.suffix.lower() != ".py":
        return
    prefixes = route_prefixes(text)
    router_prefixes = router_prefixes or {}
    for match in ROUTE_RE.finditer(text):
        method_name = match.group("method").lower()
        args = match.group("args")
        route = first_literal(args)
        if not route:
            continue
        object_name = match.group("object")
        external_prefix = router_prefixes.get(f"{path.stem}.{object_name}")
        if external_prefix is None and object_name == "router":
            external_prefix = router_prefixes.get(f"{path.stem}.router")
        route = join_route(external_prefix, join_route(prefixes.get(object_name), route))
        line = text.count("\n", 0, match.start()) + 1
        ref = source_ref(path, root, line)
        if method_name == "websocket":
            ensure_interface(
                interfaces, "ws", route, root, ref, discovery_method="source", language=language
            )
            continue
        methods: list[str]
        if method_name in {"route", "api_route"}:
            methods = [m.upper() for m in re.findall(r"['\"]([A-Za-z]+)['\"]", METHOD_LIST_RE.search(args).group(1))] if METHOD_LIST_RE.search(args) else ["GET"]
        else:
            methods = [method_name.upper()]
        for method in methods:
            if method in HTTP_METHODS:
                ensure_interface(
                    interfaces,
                    "http",
                    route,
                    root,
                    ref,
                    method=method,
                    discovery_method="source",
                    language=language,
                )


def _find_matching_delimiter(
    text: str, start: int, opener: str = "(", closer: str = ")"
) -> int | None:
    """Return the matching delimiter while tolerating strings in declarations."""
    if start < 0 or start >= len(text) or text[start] != opener:
        return None
    depth = 0
    quote: str | None = None
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in {"'", '"'}:
            quote = char
        elif char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return index
    return None


def _split_top_level(value: str, delimiter: str = ",") -> list[str]:
    """Split Java declarations without splitting generic/annotation arguments."""
    result: list[str] = []
    start = 0
    depths = {"(": 0, "[": 0, "{": 0, "<": 0}
    closers = {")": "(", "]": "[", "}": "{", ">": "<"}
    quote: str | None = None
    escaped = False
    for index, char in enumerate(value):
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in {"'", '"'}:
            quote = char
            continue
        if char in depths:
            depths[char] += 1
            continue
        if char in closers:
            opener = closers[char]
            depths[opener] = max(0, depths[opener] - 1)
            continue
        if char == delimiter and not any(depths.values()):
            result.append(value[start:index].strip())
            start = index + 1
    tail = value[start:].strip()
    if tail:
        result.append(tail)
    return result


def _annotation_arguments(value: str, annotation: str) -> str | None:
    pattern = re.compile(rf"@(?:[A-Za-z_$][\w$]*\.)*{re.escape(annotation)}\b")
    match = pattern.search(value)
    if not match:
        return None
    cursor = match.end()
    while cursor < len(value) and value[cursor].isspace():
        cursor += 1
    if cursor >= len(value) or value[cursor] != "(":
        return ""
    end = _find_matching_delimiter(value, cursor)
    return value[cursor + 1 : end] if end is not None else ""


def _java_string_literal(value: str) -> str | None:
    value = value.strip()
    if len(value) < 2 or value[0] not in {"'", '"'} or value[-1] != value[0]:
        return None
    raw = value[1:-1]
    return (
        raw.replace(r"\\n", "\n")
        .replace(r"\\r", "\r")
        .replace(r"\\t", "\t")
        .replace(r'\\"', '"')
        .replace(r"\\'", "'")
        .replace(r"\\\\", "\\")
    )


def _annotation_string(
    value: str, annotation: str, *keys: str, allow_unnamed: bool = True
) -> str | None:
    arguments = _annotation_arguments(value, annotation)
    if arguments is None:
        return None
    for key in keys:
        match = re.search(
            rf"\b{re.escape(key)}\s*=\s*(?P<literal>\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*')",
            arguments,
            re.DOTALL,
        )
        if match:
            return _java_string_literal(match.group("literal"))
    if not allow_unnamed:
        return None
    match = re.match(r"\s*(?P<literal>\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*')", arguments, re.DOTALL)
    return _java_string_literal(match.group("literal")) if match else None


def _annotation_bool(value: str, annotation: str, key: str, fallback: bool) -> bool:
    arguments = _annotation_arguments(value, annotation)
    if arguments is None:
        return fallback
    match = re.search(rf"\b{re.escape(key)}\s*=\s*(true|false)\b", arguments, re.IGNORECASE)
    return match.group(1).lower() == "true" if match else fallback


def _annotation_number(value: str, annotation: str, key: str) -> int | float | None:
    arguments = _annotation_arguments(value, annotation)
    if arguments is None:
        return None
    match = re.search(rf"\b{re.escape(key)}\s*=\s*(-?\d+(?:\.\d+)?)\b", arguments)
    if not match:
        return None
    raw = match.group(1)
    return float(raw) if "." in raw else int(raw)


def _strip_java_annotations(value: str) -> str:
    result: list[str] = []
    index = 0
    while index < len(value):
        if value[index] != "@":
            result.append(value[index])
            index += 1
            continue
        cursor = index + 1
        while cursor < len(value) and (value[cursor].isalnum() or value[cursor] in {"_", "$", "."}):
            cursor += 1
        if cursor == index + 1:
            result.append(value[index])
            index += 1
            continue
        while cursor < len(value) and value[cursor].isspace():
            cursor += 1
        if cursor < len(value) and value[cursor] == "(":
            end = _find_matching_delimiter(value, cursor)
            cursor = end + 1 if end is not None else cursor
        result.append(" ")
        index = cursor
    return "".join(result)


def _strip_java_comments(value: str) -> str:
    """Remove comments from a declaration without changing string literals."""
    value = re.sub(r"/\*[\s\S]*?\*/", " ", value)
    return re.sub(r"//[^\r\n]*", " ", value)


def _java_declaration(value: str) -> tuple[str, str] | None:
    clean = _strip_java_annotations(_strip_java_comments(value)).strip().rstrip(",;")
    clean = re.sub(
        r"\b(?:public|protected|private|static|final|volatile|transient)\b", " ", clean
    )
    clean = clean.split("=", 1)[0].strip()
    match = re.search(r"(?s)(?P<type>.+?)\s+(?P<name>[A-Za-z_$][\w$]*)\s*$", clean)
    if not match:
        return None
    return match.group("type").strip(), match.group("name")


def _java_schema_for_type(type_name: str) -> dict[str, Any]:
    raw = re.sub(r"\s+", "", type_name).removeprefix("?")
    raw = re.sub(r"^(?:extends|super)", "", raw)
    if raw.lower().startswith("optional<") and raw.endswith(">"):
        return _java_schema_for_type(raw[len("Optional<") : -1])
    if raw.endswith("..."):
        return {"type": "array", "items": _java_schema_for_type(raw[:-3])}
    if raw.endswith("[]"):
        return {"type": "array", "items": _java_schema_for_type(raw[:-2])}
    base = raw.split("<", 1)[0]
    simple = base.rsplit(".", 1)[-1].lower()
    if "<" in raw and raw.endswith(">"):
        inner = raw[raw.find("<") + 1 : -1]
        values = _split_top_level(inner)
        if simple in {"list", "set", "collection", "iterable", "stream"}:
            return {"type": "array", "items": _java_schema_for_type(values[0] if values else "Object")}
        if simple in {"map", "hashmap", "linkedhashmap", "multivaluemap"}:
            return {"type": "object"}
    if simple in {"boolean", "bool"}:
        return {"type": "boolean"}
    if simple in {"byte", "short", "int", "integer", "long", "biginteger"}:
        return {"type": "integer"}
    if simple in {"float", "double", "bigdecimal", "decimal"}:
        return {"type": "number"}
    if simple in {
        "string",
        "char",
        "character",
        "uuid",
        "date",
        "localdate",
        "localdatetime",
        "offsetdatetime",
        "instant",
        "enum",
    }:
        return {"type": "string"}
    if simple in {"object", "jsonnode", "jsonobject", "map", "dictionary"}:
        return {"type": "object"}
    # Keep the source DTO name as an internal marker until all Java type
    # declarations have been indexed.  The marker is removed before the
    # schema reaches the import manifest.
    return {"type": "object", JAVA_TYPE_MARKER: raw}


def _java_literal_value(value: str) -> Any | None:
    value = value.strip()
    string = _java_string_literal(value)
    if string is not None:
        return string
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    if re.fullmatch(r"-?\d+\.\d+", value):
        return float(value)
    return None


def _coerce_java_default(value: Any, schema: dict[str, Any]) -> Any:
    if not isinstance(value, str):
        return value
    parameter_type = str(schema.get("type") or "string")
    try:
        if parameter_type == "integer":
            return int(value)
        if parameter_type == "number":
            return float(value)
        if parameter_type == "boolean" and value.lower() in {"true", "false"}:
            return value.lower() == "true"
        if parameter_type in {"object", "array"}:
            return json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        pass
    return value


def _java_validation_message(value: str) -> str:
    """Return an explicit human-authored Bean Validation message when present."""
    for annotation in (
        "NotNull",
        "NotBlank",
        "NotEmpty",
        "Size",
        "Pattern",
        "Min",
        "Max",
        "DecimalMin",
        "DecimalMax",
        "Positive",
        "PositiveOrZero",
        "Negative",
        "NegativeOrZero",
        "Email",
    ):
        message = _annotation_string(value, annotation, "message", allow_unnamed=False)
        if message and not re.fullmatch(r"\{[^{}]+\}", message.strip()):
            return " ".join(message.split())
    return ""


def _java_parameter_metadata(value: str, schema: dict[str, Any]) -> tuple[str, Any | None, Any | None]:
    description = (
        _annotation_string(value, "Schema", "description")
        or _annotation_string(value, "Parameter", "description")
        or _annotation_string(value, "ApiModelProperty", "value", allow_unnamed=False)
        or _annotation_string(value, "ApiModelProperty", "notes", allow_unnamed=False)
        or _annotation_string(value, "JsonPropertyDescription", "value")
        or _java_validation_message(value)
        or ""
    )
    example = _annotation_string(value, "Schema", "example") or _annotation_string(
        value, "Parameter", "example"
    ) or _annotation_string(value, "ApiModelProperty", "example", allow_unnamed=False)
    default = _annotation_string(value, "Schema", "defaultValue", allow_unnamed=False)
    size_min = _annotation_number(value, "Size", "min")
    size_max = _annotation_number(value, "Size", "max")
    if schema.get("type") == "array":
        if size_min is not None:
            schema["minItems"] = size_min
        if size_max is not None:
            schema["maxItems"] = size_max
    elif schema.get("type") == "string":
        if size_min is not None:
            schema["minLength"] = size_min
        if size_max is not None:
            schema["maxLength"] = size_max
    minimum = _annotation_number(value, "Min", "value")
    maximum = _annotation_number(value, "Max", "value")
    if minimum is not None:
        schema["minimum"] = minimum
    if maximum is not None:
        schema["maximum"] = maximum
    pattern = _annotation_string(value, "Pattern", "regexp")
    if pattern:
        schema["pattern"] = pattern
    return description, default, example


def _java_field_required(value: str) -> bool:
    if JAVA_REQUIRED_ANNOTATION_RE.search(value):
        return True
    if _annotation_bool(value, "ApiModelProperty", "required", False):
        return True
    if _annotation_bool(value, "Schema", "required", False):
        return True
    schema_arguments = _annotation_arguments(value, "Schema") or ""
    return bool(re.search(r"\brequiredMode\s*=\s*(?:RequiredMode\.)?REQUIRED\b", schema_arguments))


def _java_direct_statements(value: str) -> list[str]:
    statements: list[str] = []
    start = 0
    depths = {"(": 0, "[": 0, "{": 0, "<": 0}
    closers = {")": "(", "]": "[", "}": "{", ">": "<"}
    quote: str | None = None
    escaped = False
    for index, char in enumerate(value):
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in {"'", '"'}:
            quote = char
            continue
        if char in depths:
            depths[char] += 1
            continue
        if char in closers:
            opener = closers[char]
            depths[opener] = max(0, depths[opener] - 1)
            continue
        if char == ";" and not any(depths.values()):
            statements.append(value[start:index].strip())
            start = index + 1
    return statements


def _java_field_schema(
    value: str, language: str | None = "en"
) -> tuple[str, dict[str, Any], bool] | None:
    if not value or re.search(r"\bstatic\b", _strip_java_annotations(value)):
        return None
    if _annotation_arguments(value, "JsonIgnore") is not None:
        return None
    declaration = _java_declaration(value)
    if not declaration:
        return None
    type_name, fallback_name = declaration
    name = _annotation_string(value, "JsonProperty", "value", "name") or fallback_name
    if name == "serialVersionUID":
        return None
    schema = _java_schema_for_type(type_name)
    description, default, example = _java_parameter_metadata(value, schema)
    if not description:
        comments = list(JAVA_DOC_RE.finditer(value))
        if comments:
            description = _java_doc_summary(comments[-1].group("body"))
        else:
            line_comment = re.search(r"//\s*(?P<body>[^\r\n]+)", value)
            if line_comment:
                description = " ".join(line_comment.group("body").split())
    if not description:
        description = _schema_field_description(name, language)
    assignment = re.search(r"=\s*(?P<value>[^;]+)$", value.strip(), re.DOTALL)
    if default is None and assignment:
        default = _java_literal_value(assignment.group("value"))
    default = _coerce_java_default(default, schema)
    kwargs: dict[str, Any] = {}
    if default is not None:
        kwargs["default"] = default
    if example is not None:
        kwargs["example"] = example
    parameter = parameter_from_schema(
        name,
        "body",
        schema,
        required=_java_field_required(value),
        description=description,
        language=language,
        **kwargs,
    )
    if not parameter:
        return None
    # Keep the original Java type marker (and nested array item marker) until
    # ``build_java_type_schemas`` has indexed every DTO.  The normalized
    # parameter itself intentionally does not expose this implementation
    # detail.
    property_schema = deepcopy(schema)
    for key, item in parameter.items():
        if key in {"name", "in", "required", "children"}:
            continue
        if (
            key == "items"
            and isinstance(schema.get("items"), dict)
            and JAVA_TYPE_MARKER in schema["items"]
            and isinstance(item, dict)
        ):
            property_schema["items"] = deepcopy(schema["items"])
            property_schema["items"]["type"] = item.get("type")
            continue
        property_schema[key] = deepcopy(item)
    return name, property_schema, bool(parameter.get("required"))


def _java_type_declarations(text: str) -> list[dict[str, Any]]:
    declarations: list[dict[str, Any]] = []
    for match in JAVA_TYPE_DECL_RE.finditer(text):
        body_start = text.find("{", match.end())
        semicolon = text.find(";", match.end())
        if body_start < 0 or (semicolon >= 0 and semicolon < body_start):
            continue
        body_end = _find_matching_delimiter(text, body_start, "{", "}")
        if body_end is None:
            continue
        declarations.append(
            {
                "start": match.start(),
                "name_end": match.end(),
                "body_start": body_start,
                "body_end": body_end,
                "kind": match.group("kind"),
                "name": match.group("name"),
            }
        )
    return declarations


def _java_schema_for_declaration(
    text: str,
    declaration: dict[str, Any],
    declarations: list[dict[str, Any]],
    language: str | None = "en",
) -> dict[str, Any]:
    body_start = int(declaration["body_start"])
    body_end = int(declaration["body_end"])
    if declaration["kind"] == "enum":
        enum_values: list[str] = []
        enum_body = text[body_start + 1 : body_end].split(";", 1)[0]
        for raw_value in _split_top_level(enum_body):
            clean_value = _strip_java_comments(_strip_java_annotations(raw_value)).strip()
            match = re.match(r"(?P<name>[A-Za-z_$][\w$]*)", clean_value)
            if match:
                enum_values.append(match.group("name"))
        result: dict[str, Any] = {"type": "string"}
        if enum_values:
            result["enum"] = enum_values
        return result
    body = list(text[body_start + 1 : body_end])
    for child in declarations:
        if child is declaration or not (body_start < child["start"] and child["body_end"] < body_end):
            continue
        start = max(0, int(child["start"]) - body_start - 1)
        end = min(len(body), int(child["body_end"]) - body_start)
        body[start:end] = " " * max(0, end - start)

    fields: list[str] = []
    if declaration["kind"] == "record":
        header_start = text.find("(", int(declaration["name_end"]), body_start)
        if header_start >= 0:
            header_end = _find_matching_delimiter(text, header_start)
            if header_end is not None and header_end < body_start:
                fields.extend(_split_top_level(text[header_start + 1 : header_end]))
    fields.extend(_java_direct_statements("".join(body)))

    properties: dict[str, Any] = {}
    required: list[str] = []
    for field in fields:
        resolved = _java_field_schema(field, language)
        if not resolved:
            continue
        name, schema, is_required = resolved
        properties[name] = schema
        if is_required:
            required.append(name)
    result: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        result["required"] = sorted(set(required))
    return result


def build_java_type_schemas(
    files: list[Path], language: str | None = "en"
) -> dict[str, dict[str, Any]]:
    """Build a DTO index and expand nested DTO object properties recursively."""
    schemas: dict[str, dict[str, Any]] = {}
    for path in files:
        if path.suffix.lower() not in {".java", ".kt"}:
            continue
        text = read_text(path)
        declarations = _java_type_declarations(text)
        for declaration in declarations:
            schema = _java_schema_for_declaration(text, declaration, declarations, language)
            parents = sorted(
                (
                    candidate
                    for candidate in declarations
                    if candidate["start"] < declaration["start"] < candidate["body_end"]
                ),
                key=lambda item: int(item["start"]),
            )
            names = [str(candidate["name"]) for candidate in parents] + [str(declaration["name"])]
            for key in (".".join(names), names[-1]):
                schemas.setdefault(key, schema)
    for key in list(schemas):
        schemas[key] = _expand_java_schema_references(schemas[key], schemas, {key})
    return schemas


def _expand_java_schema_references(
    schema: dict[str, Any],
    schemas: dict[str, dict[str, Any]],
    trail: set[str],
) -> dict[str, Any]:
    """Resolve statically indexed Java DTO fields without following cycles forever."""
    result = deepcopy(schema)
    reference = result.pop(JAVA_TYPE_MARKER, None)
    if isinstance(reference, str):
        candidates = [reference, reference.rsplit(".", 1)[-1]]
        target_name = next((candidate for candidate in candidates if candidate in schemas), None)
        if target_name and target_name not in trail:
            expanded = _expand_java_schema_references(
                schemas[target_name], schemas, {*trail, target_name}
            )
            # Keep the referenced DTO/enum's structural type.  The source
            # field marker is initially represented as ``object``; blindly
            # updating the resolved enum would turn it back into an object
            # and discard the enum contract.  Field-level documentation and
            # constraints still override the referenced metadata.
            for key, value in result.items():
                if key in {"type", "properties", "required", "items", "enum"}:
                    continue
                expanded[key] = value
            if (
                isinstance(expanded.get("enum"), list)
                and expanded.get("enum")
                and result.get("example") in (None, {})
            ):
                expanded["example"] = deepcopy(expanded["enum"][0])
            result = expanded

    properties = result.get("properties")
    if isinstance(properties, dict):
        result["properties"] = {
            str(name): _expand_java_schema_references(value, schemas, trail)
            if isinstance(value, dict)
            else value
            for name, value in properties.items()
        }
    items = result.get("items")
    if isinstance(items, dict):
        result["items"] = _expand_java_schema_references(items, schemas, trail)
    return result


def _resolve_java_body_schema(type_name: str, schemas: dict[str, dict[str, Any]]) -> dict[str, Any]:
    raw = re.sub(r"\s+", "", type_name)
    if raw.lower().startswith("optional<") and raw.endswith(">"):
        raw = raw[len("Optional<") : -1]
    candidates = [raw, raw.rsplit(".", 1)[-1]]
    for candidate in candidates:
        if candidate in schemas:
            return deepcopy(schemas[candidate])
    schema = _java_schema_for_type(raw)
    if schema.get("type") == "object":
        schema["additionalProperties"] = True
    return schema


def _java_type_parts(type_name: str) -> tuple[str, list[str]]:
    """Split a Java type and its top-level generic arguments conservatively."""
    compact = re.sub(r"\s+", "", _strip_java_comments(type_name)).strip()
    if compact.startswith("?"):
        compact = re.sub(r"^\?(?:extends|super)?", "", compact)
    opening = compact.find("<")
    if opening < 0 or not compact.endswith(">"):
        return compact, []
    return compact[:opening], _split_top_level(compact[opening + 1 : -1], delimiter=",")


def _java_schema_reference_known(schema: Any, schemas: dict[str, dict[str, Any]]) -> bool:
    """Report whether all internal Java type markers can be resolved."""
    if not isinstance(schema, dict):
        return True
    reference = schema.get(JAVA_TYPE_MARKER)
    if isinstance(reference, str):
        candidates = [reference, reference.rsplit(".", 1)[-1]]
        if not any(candidate in schemas for candidate in candidates):
            return False
    for value in schema.get("properties", {}).values() if isinstance(schema.get("properties"), dict) else ():
        if not _java_schema_reference_known(value, schemas):
            return False
    return _java_schema_reference_known(schema.get("items"), schemas)


def _java_response_schema_for_type(
    type_name: str,
    schemas: dict[str, dict[str, Any]],
    warnings: list[str],
) -> dict[str, Any]:
    """Convert a Spring method return type into a reviewable response schema."""
    base, arguments = _java_type_parts(type_name)
    simple_base = base.rsplit(".", 1)[-1].lower()
    if simple_base in {"void", "unit"}:
        return {}
    if simple_base in JAVA_RESPONSE_UNWRAP_TYPES:
        return (
            _java_response_schema_for_type(arguments[0], schemas, warnings)
            if arguments
            else {}
        )
    if simple_base in JAVA_RESPONSE_ENVELOPE_TYPES:
        warnings.append(
            f"Spring response wrapper {type_name} was inferred as code/data; verify the business envelope before import"
        )
        data_schema = (
            _java_response_schema_for_type(arguments[0], schemas, warnings)
            if arguments
            else {"type": "object"}
        )
        if not arguments:
            warnings.append(
                f"Spring response wrapper {type_name} has no generic data type; response.data remains an object"
            )
        return {
            "type": "object",
            "required": ["code", "data"],
            "properties": {
                "code": {
                    "type": "integer",
                    "const": 0,
                    "description": "业务响应码。",
                    "example": 0,
                },
                "data": data_schema,
            },
        }

    schema = _java_schema_for_type(type_name)
    if not _java_schema_reference_known(schema, schemas):
        warnings.append(
            f"Spring response type {type_name} is not indexed in source; response fields remain an object placeholder"
        )
    # Start with an empty trail so the top-level DTO can expand. Recursive
    # self-references are still stopped once the target name is added by the
    # expansion routine.
    return _expand_java_schema_references(schema, schemas, set())


def _set_spring_response_schema(
    item: dict[str, Any],
    return_type: str | None,
    java_schemas: dict[str, dict[str, Any]],
    language: str | None = "en",
) -> None:
    """Attach a static Spring response contract when a return type is visible."""
    normalized = str(return_type or "").strip()
    if not normalized:
        return
    response_warnings: list[str] = []
    schema = _java_response_schema_for_type(normalized, java_schemas, response_warnings)
    for warning in response_warnings:
        _add_item_warning(item, warning)
    if not schema:
        return
    _warn_schema_gaps(item, schema, "Response")
    schema = _enrich_schema_fields(schema, language)
    unpack = _response_unpack_for_schema(schema)
    if unpack:
        item["response_unpack"] = {
            key: value for key, value in unpack.items() if key != "data_schema"
        }
        item["response_schema"] = unpack["data_schema"]
    else:
        item.pop("response_unpack", None)
        item["response_schema"] = schema

    # A typed object/array response is JSON by convention unless an OpenAPI
    # source later supplies a more specific media type.  Preserve a raw
    # Spring request schema while normalizing it to the http-api/v1 wrapper.
    if schema.get("type") in {"object", "array"}:
        current = item.get("request_schema")
        if not isinstance(current, dict):
            current = {}
        elif current and "schema" not in current and "accept" not in current:
            current = {"schema": deepcopy(current)}
        current.setdefault("schema", {})
        current.setdefault("accept", "application/json")
        item["request_schema"] = current


def _java_method_declaration_after(text: str, start: int) -> re.Match[str] | None:
    # ``SPRING_RE`` intentionally consumes indentation after an annotation;
    # begin at the physical line start so the declaration expression can still
    # match a multiline, indented Java method.
    search_start = text.rfind("\n", 0, start) + 1
    return JAVA_METHOD_DECL_RE.search(text, search_start, min(len(text), start + 5000))


def _java_method_parameters_after(text: str, start: int) -> list[str]:
    match = _java_method_declaration_after(text, start)
    if not match:
        return []
    opening = match.end() - 1
    closing = _find_matching_delimiter(text, opening)
    if closing is None:
        return []
    return _split_top_level(text[opening + 1 : closing])


def _java_method_return_type_after(text: str, start: int) -> str:
    match = _java_method_declaration_after(text, start)
    return str(match.group("return_type") or "").strip() if match else ""


def _java_method_name_after(text: str, start: int) -> str:
    match = _java_method_declaration_after(text, start)
    return str(match.group("name")) if match else ""


def _java_class_name_before(text: str, position: int) -> str:
    """Return the nearest enclosing class/interface identifier when available."""
    _, name = _java_class_context_before(text, position)
    return name


def _java_class_context_before(text: str, position: int) -> tuple[str, str]:
    """Return the nearest class/interface JavaDoc summary and identifier."""
    matches = list(
        re.finditer(r"\b(?:class|interface)\s+(?P<name>[A-Za-z_$][\w$]*)\b", text[:position])
    )
    if not matches:
        return "", ""
    match = matches[-1]
    return _java_doc_before(text, match.start()), str(match.group("name"))


def _java_method_context_before(text: str, position: int) -> tuple[str, str]:
    """Return the nearest enclosing method JavaDoc summary and identifier."""
    matches = list(JAVA_METHOD_DECL_RE.finditer(text[:position]))
    if not matches:
        return "", ""
    match = matches[-1]
    return _java_doc_before(text, match.start()), str(match.group("name"))


def _spring_websocket_name_and_description(
    text: str,
    position: int,
    language: str | None = "en",
) -> tuple[str | None, str | None]:
    """Name a Spring WebSocket registration from its class/method documentation."""
    class_summary, class_identifier = _java_class_context_before(text, position)
    method_summary, _ = _java_method_context_before(text, position)
    if class_summary and method_summary:
        return _spring_name_and_description(class_summary, method_summary, language=language)
    if method_summary:
        return _spring_name_and_description("", method_summary, language=language)

    context = _java_doc_summary(class_summary) or _java_identifier_label(
        class_identifier, language
    )
    if not context:
        return None, None
    chinese = str(language or "").lower().startswith("zh")
    lower_context = context.lower()
    already_endpoint = "websocket" in lower_context or (chinese and "接口" in context)
    if chinese:
        name = context if already_endpoint else f"{context} WebSocket接口"
        description = class_summary or f"{context}的 WebSocket 通信接口；消息契约需人工审核。"
    else:
        name = context if already_endpoint else f"{context} WebSocket endpoint"
        description = class_summary or f"{context} WebSocket endpoint; message contract requires review."
    return name, description


def _add_item_warning(item: dict[str, Any], message: str) -> None:
    warnings = item.setdefault("warnings", [])
    if message not in warnings:
        warnings.append(message)


def _add_spring_parameters(
    item: dict[str, Any],
    raw_parameters: list[str],
    java_schemas: dict[str, dict[str, Any]],
    language: str | None = "en",
    method_parameter_descriptions: dict[str, str] | None = None,
) -> None:
    method_parameter_descriptions = method_parameter_descriptions or {}
    collected: list[dict[str, Any]] = []
    for raw in raw_parameters:
        declaration = _java_declaration(raw)
        if not declaration:
            continue
        type_name, fallback_name = declaration
        body_args = _annotation_arguments(raw, "RequestBody")
        if body_args is not None:
            body_schema = _resolve_java_body_schema(type_name, java_schemas)
            body_description = method_parameter_descriptions.get(fallback_name, "")
            if body_description:
                body_schema.setdefault("description", body_description)
            _warn_schema_gaps(item, body_schema, "Request")
            body_schema = _enrich_schema_fields(body_schema, language)
            if not item.get("request_schema"):
                item["request_schema"] = deepcopy(body_schema)
            body_parameters = parameters_from_object_schema(body_schema, language=language)
            if body_parameters:
                collected.extend(body_parameters)
            else:
                _add_item_warning(
                    item,
                    f"Spring request body {type_name} has no statically discoverable top-level JSON fields",
                )
            continue

        for annotation, location in (
            ("PathVariable", "path"),
            ("RequestParam", "query"),
            ("RequestHeader", "header"),
        ):
            arguments = _annotation_arguments(raw, annotation)
            if arguments is None:
                continue
            if location == "query" and JAVA_MULTIPART_TYPE_RE.search(type_name):
                _add_item_warning(
                    item,
                    f"Spring multipart parameter {fallback_name} is not emitted because qa-platform sends JSON bodies only",
                )
                break
            name = _annotation_string(raw, annotation, "value", "name") or fallback_name
            schema = _java_schema_for_type(type_name)
            description, schema_default, example = _java_parameter_metadata(raw, schema)
            if not description:
                description = method_parameter_descriptions.get(fallback_name, "") or method_parameter_descriptions.get(name, "")
            if not description:
                identifier_label = _java_identifier_label(name, language)
                if identifier_label and identifier_label.lower() != name.lower():
                    description = identifier_label
                else:
                    description = (
                        f"`{name}` 的业务含义未在源码中说明，请复核。"
                        if str(language or "").lower().startswith("zh")
                        else f"The business meaning of `{name}` is not documented in source; review required."
                    )
                _add_item_warning(
                    item,
                    f"Spring parameter {location}:{name} has no annotation or JavaDoc description",
                )
            default = _annotation_string(raw, annotation, "defaultValue", allow_unnamed=False)
            if default is None:
                default = schema_default
            default = _coerce_java_default(default, schema)
            optional_type = type_name.replace(" ", "").lower().startswith("optional<")
            required = _annotation_bool(raw, annotation, "required", not optional_type)
            if default is not None:
                required = False
            kwargs: dict[str, Any] = {}
            if default is not None:
                kwargs["default"] = default
            if example is not None:
                kwargs["example"] = example
            parameter = parameter_from_schema(
                name,
                location,
                schema,
                required=required,
                description=description,
                language=language,
                **kwargs,
            )
            if parameter:
                collected.append(parameter)
            break
    add_parameters(item, collected)


def parse_spring_routes(
    text: str,
    path: Path,
    root: Path,
    interfaces: dict[str, dict[str, dict[str, Any]]],
    java_schemas: dict[str, dict[str, Any]] | None = None,
    context_prefix: str | None = None,
    context_refs: list[dict[str, Any]] | None = None,
    language: str | None = "en",
    service_key: str | None = None,
) -> None:
    if path.suffix.lower() not in {".java", ".kt"}:
        return
    class_prefixes: list[tuple[int, str, str, bool]] = []
    class_mapping = re.compile(
        r"@RequestMapping\s*(?:\((?P<args>[^\n)]*)\))?\s*(?:public\s+|protected\s+|private\s+|abstract\s+|final\s+)*(?:class|interface)\b"
    )
    class_mapping_positions: set[int] = set()
    mapped_declaration_positions: set[int] = set()
    for class_match in class_mapping.finditer(text):
        class_mapping_positions.add(class_match.start())
        declaration_match = re.search(r"\b(?:class|interface)\b", class_match.group(0))
        declaration_position = (
            class_match.start() + declaration_match.start() if declaration_match else class_match.end()
        )
        mapped_declaration_positions.add(declaration_position)
        class_prefixes.append(
            (
                declaration_position,
                first_literal(class_match.group("args") or "") or "/",
                _java_doc_before(text, declaration_position),
                True,
            )
        )
    for feign_match in re.finditer(r"@(?:[A-Za-z_$][\w$]*\.)*FeignClient\b", text):
        arguments_start = text.find("(", feign_match.end())
        if arguments_start < 0:
            continue
        arguments_end = _find_matching_delimiter(text, arguments_start)
        if arguments_end is None:
            continue
        declaration_match = re.search(
            r"\b(?:class|interface)\b", text[arguments_end + 1 : arguments_end + 2001]
        )
        if not declaration_match:
            continue
        declaration_position = arguments_end + 1 + declaration_match.start()
        annotation = text[feign_match.start() : arguments_end + 1]
        feign_prefix = _annotation_string(
            annotation, "FeignClient", "path", allow_unnamed=False
        )
        if not feign_prefix:
            continue
        mapped_declaration_positions.add(declaration_position)
        class_prefixes.append(
            (
                declaration_position,
                feign_prefix,
                _java_doc_before(text, declaration_position),
                False,
            )
        )
    for declaration_match in re.finditer(
        r"(?m)^\s*(?:public\s+|protected\s+|private\s+|abstract\s+|final\s+|static\s+)*(?:class|interface)\s+[A-Za-z_$][\w$]*",
        text,
    ):
        declaration_position = declaration_match.start()
        if any(abs(declaration_position - mapped) < 80 for mapped in mapped_declaration_positions):
            continue
        class_prefixes.append(
            (declaration_position, "", _java_doc_before(text, declaration_position), True)
        )

    for match in SPRING_RE.finditer(text):
        if match.start() in class_mapping_positions:
            continue
        annotation = match.group("annotation")
        args = match.group("args") or ""
        route = first_literal(args) or "/"
        preceding_prefixes = [item for item in class_prefixes if item[0] < match.start()]
        class_context = max(preceding_prefixes, key=lambda item: item[0]) if preceding_prefixes else None
        class_prefix = class_context[1] if class_context else ""
        class_summary = class_context[2] if class_context else ""
        apply_context_prefix = class_context[3] if class_context else True
        method_summary = _java_doc_before(text, match.start())
        method_parameter_descriptions = _java_doc_param_descriptions(
            _java_doc_block_before(text, match.start())
        )
        api_name, api_description = _spring_name_and_description(
            class_summary,
            method_summary,
            class_identifier=_java_class_name_before(text, match.start()),
            method_identifier=_java_method_name_after(text, match.end()),
            language=language,
        )
        route = join_route(
            context_prefix if apply_context_prefix else None,
            join_route(class_prefix, route),
        )
        line = text.count("\n", 0, match.start()) + 1
        ref = source_ref(path, root, line)
        if annotation == "MessageMapping":
            item = ensure_interface(
                interfaces,
                "ws",
                route,
                root,
                ref,
                name=api_name,
                description=api_description,
                discovery_method="source",
                language=language,
                service_key=service_key,
            )
            if item:
                for context_ref in context_refs or []:
                    add_ref(item, context_ref)
                _add_item_warning(item, "WebSocket message contract is not statically discovered")
            continue
        method = {
            "GetMapping": "GET",
            "PostMapping": "POST",
            "PutMapping": "PUT",
            "PatchMapping": "PATCH",
            "DeleteMapping": "DELETE",
        }.get(annotation)
        if annotation == "RequestMapping":
            methods = [m.upper() for m in re.findall(r"RequestMethod\.([A-Z]+)", args)] or ["GET"]
        else:
            methods = [method] if method else ["GET"]
        signature_parameters = _java_method_parameters_after(text, match.end())
        return_type = _java_method_return_type_after(text, match.end())
        for selected in methods:
            item = ensure_interface(
                interfaces,
                "http",
                route,
                root,
                ref,
                method=selected,
                name=api_name,
                description=api_description,
                discovery_method="source",
                language=language,
                service_key=service_key,
            )
            if item:
                for context_ref in context_refs or []:
                    add_ref(item, context_ref)
                _add_spring_parameters(
                    item,
                    signature_parameters,
                    java_schemas or {},
                    language,
                    method_parameter_descriptions,
                )
                _set_spring_response_schema(
                    item,
                    return_type,
                    java_schemas or {},
                    language,
                )


def parse_call_routes(
    text: str,
    path: Path,
    root: Path,
    interfaces: dict[str, dict[str, dict[str, Any]]],
    language: str | None = "en",
) -> None:
    if path.suffix.lower() not in {".js", ".jsx", ".ts", ".tsx", ".vue", ".go"}:
        return
    prefixes = route_prefixes(text)
    for pattern in (NODE_RE, GO_RE):
        for match in pattern.finditer(text):
            method = match.group("method").upper()
            if method == "ANY":
                method = "GET"
            if method == "HANDLE":
                method = "GET"
            if method not in HTTP_METHODS:
                continue
            line = text.count("\n", 0, match.start()) + 1
            ensure_interface(
                interfaces,
                "http",
                join_route(prefixes.get(match.group("object")), match.group("path")),
                root,
                source_ref(path, root, line),
                method=method,
                discovery_method="source",
                language=language,
            )


def parse_websocket_routes(
    text: str,
    path: Path,
    root: Path,
    interfaces: dict[str, dict[str, dict[str, Any]]],
    context_prefix: str | None = None,
    context_refs: list[dict[str, Any]] | None = None,
    language: str | None = "en",
    service_key: str | None = None,
) -> None:
    suffix = path.suffix.lower()
    if suffix not in {".js", ".jsx", ".ts", ".tsx", ".vue", ".java", ".kt"}:
        return
    prefixes = route_prefixes(text)
    for pattern in (NODE_WS_RE, JAVA_WS_RE):
        if pattern is NODE_WS_RE and suffix not in {".js", ".jsx", ".ts", ".tsx", ".vue"}:
            continue
        if pattern is JAVA_WS_RE and suffix not in {".java", ".kt"}:
            continue
        for match in pattern.finditer(text):
            route = join_route(prefixes.get(match.groupdict().get("object")), match.group("path"))
            if pattern is JAVA_WS_RE:
                route = join_route(context_prefix, route)
            line = text.count("\n", 0, match.start()) + 1
            ensure_interface(
                interfaces,
                "ws",
                route,
                root,
                source_ref(path, root, line),
                discovery_method="source",
                confidence=0.8,
                language=language,
                service_key=service_key,
            )
    if suffix not in {".java", ".kt"} or not SPRING_WS_CONFIG_RE.search(text):
        return
    for match in SPRING_WS_HANDLER_RE.finditer(text):
        line = text.count("\n", 0, match.start()) + 1
        ref = source_ref(path, root, line)
        api_name, api_description = _spring_websocket_name_and_description(
            text, match.start(), language
        )
        for route_match in LITERAL_RE.finditer(match.group("paths")):
            item = ensure_interface(
                interfaces,
                "ws",
                join_route(context_prefix, route_match.group("value")),
                root,
                ref,
                name=api_name,
                description=api_description,
                discovery_method="source",
                confidence=0.95,
                language=language,
                service_key=service_key,
            )
            if item:
                for context_ref in context_refs or []:
                    add_ref(item, context_ref)
                _add_item_warning(item, "WebSocket message contract is not statically discovered")


def parse_frontend_routes(text: str, path: Path, root: Path, features: dict[str, dict[str, Any]]) -> None:
    if path.suffix.lower() not in {".vue", ".js", ".jsx", ".ts", ".tsx"}:
        return
    for match in FRONTEND_ROUTE_RE.finditer(text):
        route = match.group("path").strip()
        if not route.startswith("/"):
            continue
        key = f"page:{slug(route)}"
        item = features.setdefault(
            key,
            {
                "key": key,
                "name": f"Page {route}",
                "description": "",
                "entrypoints": [],
                "related_interfaces": [],
                "preconditions": [],
                "source_refs": [],
                "confidence": 0.55,
                "warnings": ["Feature derived from a frontend route"],
            },
        )
        if route not in item["entrypoints"]:
            item["entrypoints"].append(route)
        add_ref(item, source_ref(path, root, text.count("\n", 0, match.start()) + 1))


def _resolve_json_pointer(document: dict[str, Any], reference: str) -> dict[str, Any] | None:
    if not reference.startswith("#/"):
        return None
    current: Any = document
    for token in reference[2:].split("/"):
        if not isinstance(current, dict):
            return None
        current = current.get(token.replace("~1", "/").replace("~0", "~"))
    return current if isinstance(current, dict) else None


def _resolve_openapi_object(
    document: dict[str, Any], value: Any, warnings: list[str], trail: tuple[str, ...] = ()
) -> dict[str, Any]:
    """Resolve local OpenAPI/AsyncAPI references while retaining sibling fields."""
    if not isinstance(value, dict):
        return {}
    result = deepcopy(value)
    reference = result.pop("$ref", None)
    if not isinstance(reference, str):
        return result
    if reference in trail:
        warnings.append(f"Cyclic API reference was not expanded: {reference}")
        return result
    target = _resolve_json_pointer(document, reference)
    if target is None:
        warnings.append(f"Unsupported or unresolved API reference: {reference}")
        return result
    resolved = _resolve_openapi_object(document, target, warnings, (*trail, reference))
    resolved.update(result)
    return resolved


def _resolve_openapi_schema(
    document: dict[str, Any], value: Any, warnings: list[str], trail: tuple[str, ...] = ()
) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result = deepcopy(value)
    reference = result.pop("$ref", None)
    if isinstance(reference, str):
        if reference in trail:
            warnings.append(f"Cyclic API schema reference was not expanded: {reference}")
        else:
            target = _resolve_json_pointer(document, reference)
            if target is None:
                warnings.append(f"Unsupported or unresolved API schema reference: {reference}")
            else:
                resolved = _resolve_openapi_schema(document, target, warnings, (*trail, reference))
                resolved.update(result)
                result = resolved
    if not result:
        return {}
    properties = result.get("properties")
    if isinstance(properties, dict):
        result["properties"] = {
            str(name): _resolve_openapi_schema(document, schema, warnings, trail)
            for name, schema in properties.items()
        }
    items = result.get("items")
    if isinstance(items, dict):
        result["items"] = _resolve_openapi_schema(document, items, warnings, trail)
    additional = result.get("additionalProperties")
    if isinstance(additional, dict):
        result["additionalProperties"] = _resolve_openapi_schema(document, additional, warnings, trail)
    for field in ("allOf", "anyOf", "oneOf"):
        if isinstance(result.get(field), list):
            result[field] = [
                _resolve_openapi_schema(document, item, warnings, trail)
                if isinstance(item, dict)
                else item
                for item in result[field]
            ]
    if document.get("swagger"):
        if result.get("type") == "file":
            result["type"] = "string"
            result.setdefault("format", "binary")
        if result.get("exclusiveMinimum") is True and isinstance(
            result.get("minimum"), (int, float)
        ):
            result["exclusiveMinimum"] = result.pop("minimum")
        elif isinstance(result.get("exclusiveMinimum"), bool):
            result.pop("exclusiveMinimum", None)
        if result.get("exclusiveMaximum") is True and isinstance(
            result.get("maximum"), (int, float)
        ):
            result["exclusiveMaximum"] = result.pop("maximum")
        elif isinstance(result.get("exclusiveMaximum"), bool):
            result.pop("exclusiveMaximum", None)
    return _materialize_all_of(result)


def _materialize_all_of(schema: dict[str, Any]) -> dict[str, Any]:
    """Expose composed object fields for qa-platform's schema and parameter editors."""
    result = deepcopy(schema)
    branches = result.get("allOf")
    if not isinstance(branches, list):
        return result
    properties = (
        deepcopy(result.get("properties"))
        if isinstance(result.get("properties"), dict)
        else {}
    )
    required = {
        str(item)
        for item in result.get("required", [])
        if isinstance(item, str)
    }
    for branch in branches:
        if not isinstance(branch, dict):
            continue
        branch = _materialize_all_of(branch)
        if isinstance(branch.get("properties"), dict):
            properties.update(deepcopy(branch["properties"]))
        required.update(
            str(item) for item in branch.get("required", []) if isinstance(item, str)
        )
        if not result.get("type") and branch.get("type"):
            result["type"] = branch["type"]
    if properties:
        result["properties"] = properties
        result.setdefault("type", "object")
    if required:
        result["required"] = sorted(required)
    return result


def _apply_schema_example(schema: dict[str, Any], example: Any) -> dict[str, Any]:
    """Carry media-level examples down to fields when schemas omit them."""
    result = deepcopy(schema)
    if example is None:
        return result
    result.setdefault("example", deepcopy(example))
    properties = result.get("properties")
    if isinstance(properties, dict) and isinstance(example, dict):
        for name, value in example.items():
            if name in properties and isinstance(properties[name], dict):
                properties[name] = _apply_schema_example(properties[name], value)
    if isinstance(result.get("items"), dict) and isinstance(example, list) and example:
        result["items"] = _apply_schema_example(result["items"], example[0])
    return result


def _schema_detail_gaps(
    schema: dict[str, Any], prefix: str = ""
) -> tuple[list[str], list[str]]:
    missing_descriptions: list[str] = []
    missing_examples: list[str] = []
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return missing_descriptions, missing_examples
    for name, value in properties.items():
        if not isinstance(value, dict):
            continue
        field_path = f"{prefix}.{name}" if prefix else str(name)
        if not str(value.get("description") or "").strip():
            missing_descriptions.append(field_path)
        if "example" not in value and "default" not in value:
            missing_examples.append(field_path)
        nested_descriptions, nested_examples = _schema_detail_gaps(value, field_path)
        missing_descriptions.extend(nested_descriptions)
        missing_examples.extend(nested_examples)
        items = value.get("items")
        if isinstance(items, dict):
            nested_descriptions, nested_examples = _schema_detail_gaps(
                items, field_path + "[]"
            )
            missing_descriptions.extend(nested_descriptions)
            missing_examples.extend(nested_examples)
    return missing_descriptions, missing_examples


def _schema_field_description(
    name: str, language: str | None
) -> str:
    label = _java_identifier_label(name, language)
    if str(language or "").lower().startswith("zh"):
        if label and label.lower() != name.lower():
            return label
        return f"`{name}` 字段；源码或接口契约未提供业务说明，需复核。"
    if label and label.lower() != name.lower():
        return label
    return f"`{name}` field; its business meaning is not documented in source or API contracts."


def _enrich_schema_fields(
    schema: dict[str, Any], language: str | None
) -> dict[str, Any]:
    """Add deterministic UI metadata without replacing documented values."""
    result = deepcopy(schema)
    properties = result.get("properties")
    if isinstance(properties, dict):
        for name, raw_property in list(properties.items()):
            property_schema = raw_property if isinstance(raw_property, dict) else {}
            enriched = _enrich_schema_fields(property_schema, language)
            fallback = parameter_from_schema(
                str(name), "body", enriched, language=language
            )
            if fallback:
                enriched.setdefault(
                    "description", _schema_field_description(str(name), language)
                )
                enriched.setdefault("example", deepcopy(fallback["example"]))
            properties[name] = enriched
    if isinstance(result.get("items"), dict):
        result["items"] = _enrich_schema_fields(result["items"], language)
    for keyword in ("allOf", "anyOf", "oneOf"):
        if isinstance(result.get(keyword), list):
            result[keyword] = [
                _enrich_schema_fields(branch, language)
                if isinstance(branch, dict)
                else branch
                for branch in result[keyword]
            ]
    return result


def _warn_schema_gaps(
    item: dict[str, Any], schema: dict[str, Any], label: str
) -> None:
    descriptions, examples = _schema_detail_gaps(schema)
    if descriptions:
        _add_item_warning(
            item,
            f"{label} schema fields lacked descriptions and received deterministic placeholders: "
            + ", ".join(descriptions),
        )
    if examples:
        _add_item_warning(
            item,
            f"{label} schema fields lacked examples and received deterministic placeholders: "
            + ", ".join(examples),
        )


def _api_records(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _json_content(
    document: dict[str, Any], content: Any, warnings: list[str]
) -> tuple[str, dict[str, Any]] | None:
    if not isinstance(content, dict):
        return None
    for content_type in sorted(content, key=str.lower):
        normalized = str(content_type).split(";", 1)[0].lower()
        if normalized != "application/json" and not normalized.endswith("+json"):
            continue
        media = _resolve_openapi_object(document, content[content_type], warnings)
        if media:
            return str(content_type), media
    return None


def _media_example(media: dict[str, Any]) -> Any:
    if "example" in media:
        return media["example"]
    examples = media.get("examples")
    if isinstance(examples, dict):
        for value in examples.values():
            if isinstance(value, dict) and "value" in value:
                return value["value"]
    return None


def _preferred_json_type(value: Any) -> str | None:
    if not isinstance(value, list):
        return None
    for item in value:
        normalized = str(item).split(";", 1)[0].strip().lower()
        if normalized == "application/json" or normalized.endswith("+json"):
            return str(item)
    return None


def _set_request_body_schema(item: dict[str, Any], schema: dict[str, Any]) -> None:
    current = item.get("request_schema")
    accept = current.get("accept") if isinstance(current, dict) else None
    item["request_schema"] = {"schema": deepcopy(schema)}
    if isinstance(accept, str) and accept.strip():
        item["request_schema"]["accept"] = accept.strip()


def _set_accept(item: dict[str, Any], content_type: str | None) -> None:
    if not isinstance(content_type, str) or not content_type.strip():
        return
    current = item.get("request_schema")
    if isinstance(current, dict) and (
        "schema" in current or "accept" in current
    ):
        request_schema = deepcopy(current)
    else:
        request_schema = {"schema": deepcopy(current)} if isinstance(current, dict) and current else {}
    request_schema["accept"] = content_type.strip()
    request_schema.setdefault("schema", {})
    item["request_schema"] = request_schema


def _set_request_content_type(item: dict[str, Any], content_type: str | None) -> None:
    if not isinstance(content_type, str) or not content_type.strip():
        return
    request = item.get("request") if isinstance(item.get("request"), dict) else {}
    request = deepcopy(request)
    headers = request.get("headers") if isinstance(request.get("headers"), dict) else {}
    headers = deepcopy(headers)
    if "content-type" not in {str(name).lower() for name in headers}:
        headers["Content-Type"] = content_type.strip()
    request["headers"] = headers
    item["request"] = request


def _explicit_business_key(value: dict[str, Any]) -> str | None:
    candidate = value.get("x-business-key") or value.get("x_business_key")
    return str(candidate).strip() if isinstance(candidate, str) and candidate.strip() else None


GROUP_PATH_EXTENSION_KEYS = (
    "x-qa-platform-group-path",
    "x-api-group-path",
    "x-group-path",
    "group_path",
    "api_group_path",
)


def _raw_explicit_group_path(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    for key in GROUP_PATH_EXTENSION_KEYS:
        candidate = value.get(key)
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return None


def _normalized_explicit_group_path(value: Any, warnings: list[str], source: str) -> str | None:
    raw = _raw_explicit_group_path(value)
    if not raw:
        return None
    try:
        return normalize_group_path(raw)
    except ValueError as exc:
        warnings.append(f"{source} API 目录扩展无效，已忽略: {exc}")
        return None


def _openapi_tag_group_paths(
    document: dict[str, Any], warnings: list[str], source: str
) -> dict[str, str]:
    """Read optional directory extensions from OpenAPI tag declarations."""
    result: dict[str, str] = {}
    raw_tags = document.get("tags")
    if not isinstance(raw_tags, list):
        return result
    for raw_tag in raw_tags:
        if not isinstance(raw_tag, dict):
            continue
        name = str(raw_tag.get("name") or "").strip()
        path = _normalized_explicit_group_path(
            raw_tag, warnings, f"{source} tag {name or '<unnamed>'}"
        )
        if name and path:
            result[name] = path
    return result


def _set_group_path_hint(item: dict[str, Any], path: str | None) -> None:
    if path:
        item["_group_path_hint"] = path


def _group_rule_matches(interface: dict[str, Any], match: dict[str, Any]) -> bool:
    """Match the stable, source-derived API facts supported by api_grouping.rules."""
    if not match:
        return True
    protocol = str(interface.get("protocol") or "http").lower()
    method = str(interface.get("method") or "").upper()
    path = str(interface.get("path") or interface.get("url") or "")
    key = str(interface.get("key") or "")
    service = str(interface.get("service") or "")
    operation_id = str(interface.get("operation_id") or "")
    business_key = str(interface.get("_business_key") or "")
    tags = {str(tag) for tag in interface.get("tags", []) if isinstance(tag, str)}

    if match.get("protocol") and str(match["protocol"]).lower() != protocol:
        return False
    methods = match.get("methods", match.get("method"))
    if isinstance(methods, str):
        methods = [methods]
    if isinstance(methods, list) and method not in {str(value).upper() for value in methods}:
        return False
    for field, actual in (
        ("keys", key),
        ("paths", path),
        ("operation_ids", operation_id),
        ("business_keys", business_key),
    ):
        expected = match.get(field)
        if isinstance(expected, str):
            expected = [expected]
        if isinstance(expected, list) and actual not in {str(value) for value in expected}:
            return False
    if match.get("key") and key != str(match["key"]):
        return False
    if match.get("path") and path != str(match["path"]):
        return False
    if match.get("operation_id") and operation_id != str(match["operation_id"]):
        return False
    if match.get("business_key") and business_key != str(match["business_key"]):
        return False
    if match.get("service") and service != str(match["service"]):
        return False
    if match.get("path_prefix") and not path.startswith(str(match["path_prefix"])):
        return False
    if match.get("path_regex"):
        if re.search(str(match["path_regex"]), path) is None:
            return False
    required_tags = match.get("tags")
    if isinstance(required_tags, str):
        required_tags = [required_tags]
    if isinstance(required_tags, list) and not tags.intersection(
        str(value) for value in required_tags
    ):
        return False
    return True


def _tag_group_path(tags: Any) -> str | None:
    if not isinstance(tags, list):
        return None
    for raw_tag in tags:
        if not isinstance(raw_tag, str) or not raw_tag.strip():
            continue
        # Hierarchical tags are accepted as ``用户服务/用户管理``,
        # ``用户服务 > 用户管理`` or ``用户服务::用户管理``.
        segments = [
            segment.strip()
            for segment in re.split(r"\s*(?:/|>|::|／)\s*", raw_tag)
            if segment.strip()
        ]
        if segments:
            return group_path_from_segments(segments)
    return None


def _path_group_segments(path: str) -> list[str]:
    parsed = urlsplit(path)
    path_value = parsed.path if parsed.scheme or parsed.netloc else path.split("?", 1)[0]
    ignored = {"api", "apis", "v1", "v2", "v3", "v4", "version"}
    result: list[str] = []
    for raw_segment in path_value.split("/"):
        segment = raw_segment.strip().strip("{}")
        segment = segment.removeprefix(":")
        if not segment or segment.lower() in ignored:
            continue
        if raw_segment.strip().startswith(("{", ":")):
            continue
        result.append(segment)
    return result[:2]


def _controller_group_segment(item: dict[str, Any]) -> str | None:
    for ref in item.get("source_refs", []):
        if not isinstance(ref, dict):
            continue
        file_name = Path(str(ref.get("file") or "")).stem
        if not file_name:
            continue
        suffix_match = re.search(
            r"(?i)(controller|resource|endpoint|handler|router|api)$", file_name
        )
        if not suffix_match and Path(str(ref.get("file") or "")).suffix.lower() not in {
            ".java",
            ".kt",
        }:
            continue
        candidate = re.sub(
            r"(?i)(controller|resource|endpoint|handler|router|api)$", "", file_name
        ).strip("_- ")
        if candidate and candidate.lower() not in {
            "application",
            "bootstrap",
            "app",
            "main",
            "routes",
            "server",
        }:
            return candidate
    return None


def _service_group_segment(value: Any) -> str | None:
    candidate = str(value or "").strip()
    if not candidate:
        return None
    candidate = re.sub(r"^(?i:app|service)[-_]", "", candidate)
    return candidate.strip("/_-") or None


def _business_group_segments(item: dict[str, Any]) -> list[str]:
    raw = str(item.get("_business_key") or "")
    generic = {
        "get", "post", "put", "patch", "head", "options", "trace",
        "list", "create", "update", "delete", "detail", "search", "query",
        "find", "fetch", "save", "add", "remove",
        "api", "apis", "v1", "v2", "v3", "version", "id", "ids",
    }
    segments = [segment for segment in re.split(r"[.:/_-]+", raw) if segment]
    return [segment for segment in segments if segment.lower() not in generic][:2]


def _heuristic_group_path(item: dict[str, Any], root: Path) -> tuple[str, str]:
    controller = _controller_group_segment(item)
    if controller:
        return group_path_from_segments([controller]), "controller"

    service = _service_group_segment(item.get("service"))
    if service and service.lower() != root.name.lower():
        return group_path_from_segments([service]), "module"

    business_segments = _business_group_segments(item)
    if business_segments:
        return group_path_from_segments(business_segments), "business_key"

    path_segments = _path_group_segments(str(item.get("path") or item.get("url") or ""))
    if path_segments:
        return group_path_from_segments(path_segments), "path"
    return "/", "root"


def _join_group_paths(parent: str | None, child: str | None) -> str:
    normalized_parent = normalize_group_path(parent or "/")
    normalized_child = normalize_group_path(child or "/")
    if normalized_parent == "/":
        return normalized_child
    if normalized_child == "/":
        return normalized_parent
    if normalized_child == normalized_parent or normalized_child.startswith(
        normalized_parent + "/"
    ):
        return normalized_child
    return normalize_group_path(
        normalized_parent.rstrip("/") + "/" + normalized_child.lstrip("/")
    )


def assign_api_group_paths(
    interfaces: dict[str, dict[str, dict[str, Any]]],
    root: Path,
    grouping: dict[str, Any],
    service_topology: dict[str, Any] | None = None,
) -> None:
    """Assign API directories as service root plus business/controller group."""
    rules = grouping.get("rules", []) if isinstance(grouping, dict) else []
    default_path = str(grouping.get("default_path") or "/") if isinstance(grouping, dict) else "/"
    services = {
        str(service.get("key")): service
        for service in (service_topology or {}).get("services", [])
        if isinstance(service, dict) and service.get("key")
    }
    for protocol in ("http", "ws"):
        for item in interfaces[protocol].values():
            matches = [
                rule
                for rule in rules
                if isinstance(rule, dict)
                and isinstance(rule.get("match"), dict)
                and _group_rule_matches(item, rule["match"])
            ]
            if matches:
                group_path = str(matches[0].get("group_path") or default_path)
                source = "project_config"
                if len(matches) > 1:
                    item.setdefault("warnings", []).append(
                        "Multiple API directory rules matched; the first configured rule was selected"
                    )
            elif default_path != "/":
                group_path = default_path
                source = "project_config_default"
            else:
                if item.get("_group_path_hint"):
                    business_path = str(item["_group_path_hint"])
                    business_source = "openapi_extension"
                else:
                    tag_path = _tag_group_path(item.get("tags"))
                    if tag_path:
                        business_path = tag_path
                        business_source = "tag"
                    else:
                        business_path, business_source = _heuristic_group_path(item, root)
                service = services.get(str(item.get("service") or ""))
                service_group_path = str((service or {}).get("group_path") or "/")
                group_path = _join_group_paths(service_group_path, business_path)
                source = (
                    f"service_topology+{business_source}"
                    if service_group_path != "/"
                    else business_source
                )

            item["group_path"] = normalize_group_path(group_path)
            fallback_source = source.removeprefix("service_topology+")
            if fallback_source in {"business_key", "path", "root"}:
                item.setdefault("warnings", []).append(
                    f"API 目录由{ {'business_key': '业务标识', 'path': 'URL 路径', 'root': '根目录'}.get(fallback_source, fallback_source) }推导，请复核 group_path"
                )
            item.pop("_group_path_hint", None)


def _add_openapi_parameters(
    item: dict[str, Any],
    document: dict[str, Any],
    raw_parameters: Any,
    warnings: list[str],
    language: str | None = "en",
    request_content_type: str | None = None,
) -> None:
    collected: list[dict[str, Any]] = []
    for raw in _api_records(raw_parameters):
        parameter = _resolve_openapi_object(document, raw, warnings)
        location = str(parameter.get("in") or "").lower()
        if location == "body":
            schema = _resolve_openapi_schema(document, parameter.get("schema"), warnings)
            if schema:
                item.setdefault("source_request_schema", deepcopy(parameter.get("schema") or {}))
                _warn_schema_gaps(item, schema, "Request")
                schema = _enrich_schema_fields(schema, language)
                _set_request_body_schema(item, schema)
                _set_request_content_type(item, request_content_type)
                collected.extend(parameters_from_object_schema(schema, language=language))
            else:
                _add_item_warning(item, "Swagger body parameter has no readable JSON schema")
            continue
        if location == "formdata":
            _add_item_warning(
                item,
                "Swagger formData parameters are not emitted because qa-platform sends JSON bodies only",
            )
            continue
        schema = parameter.get("schema")
        if not isinstance(schema, dict):
            selected = _json_content(document, parameter.get("content"), warnings)
            if selected:
                schema = selected[1].get("schema")
        if isinstance(schema, dict):
            parameter["schema"] = _resolve_openapi_schema(document, schema, warnings)
        documented_description = str(
            parameter.get("description")
            or (parameter.get("schema") or {}).get("description")
            or ""
        ).strip()
        normalized = normalize_openapi_parameter(parameter, language=language)
        if normalized:
            collected.append(normalized)
            if not documented_description:
                _add_item_warning(
                    item,
                    f"OpenAPI parameter {normalized['in']}:{normalized['name']} has no description; a deterministic placeholder was generated",
                )
    add_parameters(item, collected)


def _add_openapi_request_body(
    item: dict[str, Any],
    document: dict[str, Any],
    raw_body: Any,
    warnings: list[str],
    language: str | None = "en",
) -> None:
    body = _resolve_openapi_object(document, raw_body, warnings)
    content = body.get("content")
    selected = _json_content(document, content, warnings)
    if not selected:
        if isinstance(content, dict) and content:
            _add_item_warning(
                item,
                "Request body is not application/json and is not emitted as executable parameters",
            )
        return
    content_type, media = selected
    raw_schema = media.get("schema")
    schema = _resolve_openapi_schema(document, raw_schema, warnings)
    if not schema:
        _add_item_warning(item, "JSON request body has no readable schema")
        return
    item["source_request_schema"] = deepcopy(raw_schema) if isinstance(raw_schema, dict) else {}
    schema = _apply_schema_example(schema, _media_example(media))
    _warn_schema_gaps(item, schema, "Request")
    schema = _enrich_schema_fields(schema, language)
    _set_request_body_schema(item, schema)
    _set_request_content_type(item, content_type)
    body_parameters = parameters_from_object_schema(schema, language=language)
    if body_parameters:
        add_parameters(item, body_parameters)
    else:
        _add_item_warning(
            item,
            "JSON request body is not a top-level object; provide a request override when executing it",
        )


def _response_schema_from_operation(
    document: dict[str, Any],
    raw_responses: Any,
    warnings: list[str],
    swagger_produces: Any = None,
) -> tuple[str | None, dict[str, Any]]:
    if not isinstance(raw_responses, dict):
        return _preferred_json_type(swagger_produces), {}
    statuses = sorted(
        raw_responses,
        key=lambda value: (
            0 if str(value).startswith("2") else 1,
            str(value),
        ),
    )
    for status in statuses:
        if not str(status).startswith(("2", "3")):
            continue
        response = _resolve_openapi_object(document, raw_responses[status], warnings)
        if isinstance(response.get("schema"), dict):  # Swagger 2
            schema = _resolve_openapi_schema(document, response["schema"], warnings)
            examples = response.get("examples")
            content_type = _preferred_json_type(swagger_produces)
            example = None
            if isinstance(examples, dict):
                if content_type and content_type in examples:
                    example = examples[content_type]
                elif examples:
                    example = next(iter(examples.values()))
            return content_type, _apply_schema_example(schema, example)
        selected = _json_content(document, response.get("content"), warnings)
        if selected:
            schema = _resolve_openapi_schema(document, selected[1].get("schema"), warnings)
            return selected[0], _apply_schema_example(schema, _media_example(selected[1]))
    return _preferred_json_type(swagger_produces), {}


def _response_unpack_for_schema(schema: dict[str, Any]) -> dict[str, Any] | None:
    """Recognize a strongly evidenced ``{code, data}`` response envelope."""
    if not isinstance(schema, dict) or schema.get("type") != "object":
        return None
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return None
    code_schema = properties.get("code")
    data_schema = properties.get("data")
    if not isinstance(code_schema, dict) or not isinstance(data_schema, dict):
        return None
    required = {str(value) for value in schema.get("required", [])}
    has_success_signal = "const" in code_schema or isinstance(code_schema.get("enum"), list)
    if not ({"code", "data"} <= required or has_success_signal):
        return None
    return {
        "enabled": True,
        "source": "body.data",
        "envelope_schema": deepcopy(schema),
        "data_schema": deepcopy(data_schema),
    }


def load_openapi(
    path: Path,
    root: Path,
    interfaces: dict[str, dict[str, dict[str, Any]]],
    warnings: list[str],
    language: str | None = "en",
    *,
    document_override: dict[str, Any] | None = None,
    source_name: str | None = None,
    required: bool = False,
) -> None:
    def reject_or_warn(message: str) -> None:
        if required:
            raise SystemExit(message)
        warnings.append(message)

    document: Any = document_override
    if document is None:
        try:
            payload = path.read_bytes()
        except OSError as exc:
            reject_or_warn(f"Could not read OpenAPI document {path}: {exc}")
            return
        try:
            document = _parse_openapi_payload(
                payload,
                str(path),
                "application/yaml"
                if path.suffix.lower() in {".yaml", ".yml"}
                else "application/json",
            )
        except SystemExit as exc:
            reject_or_warn(str(exc))
            return
    if not isinstance(document, dict):
        reject_or_warn(f"API document must be an object: {path}")
        return
    ref = {"file": source_name, "line": 1} if source_name else source_ref(path, root, 1)
    document_source = source_name or path.name
    tag_group_paths = _openapi_tag_group_paths(document, warnings, document_source)
    document_group_path = _normalized_explicit_group_path(
        document, warnings, f"{document_source} document"
    )
    if not isinstance(document.get("paths"), dict):
        channels = document.get("channels")
        if not isinstance(channels, dict):
            reject_or_warn(
                f"Document has no OpenAPI paths or AsyncAPI channels: {source_name or path}"
            )
            return
        servers = document.get("servers")
        server_url = ""
        if isinstance(servers, dict):
            first_server = next(iter(servers.values()), {})
            if isinstance(first_server, dict):
                server_url = str(first_server.get("url") or "").rstrip("/")
        for channel, channel_item in sorted(channels.items()):
            if not isinstance(channel_item, dict):
                continue
            channel_item = _resolve_openapi_object(document, channel_item, warnings)
            route = f"{server_url}/{str(channel).lstrip('/')}" if server_url else str(channel)
            explicit_business_key = _explicit_business_key(channel_item)
            if not explicit_business_key:
                for direction in ("publish", "subscribe"):
                    operation = _resolve_openapi_object(document, channel_item.get(direction), warnings)
                    explicit_business_key = _explicit_business_key(operation)
                    if explicit_business_key:
                        break
            item = ensure_interface(
                interfaces,
                "ws",
                route,
                root,
                ref,
                name=channel_item.get("description") or str(channel),
                business_key=explicit_business_key,
                discovery_method="asyncapi",
                confidence=0.98,
                language=language,
            )
            if item is None:
                continue
            _set_group_path_hint(
                item,
                _normalized_explicit_group_path(
                    channel_item, warnings, f"{document_source} channel {channel}"
                )
                or document_group_path,
            )
            channel_parameters = channel_item.get("parameters")
            if isinstance(channel_parameters, dict):
                collected: list[dict[str, Any]] = []
                for name, raw_parameter in channel_parameters.items():
                    parameter = _resolve_openapi_object(document, raw_parameter, warnings)
                    schema = _resolve_openapi_schema(document, parameter.get("schema"), warnings)
                    normalized = parameter_from_schema(
                        str(name),
                        "path",
                        schema,
                        required=True,
                        description=str(parameter.get("description") or ""),
                        language=language,
                    )
                    if normalized:
                        collected.append(normalized)
                add_parameters(item, collected)
            messages: list[dict[str, Any]] = []
            for direction in ("publish", "subscribe"):
                operation = _resolve_openapi_object(document, channel_item.get(direction), warnings)
                if not operation:
                    continue
                message = operation.get("message")
                values = message if isinstance(message, list) else [message]
                for value in values:
                    value = _resolve_openapi_object(document, value, warnings)
                    if value:
                        messages.append(
                            {
                                "direction": direction,
                                "name": value.get("name") or value.get("title"),
                                "payload": _resolve_openapi_schema(
                                    document, value.get("payload"), warnings
                                ),
                            }
                        )
            if messages:
                item["messages"] = messages
                item["receive_count"] = sum(message["direction"] == "subscribe" for message in messages)
        return
    for route in sorted(document["paths"]):
        raw_path_item = document["paths"].get(route, {})
        if not isinstance(raw_path_item, dict):
            continue
        path_item = _resolve_openapi_object(document, raw_path_item, warnings)
        for method in sorted(path_item):
            if method.upper() not in HTTP_METHODS:
                continue
            raw_operation = path_item[method]
            if not isinstance(raw_operation, dict):
                continue
            operation = _resolve_openapi_object(document, raw_operation, warnings)
            explicit_business_key = _explicit_business_key(operation)
            discovery_method = "swagger" if document.get("swagger") else "openapi"
            item = ensure_interface(
                interfaces,
                "http",
                route,
                root,
                ref,
                method=method.upper(),
                name=operation.get("summary") or operation.get("operationId"),
                description=operation.get("description") or path_item.get("description"),
                operation_id=operation.get("operationId"),
                business_key=explicit_business_key,
                discovery_method=discovery_method,
                confidence=0.98,
                language=language,
            )
            if item is None:
                continue
            if not str(operation.get("summary") or "").strip():
                _add_item_warning(
                    item,
                    "OpenAPI operation has no summary; operationId/path was used for the display name",
                )
            if not str(operation.get("description") or "").strip():
                _add_item_warning(item, "OpenAPI operation has no description")
            item["operation_id"] = operation.get("operationId")
            tags = operation.get("tags") if isinstance(operation.get("tags"), list) else []
            item["tags"] = sorted(
                set(item.get("tags", [])) | {str(tag) for tag in tags if isinstance(tag, str)}
            )
            group_path_hint = (
                _normalized_explicit_group_path(
                    operation, warnings, f"{document_source} {method.upper()} {route}"
                )
                or _normalized_explicit_group_path(
                    path_item, warnings, f"{document_source} path {route}"
                )
                or next(
                    (tag_group_paths[tag] for tag in tags if tag in tag_group_paths),
                    None,
                )
                or document_group_path
            )
            _set_group_path_hint(item, group_path_hint)
            consumes = operation.get("consumes", document.get("consumes"))
            request_content_type = _preferred_json_type(consumes)
            _add_openapi_parameters(
                item,
                document,
                path_item.get("parameters"),
                warnings,
                language,
                request_content_type,
            )
            _add_openapi_parameters(
                item,
                document,
                operation.get("parameters"),
                warnings,
                language,
                request_content_type,
            )
            _add_openapi_request_body(
                item, document, operation.get("requestBody"), warnings, language
            )
            response_content_type, response_schema = _response_schema_from_operation(
                document,
                operation.get("responses"),
                warnings,
                operation.get("produces", document.get("produces")),
            )
            _set_accept(item, response_content_type)
            if response_schema:
                _warn_schema_gaps(item, response_schema, "Response")
                enriched_response_schema = _enrich_schema_fields(response_schema, language)
                unpack = _response_unpack_for_schema(enriched_response_schema)
                if unpack:
                    item["response_unpack"] = {
                        key: value for key, value in unpack.items() if key != "data_schema"
                    }
                    item["response_schema"] = unpack["data_schema"]
                else:
                    item.pop("response_unpack", None)
                    item["response_schema"] = enriched_response_schema
            elif isinstance(operation.get("responses"), dict) and any(
                str(status).startswith("2") and str(status) != "204"
                for status in operation["responses"]
            ):
                _add_item_warning(
                    item, "OpenAPI success response has no readable JSON schema"
                )
            security = (
                operation.get("security")
                if "security" in operation
                else document.get("security")
            )
            item["auth"] = "required" if security else "none" if security == [] else "unknown"


def _parse_openapi_payload(payload: bytes, source: str, content_type: str = "") -> dict[str, Any]:
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SystemExit(f"Unable to decode API document {source}: {exc}") from None
    use_yaml = (
        "yaml" in content_type.lower()
        or source.lower().split("?", 1)[0].endswith((".yaml", ".yml"))
        or not text.lstrip().startswith(("{", "["))
    )
    if use_yaml:
        try:
            import yaml  # type: ignore
        except ImportError:
            raise SystemExit(f"PyYAML is required to read API document {source}") from None
        try:
            value = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise SystemExit(f"Unable to parse API document {source}: {exc}") from None
    else:
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"Unable to parse API document {source}: {exc}") from None
    if not isinstance(value, dict):
        raise SystemExit(f"API document must be a JSON/YAML object: {source}")
    return value


def load_openapi_url(
    url: str,
    root: Path,
    interfaces: dict[str, dict[str, dict[str, Any]]],
    warnings: list[str],
    language: str | None = "en",
    *,
    timeout_seconds: float = 3,
    max_bytes: int = 10 * 1024 * 1024,
    required: bool = False,
) -> None:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise SystemExit(f"OpenAPI URL must use http or https: {url}")
    request = Request(
        url,
        headers={
            "Accept": "application/json, application/yaml, application/x-yaml, text/yaml",
            "User-Agent": "qa-platform-skill/1.0",
        },
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 - explicit config only
            payload = response.read(max_bytes + 1)
            content_type = str(response.headers.get("Content-Type") or "")
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        message = f"Could not fetch runtime OpenAPI document {url}: {exc}"
        if required:
            raise SystemExit(message) from None
        warnings.append(message)
        return
    if len(payload) > max_bytes:
        message = f"Runtime OpenAPI document exceeds {max_bytes} bytes: {url}"
        if required:
            raise SystemExit(message)
        warnings.append(message)
        return
    try:
        document = _parse_openapi_payload(payload, url, content_type)
    except SystemExit as exc:
        if required:
            raise
        warnings.append(str(exc))
        return
    path_name = Path(parsed.path).name or "openapi.json"
    load_openapi(
        Path(path_name),
        root,
        interfaces,
        warnings,
        language,
        document_override=document,
        source_name=url,
        required=required,
    )


def detect_runtime_openapi_paths(files: list[Path]) -> list[str]:
    """Map known framework evidence to conventional runtime document paths."""
    paths: list[str] = []

    def add(path: str) -> None:
        if path not in paths:
            paths.append(path)

    for path in files:
        if path.name not in BUILD_METADATA_NAMES and path.suffix.lower() not in {
            ".py",
            ".java",
            ".kt",
            ".js",
            ".ts",
        }:
            continue
        text = read_text(path)[:500_000].lower()
        if "springdoc-openapi" in text or "org.springdoc" in text:
            add("/v3/api-docs")
        if "springfox" in text or "swagger2" in text:
            add("/v2/api-docs")
        if "fastapi" in text:
            add("/openapi.json")
        if "@nestjs/swagger" in text or "swaggerdocumentoptions" in text:
            add("/api-json")
        if "swaggo" in text or "swaggerfiles" in text:
            add("/swagger/doc.json")
    return paths


def runtime_openapi_urls(
    openapi_config: dict[str, Any],
    project_variables: dict[str, Any],
    files: list[Path],
) -> list[dict[str, Any]]:
    runtime = openapi_config.get("runtime_discovery", {})
    if not isinstance(runtime, dict) or not runtime.get("enabled"):
        return []
    base_url = str(project_variables.get("base_url") or "").strip()
    if not base_url:
        raise SystemExit(
            "qa-platform openapi.runtime_discovery requires variables.base_url"
        )
    scheme = str(runtime.get("scheme") or "http").lower()
    if scheme not in {"http", "https"}:
        raise SystemExit("qa-platform openapi.runtime_discovery.scheme must be http or https")
    paths = runtime.get("paths") or detect_runtime_openapi_paths(files)
    if not paths:
        return []
    base = f"{scheme}://{base_url}/"
    return [
        {
            "url": urljoin(base, str(path).lstrip("/")),
            "required": False,
            "timeout_seconds": runtime.get("timeout_seconds", 3),
            "max_bytes": runtime.get("max_bytes", 10 * 1024 * 1024),
        }
        for path in paths
    ]


def discover_files(root: Path, excluded_roots: tuple[Path, ...] = ()) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if (
            path.suffix.lower() not in SOURCE_SUFFIXES
            and path.suffix.lower() not in ARCHITECTURE_SUFFIXES
            and path.name not in BUILD_METADATA_NAMES
        ):
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if any(_is_relative_to(path, excluded_root) for excluded_root in excluded_roots):
            continue
        files.append(path)
    return sorted(files, key=lambda item: item.as_posix())


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def git_commit(root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def detect_architecture(root: Path, files: list[Path]) -> dict[str, Any]:
    """Infer service topology and gateway evidence without executing the project."""
    gateway_hits: list[dict[str, Any]] = []
    discovery_hits: list[dict[str, Any]] = []
    explicit_addresses: list[dict[str, Any]] = []
    inferred_ports: list[dict[str, Any]] = []
    service_dirs: set[str] = set()
    build_names = BUILD_METADATA_NAMES

    def service_root(relative: Path) -> Path:
        for index, part in enumerate(relative.parts):
            normalized = part.lower()
            if "gateway" in normalized or normalized.startswith(
                ("app-", "service-", "microservice-")
            ):
                return Path(*relative.parts[: index + 1])
        return relative

    for path in files:
        text = read_text(path)
        relative = path.relative_to(root)
        gateway_module_path = any("gateway" in part.lower() for part in relative.parts)
        gateway_config_path = gateway_module_path and path.suffix.lower() in {
            ".yaml",
            ".yml",
            ".properties",
            ".json",
        }
        gateway_build_path = gateway_module_path and path.name in build_names
        if path.name in build_names and relative.parent != Path("."):
            service_dirs.add(service_root(relative.parent).as_posix())
        lower = text.lower()
        # A module such as ``app-gateway`` with its own application configuration
        # is stronger evidence than a generic Java class whose name happens to
        # contain "gateway".  This also covers nested YAML where
        # ``spring.cloud.gateway`` is not present as one literal string.
        if gateway_config_path:
            gateway_hits.append(
                {
                    "marker": "gateway-module-config",
                    "source_ref": source_ref(path, root, 1),
                }
            )
        if gateway_build_path:
            gateway_hits.append(
                {
                    "marker": "gateway-module-build",
                    "source_ref": source_ref(path, root, 1),
                }
            )
        for marker in GATEWAY_MARKERS:
            position = lower.find(marker.lower())
            if position >= 0:
                line = text.count("\n", 0, position) + 1
                gateway_hits.append({"marker": marker, "source_ref": source_ref(path, root, line)})
        for marker in SERVICE_DISCOVERY_MARKERS:
            position = lower.find(marker.lower())
            if position >= 0:
                line = text.count("\n", 0, position) + 1
                discovery_hits.append({"marker": marker, "source_ref": source_ref(path, root, line)})
        for match in GATEWAY_URL_RE.finditer(text):
            key = match.group("key").lower()
            if "gateway" not in key and "api" not in key:
                continue
            line = text.count("\n", 0, match.start()) + 1
            explicit_addresses.append(
                {"value": match.group("url").rstrip("/"), "source_ref": source_ref(path, root, line)}
            )
        if gateway_module_path or "gateway" in path.name.lower() or "gateway" in lower:
            for match in SERVER_PORT_RE.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                inferred_ports.append(
                    {"port": int(match.group("port")), "source_ref": source_ref(path, root, line)}
                )

    service_like_dirs = [
        value
        for value in service_dirs
        if any(
            token in part.lower()
            for part in Path(value).parts
            for token in ("app-", "service", "gateway", "microservice")
        )
    ]
    multiple_build_roots = len(service_dirs) >= 2
    is_microservices = bool(
        gateway_hits or discovery_hits or len(service_like_dirs) >= 2 or multiple_build_roots
    )
    architecture_confidence = (
        0.9
        if gateway_hits
        else 0.8
        if discovery_hits
        else 0.6
        if is_microservices
        else 0.7
    )
    gateway_refs = [hit["source_ref"] for hit in gateway_hits]
    address: dict[str, Any] | None = None
    gateway_warnings: list[str] = []
    if explicit_addresses:
        address = {
            "value": explicit_addresses[0]["value"],
            "kind": "explicit",
            "discovery_method": "config",
            "confidence": 0.9,
            "source_refs": [item["source_ref"] for item in explicit_addresses],
        }
    elif gateway_hits and inferred_ports:
        address = {
            "value": f"http://localhost:{inferred_ports[0]['port']}",
            "kind": "inferred",
            "discovery_method": "server-port",
            "confidence": 0.45,
            "source_refs": [item["source_ref"] for item in inferred_ports],
        }
        gateway_warnings.append("网关地址由 server.port 推断，导入前请人工确认 host 和协议")
    elif is_microservices:
        gateway_warnings.append("识别为微服务或多服务项目，但未找到明确的网关访问地址")
    if multiple_build_roots and not gateway_hits and not discovery_hits:
        gateway_warnings.append("发现多个构建根目录，可能是多服务或多模块项目，请人工确认拓扑")

    displayed_service_dirs = service_like_dirs or list(service_dirs)
    service_names = [
        {"name": Path(value).name, "root": value}
        for value in sorted(displayed_service_dirs)
        if Path(value).name.lower() not in {"src", "test", "tests"}
    ]
    return {
        "is_microservices": is_microservices,
        "type": "microservices" if is_microservices else "monolith_or_unknown",
        "confidence": architecture_confidence,
        "gateway": {
            "detected": bool(gateway_hits),
            "address": address,
            "source_refs": gateway_refs,
            "confidence": 0.9 if gateway_hits else 0.0,
            "warnings": gateway_warnings,
        },
        "services": service_names,
        "evidence": {
            "gateway_markers": gateway_hits,
            "service_discovery_markers": discovery_hits,
            "multiple_build_roots": multiple_build_roots,
        },
        "warnings": gateway_warnings,
    }


def add_inferred_features(
    interfaces: dict[str, dict[str, dict[str, Any]]], features: dict[str, dict[str, Any]]
) -> None:
    for protocol in ("http", "ws"):
        for item in interfaces[protocol].values():
            path = str(item.get("path") or item.get("url") or "")
            interface_business_key = str(
                item.get("_business_key") or derive_business_key(protocol, item.get("method"), path)
            )
            business_segments = [segment for segment in interface_business_key.split(".") if segment]
            if not business_segments:
                continue
            feature_business_key = ".".join(business_segments[:2])
            key = f"feature:{feature_business_key}"
            feature = features.setdefault(
                key,
                {
                    "key": key,
                    "business_key": feature_business_key,
                    "name": feature_business_key.replace(".", " ").replace("-", " ").title(),
                    "description": "",
                    "entrypoints": [],
                    "related_interfaces": [],
                    "preconditions": [],
                    "source_refs": [],
                    "confidence": 0.45,
                    "warnings": ["Feature grouped heuristically from an interface path"],
                },
            )
            if item["key"] not in feature["related_interfaces"]:
                feature["related_interfaces"].append(item["key"])


ZH_TOKEN_LABELS = {
    "api": "服务",
    "auth": "认证",
    "chat": "聊天",
    "chunk": "分块",
    "client": "客户端",
    "code": "编码",
    "config": "配置",
    "conversation": "会话",
    "content": "内容",
    "create": "创建",
    "add": "新增",
    "delete": "删除",
    "detail": "详情",
    "description": "说明",
    "download": "下载",
    "edit": "编辑",
    "enabled": "是否启用",
    "embedding": "嵌入",
    "entities": "实体",
    "entity": "实体",
    "export": "导出",
    "ext": "扩展",
    "execution": "执行",
    "explain": "解释",
    "field": "字段",
    "fields": "字段",
    "file": "文件",
    "lineage": "血缘",
    "metadata": "元数据",
    "meta": "元数据",
    "health": "健康检查",
    "http": "HTTP",
    "id": "标识",
    "import": "导入",
    "list": "列表",
    "login": "登录",
    "logout": "登出",
    "message": "消息",
    "method": "方式",
    "model": "模型",
    "manage": "管理",
    "management": "管理",
    "name": "名称",
    "order": "订单",
    "path": "路径",
    "permission": "权限",
    "provider": "提供方",
    "plan": "计划",
    "pivot": "透视",
    "preview": "预览",
    "project": "项目",
    "query": "查询",
    "request": "请求",
    "response": "响应",
    "refresh": "刷新",
    "register": "注册",
    "remove": "删除",
    "role": "角色",
    "rule": "规则",
    "rules": "规则",
    "search": "搜索",
    "send": "发送",
    "setting": "设置",
    "sync": "同步",
    "system": "系统",
    "status": "状态",
    "test": "测试",
    "tool": "工具",
    "type": "类型",
    "transform": "转换",
    "update": "更新",
    "upload": "上传",
    "user": "用户",
    "url": "地址",
    "validate": "校验",
    "version": "版本",
    "value": "值",
    "key": "键",
    "kb": "知识库",
    "virtual": "虚拟",
    "data": "数据",
    "flow": "流程",
    "websocket": "消息",
    "ws": "WebSocket",
}
ZH_METHOD_LABELS = {
    "GET": "查询",
    "POST": "创建",
    "PUT": "更新",
    "PATCH": "更新",
    "DELETE": "删除",
    "HEAD": "查询",
    "OPTIONS": "查询",
    "TRACE": "追踪",
    "WS": "消息",
}


def _key_tokens(value: str) -> list[str]:
    return [token.lower() for token in re.split(r"[.:/_\-]+", str(value or "")) if token]


def chinese_business_label(business_key: str, method: str | None = None) -> str:
    tokens = [token for token in _key_tokens(business_key) if token not in {"v1", "v2", "v3", "version"}]
    labels: list[str] = []
    for token in tokens:
        # Preserve an unrecognized route token rather than replacing its only
        # business context with the generic label “业务”.
        label = ZH_TOKEN_LABELS.get(token, token)
        if label and label not in labels:
            labels.append(label)
    method_label = ZH_METHOD_LABELS.get(str(method or "").upper(), "")
    if not labels:
        return method_label or "根路径"
    label = "".join(labels)
    return label if not method_label or method_label in label else f"{label}{method_label}"


GENERIC_CHINESE_INTERFACE_NAME_RE = re.compile(
    r"^(?:(?:虚拟数据)?(?:校验)?(?:业务)?|(?:查询|删除|新增|创建|更新|修改|保存|校验|列表|详情))接口$"
)


def _is_generic_chinese_interface_name(value: Any) -> bool:
    normalized = re.sub(r"\s+", "", str(value or "")).rstrip("。！？.!?")
    return bool(GENERIC_CHINESE_INTERFACE_NAME_RE.fullmatch(normalized))


def ensure_unique_interface_names(
    interfaces: dict[str, dict[str, dict[str, Any]]]
) -> None:
    """Make colliding display names reviewable without changing stable keys."""
    all_interfaces = [
        item
        for protocol in ("http", "ws")
        for item in interfaces[protocol].values()
    ]
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in all_interfaces:
        name = _bounded_display_name(item.get("name"))
        if name:
            item["name"] = name
            grouped.setdefault(name, []).append(item)
    used_names = {
        name for name, items in grouped.items() if len(items) == 1
    }
    for name, items in grouped.items():
        if len(items) < 2:
            continue
        for item in sorted(items, key=lambda value: str(value.get("key") or "")):
            protocol = str(item.get("protocol") or "http").upper()
            method = str(item.get("method") or protocol).upper()
            endpoint = str(item.get("path") or item.get("url") or item.get("key") or "")
            endpoint_label = _bounded_display_name(endpoint, 56)
            candidate = _display_name_with_suffix(
                name, f"（{method} {endpoint_label}）"
            )
            counter = 2
            while candidate in used_names:
                candidate = _display_name_with_suffix(
                    name, f"（{method} {endpoint_label} #{counter}）"
                )
                counter += 1
            item["name"] = candidate
            used_names.add(candidate)


def localize_assets(
    interfaces: dict[str, dict[str, dict[str, Any]]],
    features: dict[str, dict[str, Any]],
    test_cases: list[dict[str, Any]],
    flows: list[dict[str, Any]],
    test_plans: list[dict[str, Any]],
    language: dict[str, Any],
) -> None:
    """Localize generated names/descriptions while preserving stable business keys."""
    if not str(language.get("code", "")).lower().startswith("zh"):
        ensure_unique_interface_names(interfaces)
        for protocol in ("http", "ws"):
            for item in interfaces[protocol].values():
                item.pop("_name_source", None)
                item.pop("_name_priority", None)
                item.pop("_description_priority", None)
                item.pop("_business_key", None)
        return

    interface_labels: dict[str, str] = {}
    for protocol in ("http", "ws"):
        for item in interfaces[protocol].values():
            business_key = str(item.get("_business_key") or item.get("key") or "")
            label = chinese_business_label(business_key, item.get("method"))
            original_name = str(item.get("name") or "").strip()
            generic_source_name = _is_generic_chinese_interface_name(original_name)
            if item.get("_name_source") != "source" or generic_source_name:
                item["name"] = f"{label}接口"
            protocol_label = "HTTP" if protocol == "http" else "WebSocket"
            if not str(item.get("description") or "").strip() or (
                generic_source_name and _is_generic_chinese_interface_name(item.get("description"))
            ):
                item["description"] = f"用于{label}，协议为 {protocol_label}；成功断言和请求参数需人工审核。"
            interface_labels[str(item["key"])] = str(item.get("name") or label)

    ensure_unique_interface_names(interfaces)
    for protocol in ("http", "ws"):
        for item in interfaces[protocol].values():
            interface_labels[str(item["key"])] = str(item.get("name") or "接口")
            item.pop("_name_source", None)
            item.pop("_name_priority", None)
            item.pop("_description_priority", None)
            item.pop("_business_key", None)

    feature_labels: dict[str, str] = {}
    for feature in features.values():
        label = chinese_business_label(str(feature.get("business_key") or feature.get("key") or ""))
        feature_labels[str(feature["key"])] = label
        feature["name"] = label
        feature["description"] = f"{label}相关接口的功能分组，来源于静态扫描结果。"

    for case in test_cases:
        interface_key = str((case.get("target") or {}).get("interface_key") or "")
        label = interface_labels.get(interface_key, "接口")
        case["name"] = f"{label}冒烟测试"
        case["warnings"] = ["请求参数和鉴权信息仍需人工审核"]

    for flow in flows:
        documented = flow.get("origin") == "documentation"
        feature_key = f"feature:{str(flow.get('key', '')).removeprefix('flow:')}"
        label = feature_labels.get(feature_key, chinese_business_label(str(flow.get("key") or "测试")))
        if not documented or not str(flow.get("name") or "").strip():
            flow["name"] = f"{label}测试流程"
        if not documented or not str(flow.get("description") or "").strip():
            flow["description"] = (
                "由项目测试流程文档生成的待审核测试流程。"
                if documented
                else "由接口与功能分组生成的待审核测试流程。"
            )
        for step in flow.get("steps", []):
            if not documented or not str(step.get("name") or "").strip():
                step["name"] = interface_labels.get(
                    str(step.get("interface_key") or ""), "接口"
                )

    for plan in test_plans:
        version = str(plan.get("version") or "当前")
        plan["name"] = f"{version}版本测试计划"
        plan["description"] = "按版本汇总测试流程和未被流程覆盖接口的待审核测试计划。"


def _javascript_named_block(text: str, names: tuple[str, ...]) -> str:
    """Extract a likely shared request-header builder from JS/TS source."""
    for name in names:
        function_match = re.search(rf"\bfunction\s+{re.escape(name)}\b", text)
        if function_match:
            opening_paren = text.find("(", function_match.end())
            closing_paren = _find_matching_delimiter(text, opening_paren)
            opening = text.find("{", closing_paren or function_match.end())
            closing = _find_matching_delimiter(text, opening, "{", "}")
            if opening >= 0 and closing is not None:
                return text[function_match.start() : closing + 1]
        arrow_match = re.search(
            rf"\b(?:const|let|var)\s+{re.escape(name)}\b", text
        )
        if arrow_match:
            arrow = text.find("=>", arrow_match.end())
            opening = text.find("{", arrow)
            closing = _find_matching_delimiter(text, opening, "{", "}")
            if arrow >= 0 and opening >= 0 and closing is not None:
                return text[arrow_match.start() : closing + 1]
    return ""


def _javascript_literal(value: str) -> str | None:
    """Decode only a plain JS string literal; expressions remain unresolved."""
    value = value.strip().rstrip(",")
    if len(value) < 2 or value[0] not in {"'", '"', "`"} or value[-1] != value[0]:
        return None
    if value[0] == "`" and "${" in value:
        return None
    return (
        value[1:-1]
        .replace(r"\\n", "\n")
        .replace(r"\\r", "\r")
        .replace(r"\\t", "\t")
        .replace(r'\"', '"')
        .replace(r"\'", "'")
        .replace(r"\\", "\\")
    )


def _safe_frontend_header_value(name: str, expression: str) -> str | None:
    """Convert a shared frontend header expression into a secret-free value."""
    normalized = name.strip().lower()
    expression = expression.strip().rstrip(",")
    if normalized in TEMPLATE_AUTH_HEADER_NAMES:
        if re.search(r"bearer", expression, re.IGNORECASE):
            return "Bearer {{ access_token }}"
        return "{{ access_token }}"
    if normalized == "x-trace-id":
        return "{{ random.uuid(32) }}"
    if normalized == "x-frontend-environment":
        return "{{ frontend_environment }}"
    if normalized not in TEMPLATE_SAFE_HEADER_NAMES:
        return None
    literal = _javascript_literal(expression)
    if literal is not None and literal.strip():
        return literal.strip()
    return None


def discover_frontend_api_template(
    files: list[Path], root: Path
) -> tuple[dict[str, Any] | None, list[str]]:
    """Discover safe headers from a shared frontend request wrapper."""
    header_values: dict[str, str] = {}
    header_refs: dict[str, list[dict[str, Any]]] = {}
    warnings: list[str] = []
    for path in files:
        if path.suffix.lower() not in {".js", ".jsx", ".ts", ".tsx", ".vue"}:
            continue
        text = read_text(path)
        constants: dict[str, str] = {}
        for constant in re.finditer(
            r"\b(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*(?P<value>['\"][^'\"]+['\"])",
            text,
        ):
            literal = _javascript_literal(constant.group("value"))
            if literal:
                constants[constant.group("name")] = literal
        block = _javascript_named_block(
            text,
            (
                "buildRequestHeaders",
                "buildRequestHeader",
                "createRequestHeaders",
                "createRequestHeader",
            ),
        )
        if not block:
            continue

        expressions: list[tuple[str, str, int]] = []
        value_pattern = r"""(?:(?P<quote>['"])(?P<quoted>[A-Za-z0-9-]+)(?P=quote)|(?P<bare>[A-Za-z_$][\w$-]*))\s*:\s*(?P<value>`(?:\\.|[^`])*`|\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|[^,\n}]+)"""
        for match in re.finditer(value_pattern, block, re.DOTALL):
            name = match.group("quoted") or match.group("bare") or ""
            expressions.append(
                (
                    name,
                    match.group("value"),
                    text.count("\n", 0, text.find(block) + match.start()) + 1,
                )
            )
        computed_pattern = r"""\[(?P<reference>[A-Za-z_$][\w$]*)\]\s*:\s*(?P<value>`(?:\\.|[^`])*`|\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|[^,\n}]+)"""
        for match in re.finditer(computed_pattern, block, re.DOTALL):
            name = constants.get(match.group("reference"), "")
            if not name:
                continue
            expressions.append(
                (
                    name,
                    match.group("value"),
                    text.count("\n", 0, text.find(block) + match.start()) + 1,
                )
            )
        for name, expression, line in expressions:
            normalized = name.strip().lower()
            value = _safe_frontend_header_value(name, expression)
            if value is None:
                continue
            if normalized in header_values and header_values[normalized] != value:
                warnings.append(
                    f"Frontend shared request header {name} has conflicting static values; kept the first value"
                )
                continue
            header_values.setdefault(normalized, value)
            header_refs.setdefault(normalized, []).append(source_ref(path, root, line))

    if not header_values:
        return None, warnings
    headers: dict[str, str] = {}
    display_names = {
        "accept": "Accept",
        "content-type": "Content-Type",
        "x-frontend-environment": "X-Frontend-Environment",
        "x-trace-id": "X-Trace-Id",
        "authorization": "Authorization",
        "proxy-authorization": "Proxy-Authorization",
    }
    refs: list[dict[str, Any]] = []
    for normalized, value in header_values.items():
        headers[display_names.get(normalized, normalized)] = value
        for ref in header_refs.get(normalized, []):
            if ref not in refs:
                refs.append(ref)
    return (
        {
            "key": "scanner:frontend-http",
            "name": "前端公共 HTTP 请求模板",
            "protocol": "http",
            "description": "从前端公共请求封装静态发现的安全默认请求头；动态值使用 qa-platform 变量。",
            "request": {"headers": headers},
            "match": {"protocol": "http"},
            "origin": "scanner",
            "discovery_method": "frontend-request-wrapper",
            "confidence": 0.9,
            "source_refs": refs,
        },
        warnings,
    )


def _config_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    normalized = _config_literal(value).lower()
    if normalized in {"true", "on", "yes", "1"}:
        return True
    if normalized in {"false", "off", "no", "0"}:
        return False
    return None


def discover_gateway_api_template(
    files: list[Path], root: Path, base_headers: dict[str, str] | None = None
) -> tuple[dict[str, Any] | None, list[str]]:
    """Discover a secret-free gateway Authorization template and exclusions."""
    candidates: list[dict[str, Any]] = []
    for path in files:
        if not SPRING_APPLICATION_CONFIG_RE.match(path.name):
            continue
        entries = _simple_config_entries(path)
        relevant = [
            entry
            for entry in entries
            if str(entry.get("key", "")).startswith("gateway.security.")
        ]
        if not relevant:
            continue
        values: dict[str, list[dict[str, Any]]] = {}
        for entry in relevant:
            key = str(entry["key"])
            values.setdefault(key, []).append(entry)
        def first(*keys: str) -> dict[str, Any] | None:
            for key in keys:
                matches = values.get(key)
                if matches:
                    return matches[0]
            return None

        enabled_entry = first("gateway.security.enabled")
        require_entry = first("gateway.security.requiretoken")
        enabled = _config_bool(str(enabled_entry["value"])) if enabled_entry else None
        require_token = _config_bool(str(require_entry["value"])) if require_entry else None
        header_entry = first("gateway.security.headername")
        prefix_entry = first("gateway.security.tokenprefix")
        if enabled is False or require_token is False:
            continue
        if not any((require_token is True, header_entry, prefix_entry)):
            continue
        header_name = _config_literal(header_entry["value"]) if header_entry else "Authorization"
        token_prefix = _config_literal(prefix_entry["value"]) if prefix_entry else "Bearer"
        if not header_name or not token_prefix:
            continue
        ignore_paths: list[str] = []
        ignore_refs: list[dict[str, Any]] = []
        for key, key_entries in values.items():
            if not key.startswith("gateway.security.ignoreurls"):
                continue
            for entry in key_entries:
                path_value = _config_literal(entry["value"])
                if not path_value or path_value.startswith(("${", "#{")):
                    continue
                if path_value not in ignore_paths:
                    ignore_paths.append(path_value)
                ref = source_ref(path, root, int(entry["line"]))
                if ref not in ignore_refs:
                    ignore_refs.append(ref)
        refs: list[dict[str, Any]] = []
        for entry in (enabled_entry, require_entry, header_entry, prefix_entry):
            if entry:
                ref = source_ref(path, root, int(entry["line"]))
                if ref not in refs:
                    refs.append(ref)
        refs.extend(ref for ref in ignore_refs if ref not in refs)
        candidates.append(
            {
                "path": path,
                "priority": _application_config_priority(path),
                "header_name": header_name,
                "token_prefix": token_prefix,
                "ignore_paths": ignore_paths,
                "source_refs": refs,
            }
        )

    if not candidates:
        return None, []
    candidates.sort(key=lambda item: (int(item["priority"]), str(item["path"])))
    selected = candidates[0]
    warnings: list[str] = []
    signatures = {
        (
            str(candidate["header_name"]),
            str(candidate["token_prefix"]),
            tuple(candidate["ignore_paths"]),
        )
        for candidate in candidates
    }
    if len(signatures) > 1:
        warnings.append(
            "Multiple Spring gateway security configurations were found; the highest-priority application config was used for the API template"
        )
    headers = deepcopy(base_headers or {})
    # Assemble the placeholder from a literal prefix without ever copying a
    # configured secret/token value.
    headers[str(selected["header_name"])] = (
        f"{selected['token_prefix']} {{{{ access_token }}}}"
        if str(selected["token_prefix"])
        else "{{ access_token }}"
    )
    match: dict[str, Any] = {"protocol": "http"}
    if selected["ignore_paths"]:
        match["exclude_paths"] = sorted(set(selected["ignore_paths"]))
    return (
        {
            "key": "scanner:gateway-auth-http",
            "name": "网关鉴权 HTTP 请求模板",
            "protocol": "http",
            "description": "从 Spring 网关安全配置静态发现的鉴权请求头；令牌由 access_token 变量提供。",
            "request": {"headers": headers},
            "match": match,
            "origin": "scanner",
            "discovery_method": "spring-gateway-security",
            "confidence": 0.92,
            "source_refs": selected["source_refs"],
        },
        warnings,
    )


def discover_api_templates(
    files: list[Path], root: Path, language: str | None = "zh-CN"
) -> tuple[list[dict[str, Any]], list[str]]:
    """Discover reusable project request templates from static source evidence."""
    frontend_template, warnings = discover_frontend_api_template(files, root)
    base_headers = {}
    if frontend_template:
        base_headers = deepcopy(frontend_template.get("request", {}).get("headers", {}))
    gateway_template, gateway_warnings = discover_gateway_api_template(
        files, root, base_headers
    )
    warnings.extend(gateway_warnings)
    templates: list[dict[str, Any]] = []
    if gateway_template:
        templates.append(gateway_template)
    if frontend_template:
        templates.append(frontend_template)
    if templates and not str(language or "").lower().startswith("zh"):
        for template in templates:
            if template["key"] == "scanner:frontend-http":
                template["name"] = "Frontend shared HTTP request"
                template["description"] = "Safe defaults statically discovered from the shared frontend request wrapper."
            else:
                template["name"] = "Gateway authenticated HTTP request"
                template["description"] = "Authorization defaults statically discovered from Spring gateway security configuration."
    return templates, warnings


def _match_path_pattern(path: str, pattern: str) -> bool:
    normalized = str(pattern or "").strip()
    if not normalized:
        return False
    if fnmatchcase(path, normalized):
        return True
    if normalized.endswith("/**") and path == normalized[:-3].rstrip("/"):
        return True
    if normalized.endswith("/*") and path == normalized[:-2].rstrip("/"):
        return True
    return False


def _template_matches(interface: dict[str, Any], match: dict[str, Any]) -> bool:
    if not match:
        return False
    protocol = str(interface.get("protocol") or "http").lower()
    method = str(interface.get("method") or "").upper()
    path = str(interface.get("path") or interface.get("url") or "")
    key = str(interface.get("key") or "")
    tags = {str(item) for item in interface.get("tags", []) if isinstance(item, str)}

    if match.get("protocol") and str(match["protocol"]).lower() != protocol:
        return False
    methods = match.get("methods", match.get("method"))
    if isinstance(methods, str):
        methods = [methods]
    if isinstance(methods, list) and method not in {str(item).upper() for item in methods}:
        return False
    keys = match.get("keys", match.get("key"))
    if isinstance(keys, str):
        keys = [keys]
    if isinstance(keys, list) and key not in {str(item) for item in keys}:
        return False
    paths = match.get("paths", match.get("path"))
    if isinstance(paths, str):
        paths = [paths]
    if isinstance(paths, list) and path not in {str(item) for item in paths}:
        return False
    prefix = match.get("path_prefix")
    if prefix and not path.startswith(str(prefix)):
        return False
    excluded_paths = match.get("exclude_paths", match.get("exclude_path"))
    if isinstance(excluded_paths, str):
        excluded_paths = [excluded_paths]
    if isinstance(excluded_paths, list) and any(
        _match_path_pattern(path, str(pattern)) for pattern in excluded_paths
    ):
        return False
    excluded_prefixes = match.get("exclude_path_prefixes")
    if isinstance(excluded_prefixes, str):
        excluded_prefixes = [excluded_prefixes]
    if isinstance(excluded_prefixes, list) and any(
        path.startswith(str(pattern)) for pattern in excluded_prefixes
    ):
        return False
    excluded_regex = match.get("exclude_path_regex")
    if excluded_regex:
        try:
            if re.search(str(excluded_regex), path) is not None:
                return False
        except re.error as exc:
            raise SystemExit(
                f"Invalid api_templates.match.exclude_path_regex {excluded_regex}: {exc}"
            ) from None
    regex = match.get("path_regex")
    if regex:
        try:
            if re.search(str(regex), path) is None:
                return False
        except re.error as exc:
            raise SystemExit(f"Invalid api_templates.match.path_regex {regex}: {exc}") from None
    required_tags = match.get("tags")
    if isinstance(required_tags, str):
        required_tags = [required_tags]
    if isinstance(required_tags, list) and not tags.intersection(str(item) for item in required_tags):
        return False
    return True


def apply_api_template_bindings(
    interfaces: dict[str, dict[str, dict[str, Any]]],
    templates: list[dict[str, Any]],
) -> None:
    """Bind configured templates with deterministic match rules."""
    for protocol in ("http", "ws"):
        for interface in interfaces[protocol].values():
            matches = [
                template
                for template in templates
                if isinstance(template.get("match"), dict)
                and _template_matches(interface, template["match"])
            ]
            if not matches:
                continue
            selected = matches[0]
            interface["template_key"] = str(selected.get("key") or selected["name"])
            if len(matches) > 1:
                _add_item_warning(
                    interface,
                    "Multiple API templates matched; the first configured template was selected: "
                    + ", ".join(str(item.get("key") or item["name"]) for item in matches),
                )


def finalize_http_request_schemas(
    interfaces: dict[str, dict[str, dict[str, Any]]]
) -> None:
    """Normalize scanner-era raw schemas to the http-api/v1 wrapper."""
    for item in interfaces["http"].values():
        schema = item.get("request_schema")
        if not isinstance(schema, dict):
            item["request_schema"] = {}
        elif schema and "schema" not in schema and "accept" not in schema:
            item["request_schema"] = {"schema": deepcopy(schema)}


def build_assets(
    interfaces: dict[str, dict[str, dict[str, Any]]],
    features: dict[str, dict[str, Any]],
    plan_version: str,
    project_key: str,
    documented_flows: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    all_interfaces = sorted(
        [*interfaces["http"].values(), *interfaces["ws"].values()], key=lambda item: item["key"]
    )
    test_cases: list[dict[str, Any]] = []
    for item in all_interfaces:
        test_cases.append(
            {
                "key": f"case:{item['key']}:smoke",
                "name": f"Smoke: {item.get('method', 'WS')} {item.get('path') or item.get('url')}",
                "type": "api_smoke",
                "target": {"interface_key": item["key"]},
                "priority": "P1",
                "status": "draft",
                "origin": "scanner",
                "preconditions": [],
                "request": {},
                "assertions": [],
                "source_refs": item.get("source_refs", []),
                "confidence": min(float(item.get("confidence", 0.5)), 0.7),
                "warnings": ["Request values and authentication require review"],
            }
        )

    flows: list[dict[str, Any]] = deepcopy(documented_flows or [])
    covered_interface_keys: set[str] = {
        str(step.get("interface_key"))
        for flow in flows
        for step in flow.get("steps", [])
        if isinstance(step, dict) and step.get("interface_key")
    }
    for feature in sorted(features.values(), key=lambda item: item["key"]):
        related = sorted(
            set(feature.get("related_interfaces", [])) - covered_interface_keys
        )
        if not related:
            continue
        covered_interface_keys.update(related)
        steps = []
        for index, key in enumerate(related, start=1):
            steps.append(
                {
                    "id": f"step-{index}",
                    "name": key,
                    "interface_key": key,
                    "enabled": False,
                    "request": {},
                    "assertions": [],
                    "extractors": [],
                }
            )
        feature_business_key = str(feature.get("business_key") or feature["key"].removeprefix("feature:"))
        flow_key = f"flow:{feature_business_key}"
        flows.append(
            {
                "key": flow_key,
                "name": f"{feature['name']} draft flow",
                "description": "由接口与功能分组生成的待审核测试流程。",
                "status": "draft",
                "origin": "scanner",
                "variables": {},
                "steps": steps,
                "source_refs": feature.get("source_refs", []),
                "confidence": min(float(feature.get("confidence", 0.4)), 0.45),
                "warnings": ["Step order is inferred; review before enabling"],
            }
        )
    uncovered_interfaces = [
        item for item in all_interfaces if str(item["key"]) not in covered_interface_keys
    ]
    plan_items: list[dict[str, Any]] = []
    for index, flow in enumerate(flows, start=1):
        plan_items.append(
            {
                "id": f"flow-item-{index}",
                "type": "flow",
                "target_key": str(flow["key"]),
                "enabled": False,
            }
        )
    for index, interface in enumerate(uncovered_interfaces, start=1):
        plan_items.append(
            {
                "id": f"api-item-{index}",
                "type": "api",
                "target_key": str(interface["key"]),
                "enabled": False,
            }
        )

    source_refs: list[dict[str, Any]] = []
    seen_source_refs: set[tuple[str, int]] = set()
    for item in [*flows, *uncovered_interfaces]:
        for ref in item.get("source_refs", []):
            if not isinstance(ref, dict):
                continue
            file = ref.get("file")
            line = ref.get("line")
            if not isinstance(file, str) or not isinstance(line, int):
                continue
            identity = (file, line)
            if identity not in seen_source_refs:
                seen_source_refs.add(identity)
                source_refs.append({"file": file, "line": line})

    test_plans: list[dict[str, Any]] = []
    if plan_items:
        test_plans.append(
            {
                "key": f"plan:{slug(project_key)}:{slug(plan_version)}:smoke",
                "version": plan_version,
                "name": f"{project_key} {plan_version} smoke plan",
                "description": "One version plan that aggregates draft flows and uncovered interfaces.",
                "status": "draft",
                "origin": "scanner",
                "items": plan_items,
                "source_refs": source_refs,
                "confidence": 0.3,
                "warnings": [
                    "Plan items are disabled until a reviewer confirms flow scope, order, and direct API coverage"
                ],
            }
        )
    return test_cases, flows, test_plans


def _section_items(document: dict[str, Any], section: str) -> list[dict[str, Any]]:
    value: Any = document
    for part in section.split("."):
        value = value.get(part, {}) if isinstance(value, dict) else {}
    return value if isinstance(value, list) else []


def _keyed(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("key") or item.get("path")): item
        for item in items
        if isinstance(item, dict) and (item.get("key") or item.get("path"))
    }


def change_summary(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    sections = (
        "interfaces.http",
        "interfaces.ws",
        "api_templates",
        "assertion_definitions",
        "features",
        "test_cases",
        "flow_documents.documents",
        "flows",
        "test_plans",
    )
    result: dict[str, Any] = {}
    for section in sections:
        before = _keyed(_section_items(previous, section))
        after = _keyed(_section_items(current, section))
        created = sorted(set(after) - set(before))
        deleted = sorted(set(before) - set(after))
        updated = sorted(key for key in set(before) & set(after) if before[key] != after[key])
        result[section] = {
            "created": created,
            "updated": updated,
            "deleted": deleted,
            "unchanged": len(set(before) & set(after)) - len(updated),
        }
    return result


def decide_import(
    current: dict[str, Any], previous_path: str | None, version: str
) -> dict[str, Any]:
    if not previous_path:
        return {
            "mode": "create",
            "version": version,
            "previous_version": None,
            "changed_sections": [],
            "summary": {},
            "reason": "No previous manifest was supplied",
        }
    try:
        previous = load_import_source(Path(previous_path))
    except (ModuleBundleError, OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Unable to read previous manifest: {exc}") from None
    if not isinstance(previous, dict):
        raise SystemExit("Previous manifest root must be an object")
    previous_project = previous.get("project") if isinstance(previous.get("project"), dict) else {}
    current_project = current.get("project") if isinstance(current.get("project"), dict) else {}
    if previous_project.get("key") != current_project.get("key"):
        return {
            "mode": "create",
            "version": version,
            "previous_version": previous.get("package_version"),
            "changed_sections": ["project"],
            "summary": {},
            "reason": "Project key changed",
        }

    summary = change_summary(previous, current)
    if previous.get("project") != current.get("project"):
        summary["project"] = {
            "created": [],
            "updated": ["project"],
            "deleted": [],
            "unchanged": 0,
        }
    if previous.get("architecture") != current.get("architecture"):
        summary["architecture"] = {
            "created": [],
            "updated": ["architecture"],
            "deleted": [],
            "unchanged": 0,
        }
    if previous.get("service_topology") != current.get("service_topology"):
        summary["service_topology"] = {
            "created": [],
            "updated": ["service_topology"],
            "deleted": [],
            "unchanged": 0,
        }
    changed_sections = [
        section
        for section, changes in summary.items()
        if changes["created"] or changes["updated"] or changes["deleted"]
    ]
    previous_version_raw = str(
        previous.get("package_version")
        or (previous.get("import_decision") or {}).get("version")
        or ""
    )
    previous_version = normalize_package_version(previous_version_raw) if previous_version_raw.strip() else ""
    if previous_version and previous_version != version:
        mode = "new_version"
        reason = "Test plan version changed"
    elif changed_sections:
        mode = "update"
        reason = "Stable interface or business-flow keys changed"
    else:
        mode = "unchanged"
        reason = "No stable-key content changed"
    return {
        "mode": mode,
        "version": version,
        "previous_version": previous_version or None,
        "changed_sections": changed_sections,
        "summary": summary,
        "reason": reason,
    }


def _scan_output_paths(
    args: argparse.Namespace,
    root: Path,
    storage: dict[str, Any],
    package_version: str,
) -> tuple[Path, Path, Path]:
    default_manifest_path, default_archive_path = storage_paths(
        root, storage, package_version
    )
    output_path = Path(args.output).expanduser() if args.output else default_manifest_path
    if not output_path.is_absolute():
        output_path = Path.cwd() / output_path
    output_path = output_path.resolve()
    if args.modules_dir:
        modules_directory = Path(args.modules_dir).expanduser()
        if not modules_directory.is_absolute():
            modules_directory = root / modules_directory
        modules_directory = modules_directory.resolve()
    elif output_path == default_manifest_path.resolve():
        modules_directory = output_path.parent
    else:
        modules_directory = output_path.parent / f"{output_path.stem}.modules"
    return output_path, modules_directory, default_archive_path.resolve()


def scan(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.root).expanduser().resolve()
    if not root.is_dir():
        raise SystemExit(f"Project root is not a directory: {root}")
    config, config_path = load_project_config(root, args.config)
    raw_project = config.get("project") if isinstance(config.get("project"), dict) else {}
    project_metadata = normalize_project_metadata(config.get("project"))
    configured_success_assertions = normalize_success_assertions(
        config.get("success_assertions")
    )
    configured_api_grouping = normalize_api_grouping(
        config.get("api_grouping", config.get("api_groups"))
    )
    configured_service_topology = normalize_service_topology(
        config.get("service_topology", config.get("services"))
    )
    api_templates = normalize_api_templates(config.get("api_templates"))
    template_discovery = normalize_api_template_discovery(
        config.get("api_template_discovery")
    )
    flow_document_config = normalize_flow_documents(config.get("flow_documents"))
    openapi_config = normalize_openapi_config(config.get("openapi"))
    configured_variables = config.get("variables")
    if configured_variables is None and isinstance(raw_project, dict):
        configured_variables = raw_project.get("variables")
    project_variables = normalize_project_variables(
        configured_variables, require_base_url=config_path is not None
    )
    version_info = resolve_package_version(root, config, args.plan_version)
    package_version = str(version_info["value"])
    project_key = args.project_key or project_metadata.get("key") or slug(root.name)
    project_name = args.project_name or project_metadata.get("name") or root.name
    storage = normalize_storage(args.storage_dir or config.get("storage"))
    output_path, modules_directory, default_archive_path = _scan_output_paths(
        args, root, storage, package_version
    )
    default_manifest_path = storage_paths(root, storage, package_version)[0]
    storage_base = (
        default_manifest_path.parent.parent
        if storage.get("versioned", True)
        else default_manifest_path.parent
    )
    excluded_roots = tuple({storage_base.resolve(), modules_directory.resolve()})
    interfaces: dict[str, dict[str, dict[str, Any]]] = {"http": {}, "ws": {}}
    features: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []
    for service in configured_service_topology["services"]:
        for source_root in service.get("source_roots", []):
            if not (root / source_root).exists():
                warnings.append(
                    f"service_topology service {service['key']} source_root does not exist: {source_root}"
                )
    files = discover_files(root, excluded_roots)
    language = resolve_language(root, config, files, args.language)
    router_prefixes = discover_router_prefixes(files)
    spring_context_candidates, spring_context_warnings = discover_spring_context_paths(root, files)
    warnings.extend(spring_context_warnings)
    java_schemas = build_java_type_schemas(files, language["code"])
    for path in files:
        text = read_text(path)
        parse_python_routes(text, path, root, interfaces, router_prefixes, language["code"])
        context_prefix = None
        context_refs: list[dict[str, Any]] = []
        configured_service, service_warnings = resolve_configured_service(
            path, root, configured_service_topology
        )
        warnings.extend(service_warnings)
        configured_service_key = (
            str(configured_service.get("key")) if configured_service else None
        )
        if path.suffix.lower() in {".java", ".kt"}:
            context_prefix, context_refs, context_warnings = resolve_spring_context_path(
                path, spring_context_candidates
            )
            warnings.extend(context_warnings)
            context_prefix, context_refs, configured_context_warnings = (
                configured_service_context_path(
                    configured_service, context_prefix, context_refs
                )
            )
            warnings.extend(configured_context_warnings)
        parse_spring_routes(
            text,
            path,
            root,
            interfaces,
            java_schemas,
            context_prefix=context_prefix if path.suffix.lower() in {".java", ".kt"} else None,
            context_refs=context_refs if path.suffix.lower() in {".java", ".kt"} else None,
            language=language["code"],
            service_key=configured_service_key,
        )
        parse_call_routes(text, path, root, interfaces, language["code"])
        parse_websocket_routes(
            text,
            path,
            root,
            interfaces,
            context_prefix=context_prefix if path.suffix.lower() in {".java", ".kt"} else None,
            context_refs=context_refs if path.suffix.lower() in {".java", ".kt"} else None,
            language=language["code"],
            service_key=configured_service_key,
        )
        parse_frontend_routes(text, path, root, features)

    api_document_sources: list[dict[str, Any]] = []
    local_sources = [
        {"path": document, "required": True, "source": "cli"}
        for document in args.openapi
    ] + [
        {**document, "source": "project_config"}
        for document in openapi_config["documents"]
    ]
    explicit_documents: set[str] = set()
    for configured_document in local_sources:
        path = Path(str(configured_document["path"])).expanduser()
        if not path.is_absolute():
            path = root / path
        path = path.resolve()
        explicit_documents.add(str(path))
        if not path.is_file():
            message = f"Configured OpenAPI document does not exist: {path}"
            if configured_document.get("required", True):
                raise SystemExit(message)
            warnings.append(message)
            continue
        load_openapi(
            path,
            root,
            interfaces,
            warnings,
            language["code"],
            required=bool(configured_document.get("required", True)),
        )
        api_document_sources.append(
            {
                "kind": "file",
                "value": _relative_source_path(path, root),
                "source": configured_document["source"],
            }
        )
    if openapi_config["auto_discover"]:
        for path in files:
            if (
                path.name.lower() in DEFAULT_API_DOCUMENT_NAMES
                and str(path.resolve()) not in explicit_documents
            ):
                load_openapi(path, root, interfaces, warnings, language["code"])
                api_document_sources.append(
                    {
                        "kind": "file",
                        "value": _relative_source_path(path, root),
                        "source": "auto_discovery",
                    }
                )

    runtime_sources = [
        {"url": value, "required": True, "source": "cli"}
        for value in args.openapi_url
    ] + [
        {**value, "source": "project_config"}
        for value in openapi_config["urls"]
    ] + [
        {**value, "source": "framework_runtime_discovery"}
        for value in runtime_openapi_urls(openapi_config, project_variables, files)
    ]
    seen_urls: set[str] = set()
    runtime_defaults = openapi_config["runtime_discovery"]
    for configured_url in runtime_sources:
        url = str(configured_url["url"])
        if url in seen_urls:
            continue
        seen_urls.add(url)
        load_openapi_url(
            url,
            root,
            interfaces,
            warnings,
            language["code"],
            timeout_seconds=float(
                configured_url.get(
                    "timeout_seconds", runtime_defaults["timeout_seconds"]
                )
            ),
            max_bytes=int(
                configured_url.get("max_bytes", runtime_defaults["max_bytes"])
            ),
            required=bool(configured_url.get("required", False)),
        )
        api_document_sources.append(
            {
                "kind": "url",
                "value": url,
                "source": configured_url["source"],
            }
        )

    if not api_templates and template_discovery["enabled"]:
        discovered_templates, template_warnings = discover_api_templates(
            files, root, language["code"]
        )
        api_templates = normalize_api_templates(discovered_templates)
        warnings.extend(template_warnings)
    if not api_templates:
        warnings.append(
            "No reusable API template was configured or statically discovered; APIs have no template_key"
        )

    finalize_http_request_schemas(interfaces)
    apply_api_template_bindings(interfaces, api_templates)
    assign_api_group_paths(
        interfaces, root, configured_api_grouping, configured_service_topology
    )
    success_code_candidates, success_code_warnings = discover_success_code_values(root, files)
    warnings.extend(success_code_warnings)
    success_assertions = build_success_assertion_assets(
        interfaces, success_code_candidates, configured_success_assertions
    )
    add_inferred_features(interfaces, features)
    interface_keys = {
        str(item["key"])
        for protocol in ("http", "ws")
        for item in interfaces[protocol].values()
    }
    flow_document_context, documented_flows = load_flow_documents(
        root, flow_document_config, interface_keys, warnings
    )
    test_cases, flows, test_plans = build_assets(
        interfaces,
        features,
        package_version,
        project_key,
        documented_flows,
    )
    localize_assets(interfaces, features, test_cases, flows, test_plans, language)
    if not interfaces["http"] and not interfaces["ws"]:
        warnings.append("No HTTP or WebSocket interfaces were discovered")
    generated_project_description = (
        "由项目静态扫描生成的导入草稿，接口、流程和计划需人工审核。"
        if language["code"].lower().startswith("zh")
        else "Generated from static project scanning; review interfaces, flows, and plans before import."
    )
    storage_info = storage_metadata(root, storage, package_version)
    storage_info.update(
        {
            "manifest_path": _relative_source_path(output_path, root),
            "modules_directory": _relative_source_path(modules_directory, root),
            "archive_path": _relative_source_path(
                modules_directory / default_archive_path.name, root
            ),
        }
    )
    manifest = {
        "format": "qa-platform-import",
        "version": "1.0",
        "package_version": package_version,
        "language": language,
        "storage": storage_info,
        "project": {
            "key": project_key,
            "name": project_name,
            "description": project_metadata.get(
                "description", generated_project_description
            ),
            "language": language["code"],
            "variables": project_variables,
        },
        "source": {
            "repository": "local",
            "root_name": root.name,
            "commit": git_commit(root),
            "scanned_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "file_count": len(files),
            "release_version": version_info,
            "api_documents": api_document_sources,
        },
        "interfaces": {
            "http": sorted(interfaces["http"].values(), key=lambda item: item["key"]),
            "ws": sorted(interfaces["ws"].values(), key=lambda item: item["key"]),
        },
        "api_templates": api_templates,
        "api_grouping": configured_api_grouping,
        "service_topology": configured_service_topology,
        "api_template_discovery": template_discovery,
        "assertion_definitions": success_assertions["assertion_definitions"],
        "success_assertions": {
            "source": success_assertions["source"],
            "detected_success_codes": success_assertions["detected_success_codes"],
            "success_assertion_keys": success_assertions["success_assertion_keys"],
            "default_assertions": success_assertions["default_assertions"],
        },
        "features": sorted(features.values(), key=lambda item: item["key"]),
        "test_cases": test_cases,
        "flow_documents": flow_document_context,
        "flows": flows,
        "test_plans": test_plans,
        "architecture": detect_architecture(root, files),
        "warnings": sorted(set(warnings)),
    }
    if config_path:
        manifest["source"]["config_path"] = _relative_source_path(config_path, root)
    previous_manifest = args.previous_manifest
    if not previous_manifest and (modules_directory / "manifest.json").is_file():
        previous_manifest = str(modules_directory)
    elif not previous_manifest and output_path.is_file():
        previous_manifest = str(output_path)
    manifest["import_decision"] = decide_import(
        manifest, previous_manifest, package_version
    )
    manifest["warnings"] = sorted(
        set(manifest["warnings"] + manifest["architecture"].get("warnings", []))
    )
    return manifest


def _relative_source_path(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def main() -> int:
    args = parse_args()
    manifest = scan(args)
    root = Path(args.root).expanduser().resolve()
    storage = normalize_storage(manifest.get("storage"))
    output, modules_directory, _default_archive = _scan_output_paths(
        args, root, storage, str(manifest["package_version"])
    )
    bundle = write_module_bundle(
        manifest, modules_directory, compatibility_path=output
    )
    print(json.dumps({"output": str(output), "modules": bundle["directory"], "module_manifest": bundle["manifest"], "http": len(manifest["interfaces"]["http"]), "ws": len(manifest["interfaces"]["ws"]), "api_templates": len(manifest["api_templates"]), "flow_documents": len(manifest["flow_documents"]["documents"]), "features": len(manifest["features"]), "test_cases": len(manifest["test_cases"]), "flows": len(manifest["flows"]), "test_plans": len(manifest["test_plans"]), "warnings": len(manifest["warnings"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
