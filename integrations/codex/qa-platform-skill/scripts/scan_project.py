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
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from parameter_protocol import (
    add_parameters,
    add_path_parameters,
    normalize_openapi_parameter,
    parameter_from_schema,
    parameters_from_object_schema,
)
from project_config import (
    load_project_config,
    normalize_package_version,
    normalize_project_variables,
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
LITERAL_RE = re.compile(r"['\"](?P<value>[^'\"]+)['\"]")
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
JAVA_TYPE_DECL_RE = re.compile(r"\b(?P<kind>class|record)\s+(?P<name>[A-Za-z_$][\w$]*)\b")
JAVA_METHOD_DECL_RE = re.compile(
    r"(?m)^\s*(?:(?:public|protected|private|static|final|default|abstract|synchronized)\s+)*"
    r"(?:<[^>]+>\s+)?[A-Za-z_$][\w$.$<>, ?\[\]]*\s+(?P<name>[A-Za-z_$][\w$]*)\s*\("
)
JAVA_REQUIRED_ANNOTATION_RE = re.compile(r"@(?:[\w$.]+\.)?(?:NotNull|NotBlank|NotEmpty|NonNull)\b")
JAVA_MULTIPART_TYPE_RE = re.compile(r"\b(?:MultipartFile|Part|FilePart)\b")


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
    """Resolve the nearest module config, warning when profiles disagree."""
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
        help="Previous scan manifest used to decide update vs new test version",
    )
    parser.add_argument(
        "--openapi",
        action="append",
        default=[],
        help="Additional local OpenAPI JSON/YAML document; may be repeated",
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
) -> dict[str, Any] | None:
    path = path.strip()
    if not path or not path.startswith(("/", "ws://", "wss://", "http://", "https://")):
        return None
    method = method.upper() if method else None
    key_path = path
    identity = interface_key(protocol, method, key_path)
    bucket = interfaces[protocol]
    item = next(
        (candidate for candidate in bucket.values() if candidate.get("identity_key") == identity),
        None,
    )
    if item is None:
        candidate_key = business_key or derive_business_key(
            protocol, method, key_path, name=name, operation_id=operation_id
        )
        used_keys = {str(candidate.get("key")) for candidate in bucket.values()}
        unique_key = candidate_key
        if unique_key in used_keys:
            suffix = (method or "ws").lower()
            unique_key = f"{candidate_key}:{suffix}"
            counter = 2
            while unique_key in used_keys:
                unique_key = f"{candidate_key}:{suffix}:{counter}"
                counter += 1
        normalized_name = str(name or "").strip()
        item = {
            "key": unique_key,
            "business_key": candidate_key,
            "identity_key": identity,
            "protocol": protocol,
            "name": normalized_name or (f"{method} {path}" if method else path),
            "_name_source": "source" if normalized_name else "fallback",
            "description": str(description or "").strip(),
            "service": root.name,
            "parameters": [],
            "request_schema": {},
            "response_schema": {},
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
        bucket[identity] = item
    elif business_key and item.get("business_key") != business_key:
        used_keys = {
            str(candidate.get("key"))
            for candidate in bucket.values()
            if candidate is not item
        }
        unique_key = business_key
        if unique_key in used_keys:
            suffix = (method or "ws").lower()
            unique_key = f"{business_key}:{suffix}"
            counter = 2
            while unique_key in used_keys:
                unique_key = f"{business_key}:{suffix}:{counter}"
                counter += 1
        item["key"] = unique_key
        item["business_key"] = business_key
    add_ref(item, ref)
    item["confidence"] = max(float(item.get("confidence", 0)), confidence)
    if item.get("discovery_method") == "inferred" and discovery_method != "inferred":
        item["discovery_method"] = discovery_method
    normalized_name = str(name or "").strip()
    if normalized_name and item.get("_name_source") != "source":
        item["name"] = normalized_name
        item["_name_source"] = "source"
    normalized_description = str(description or "").strip()
    if normalized_description and not str(item.get("description") or "").strip():
        item["description"] = normalized_description
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


def _java_doc_summary(value: str) -> str:
    """Extract the first human-facing sentence from a nearby JavaDoc block."""
    lines: list[str] = []
    for raw_line in value.splitlines():
        line = re.sub(r"^\s*\*?\s?", "", raw_line).strip()
        if not line or line.startswith("@"):
            if lines and line.startswith("@"):
                break
            continue
        line = JAVA_DOC_LINK_RE.sub(r"\1", line)
        line = JAVA_DOC_HTML_RE.sub(" ", line)
        line = " ".join(line.split())
        if line:
            lines.append(line)
    text = " ".join(lines)
    if not text:
        return ""
    sentence = re.split(r"(?<=[。！？.!?])\s*", text, maxsplit=1)[0]
    return sentence.strip().rstrip("。！？.!?").strip()


def _java_doc_before(text: str, position: int) -> str:
    """Return a JavaDoc summary when it belongs to the declaration at position."""
    start = max(0, position - 8_000)
    prefix = text[start:position]
    matches = list(JAVA_DOC_RE.finditer(prefix))
    if not matches:
        return ""
    match = matches[-1]
    gap = prefix[match.end() :]
    # A closing brace or semicolon means the comment belongs to a preceding
    # declaration rather than the current class/method annotations.
    if re.search(r"[};]", gap) or gap.count("\n") > 48:
        return ""
    return _java_doc_summary(match.group("body"))


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
    class_summary = class_summary.strip() or _java_identifier_label(class_identifier, language)
    method_summary = method_summary.strip() or _java_identifier_label(method_identifier, language)
    if method_summary and class_summary:
        if method_summary == class_summary or method_summary in class_summary:
            return class_summary, class_summary
        if class_summary in method_summary:
            return method_summary, method_summary
        return f"{class_summary} - {method_summary}", f"{class_summary}。{method_summary}。"
    if method_summary:
        return method_summary, method_summary
    if class_summary:
        return class_summary, class_summary
    return None, None


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


def _java_declaration(value: str) -> tuple[str, str] | None:
    clean = _strip_java_annotations(value).strip().rstrip(",;")
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
    return {"type": "object"}


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


def _java_parameter_metadata(value: str, schema: dict[str, Any]) -> tuple[str, Any | None, Any | None]:
    description = _annotation_string(value, "Schema", "description") or _annotation_string(
        value, "Parameter", "description"
    ) or ""
    example = _annotation_string(value, "Schema", "example") or _annotation_string(
        value, "Parameter", "example"
    )
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
        required=bool(JAVA_REQUIRED_ANNOTATION_RE.search(value)),
        description=description,
        language=language,
        **kwargs,
    )
    if not parameter:
        return None
    property_schema = {
        key: deepcopy(item)
        for key, item in parameter.items()
        if key not in {"name", "in", "required"}
    }
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
    """Build a small DTO index for Spring request-body top-level properties."""
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
    return schemas


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
        return method_summary, method_summary

    context = class_summary or _java_identifier_label(class_identifier, language)
    if not context:
        return None, None
    chinese = str(language or "").lower().startswith("zh")
    lower_context = context.lower()
    already_endpoint = "websocket" in lower_context or (chinese and "接口" in context)
    if chinese:
        name = context if already_endpoint else f"{context} WebSocket接口"
        description = f"{context}的 WebSocket 通信接口；消息契约需人工审核。"
    else:
        name = context if already_endpoint else f"{context} WebSocket endpoint"
        description = f"{context} WebSocket endpoint; message contract requires review."
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
) -> None:
    collected: list[dict[str, Any]] = []
    for raw in raw_parameters:
        declaration = _java_declaration(raw)
        if not declaration:
            continue
        type_name, fallback_name = declaration
        body_args = _annotation_arguments(raw, "RequestBody")
        if body_args is not None:
            body_schema = _resolve_java_body_schema(type_name, java_schemas)
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
) -> None:
    if path.suffix.lower() not in {".java", ".kt"}:
        return
    class_prefixes: list[tuple[int, str, str]] = []
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
            )
        )
    for declaration_match in re.finditer(
        r"(?m)^\s*(?:public\s+|protected\s+|private\s+|abstract\s+|final\s+|static\s+)*(?:class|interface)\s+[A-Za-z_$][\w$]*",
        text,
    ):
        declaration_position = declaration_match.start()
        if any(abs(declaration_position - mapped) < 80 for mapped in mapped_declaration_positions):
            continue
        class_prefixes.append((declaration_position, "", _java_doc_before(text, declaration_position)))

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
        method_summary = _java_doc_before(text, match.start())
        api_name, api_description = _spring_name_and_description(
            class_summary,
            method_summary,
            class_identifier=_java_class_name_before(text, match.start()),
            method_identifier=_java_method_name_after(text, match.end()),
            language=language,
        )
        route = join_route(context_prefix, join_route(class_prefix, route))
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
            )
            if item:
                for context_ref in context_refs or []:
                    add_ref(item, context_ref)
                _add_spring_parameters(item, signature_parameters, java_schemas or {}, language)


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
    return result


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


def _explicit_business_key(value: dict[str, Any]) -> str | None:
    candidate = value.get("x-business-key") or value.get("x_business_key")
    return str(candidate).strip() if isinstance(candidate, str) and candidate.strip() else None


def _add_openapi_parameters(
    item: dict[str, Any],
    document: dict[str, Any],
    raw_parameters: Any,
    warnings: list[str],
    language: str | None = "en",
) -> None:
    collected: list[dict[str, Any]] = []
    for raw in _api_records(raw_parameters):
        parameter = _resolve_openapi_object(document, raw, warnings)
        location = str(parameter.get("in") or "").lower()
        if location == "body":
            schema = _resolve_openapi_schema(document, parameter.get("schema"), warnings)
            if schema:
                item.setdefault("source_request_schema", deepcopy(parameter.get("schema") or {}))
                item["request_schema"] = schema
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
        if isinstance(schema, dict):
            parameter["schema"] = _resolve_openapi_schema(document, schema, warnings)
        normalized = normalize_openapi_parameter(parameter, language=language)
        if normalized:
            collected.append(normalized)
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
    _content_type, media = selected
    raw_schema = media.get("schema")
    schema = _resolve_openapi_schema(document, raw_schema, warnings)
    if not schema:
        _add_item_warning(item, "JSON request body has no readable schema")
        return
    item["source_request_schema"] = deepcopy(raw_schema) if isinstance(raw_schema, dict) else {}
    item["request_schema"] = schema
    body_parameters = parameters_from_object_schema(schema, language=language)
    if body_parameters:
        add_parameters(item, body_parameters)
    else:
        _add_item_warning(
            item,
            "JSON request body is not a top-level object; provide a request override when executing it",
        )


def _response_schema_from_operation(
    document: dict[str, Any], raw_responses: Any, warnings: list[str]
) -> dict[str, Any]:
    if not isinstance(raw_responses, dict):
        return {}
    for status in sorted(raw_responses, key=str):
        if not str(status).startswith(("2", "3")):
            continue
        response = _resolve_openapi_object(document, raw_responses[status], warnings)
        if isinstance(response.get("schema"), dict):  # Swagger 2
            return _resolve_openapi_schema(document, response["schema"], warnings)
        selected = _json_content(document, response.get("content"), warnings)
        if selected and isinstance(selected[1].get("schema"), dict):
            return _resolve_openapi_schema(document, selected[1]["schema"], warnings)
    return {}


def load_openapi(
    path: Path,
    root: Path,
    interfaces: dict[str, dict[str, dict[str, Any]]],
    warnings: list[str],
    language: str | None = "en",
) -> None:
    try:
        if path.suffix.lower() in {".yaml", ".yml"}:
            try:
                import yaml  # type: ignore
            except ImportError:
                warnings.append(f"Skipped YAML OpenAPI without PyYAML: {path}")
                return
            document = yaml.safe_load(read_text(path))
        else:
            document = json.loads(read_text(path))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        warnings.append(f"Could not read OpenAPI document {path}: {exc}")
        return
    if not isinstance(document, dict):
        warnings.append(f"API document must be an object: {path}")
        return
    ref = source_ref(path, root, 1)
    if not isinstance(document.get("paths"), dict):
        channels = document.get("channels")
        if not isinstance(channels, dict):
            warnings.append(f"Document has no OpenAPI paths or AsyncAPI channels: {path}")
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
            item = ensure_interface(
                interfaces,
                "http",
                route,
                root,
                ref,
                method=method.upper(),
                name=operation.get("summary") or operation.get("operationId"),
                operation_id=operation.get("operationId"),
                business_key=explicit_business_key,
                discovery_method="openapi",
                confidence=0.98,
                language=language,
            )
            if item is None:
                continue
            item["operation_id"] = operation.get("operationId")
            tags = operation.get("tags") if isinstance(operation.get("tags"), list) else []
            item["tags"] = sorted(
                set(item.get("tags", [])) | {str(tag) for tag in tags if isinstance(tag, str)}
            )
            _add_openapi_parameters(
                item, document, path_item.get("parameters"), warnings, language
            )
            _add_openapi_parameters(
                item, document, operation.get("parameters"), warnings, language
            )
            _add_openapi_request_body(
                item, document, operation.get("requestBody"), warnings, language
            )
            response_schema = _response_schema_from_operation(
                document, operation.get("responses"), warnings
            )
            if response_schema:
                item["response_schema"] = response_schema
            item["auth"] = "required" if operation.get("security") or document.get("security") else "unknown"


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
                item.get("business_key") or derive_business_key(protocol, item.get("method"), path)
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
    "client": "客户端",
    "config": "配置",
    "conversation": "会话",
    "create": "创建",
    "add": "新增",
    "delete": "删除",
    "detail": "详情",
    "download": "下载",
    "edit": "编辑",
    "entities": "实体",
    "entity": "实体",
    "export": "导出",
    "execution": "执行",
    "explain": "解释",
    "field": "字段",
    "fields": "字段",
    "lineage": "血缘",
    "metadata": "元数据",
    "meta": "元数据",
    "health": "健康检查",
    "http": "HTTP",
    "import": "导入",
    "list": "列表",
    "login": "登录",
    "logout": "登出",
    "message": "消息",
    "manage": "管理",
    "management": "管理",
    "order": "订单",
    "permission": "权限",
    "plan": "计划",
    "pivot": "透视",
    "preview": "预览",
    "project": "项目",
    "query": "查询",
    "refresh": "刷新",
    "register": "注册",
    "remove": "删除",
    "role": "角色",
    "rule": "规则",
    "rules": "规则",
    "search": "搜索",
    "send": "发送",
    "setting": "设置",
    "system": "系统",
    "test": "测试",
    "transform": "转换",
    "update": "更新",
    "upload": "上传",
    "user": "用户",
    "validate": "校验",
    "value": "值",
    "key": "键",
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
        name = str(item.get("name") or "").strip()
        if name:
            grouped.setdefault(name, []).append(item)
    for name, items in grouped.items():
        if len(items) < 2:
            continue
        used_names: set[str] = set()
        for item in sorted(items, key=lambda value: str(value.get("key") or "")):
            protocol = str(item.get("protocol") or "http").upper()
            method = str(item.get("method") or protocol).upper()
            endpoint = str(item.get("path") or item.get("url") or item.get("key") or "")
            candidate = f"{name}（{method} {endpoint}）"
            counter = 2
            while candidate in used_names:
                candidate = f"{name}（{method} {endpoint} #{counter}）"
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
        return

    interface_labels: dict[str, str] = {}
    for protocol in ("http", "ws"):
        for item in interfaces[protocol].values():
            business_key = str(item.get("business_key") or item.get("key") or "")
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
        feature_key = f"feature:{str(flow.get('key', '')).removeprefix('flow:')}"
        label = feature_labels.get(feature_key, chinese_business_label(str(flow.get("key") or "测试")))
        flow["name"] = f"{label}测试流程"
        flow["description"] = "由接口与功能分组生成的待审核测试流程。"
        for step in flow.get("steps", []):
            step["name"] = interface_labels.get(str(step.get("interface_key") or ""), "接口")

    for plan in test_plans:
        version = str(plan.get("version") or "当前")
        plan["name"] = f"{version}版本测试计划"
        plan["description"] = "按版本汇总测试流程和未被流程覆盖接口的待审核测试计划。"


def build_assets(
    interfaces: dict[str, dict[str, dict[str, Any]]],
    features: dict[str, dict[str, Any]],
    plan_version: str,
    project_key: str,
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

    flows: list[dict[str, Any]] = []
    covered_interface_keys: set[str] = set()
    for feature in sorted(features.values(), key=lambda item: item["key"]):
        related = sorted(set(feature.get("related_interfaces", [])))
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
        str(item["key"]): item
        for item in items
        if isinstance(item, dict) and item.get("key")
    }


def change_summary(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    sections = (
        "interfaces.http",
        "interfaces.ws",
        "features",
        "test_cases",
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
        previous = json.loads(Path(previous_path).expanduser().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
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


def scan(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.root).expanduser().resolve()
    if not root.is_dir():
        raise SystemExit(f"Project root is not a directory: {root}")
    config, config_path = load_project_config(root, args.config)
    configured_success_assertions = normalize_success_assertions(
        config.get("success_assertions")
    )
    project_variables = normalize_project_variables(
        config.get("variables"), require_base_url=config_path is not None
    )
    version_info = resolve_package_version(root, config, args.plan_version)
    package_version = str(version_info["value"])
    project_key = args.project_key or slug(root.name)
    project_name = args.project_name or root.name
    storage = normalize_storage(args.storage_dir or config.get("storage"))
    default_manifest_path, _default_archive_path = storage_paths(root, storage, package_version)
    storage_base = (
        default_manifest_path.parent.parent
        if storage.get("versioned", True)
        else default_manifest_path.parent
    )
    interfaces: dict[str, dict[str, dict[str, Any]]] = {"http": {}, "ws": {}}
    features: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []
    files = discover_files(root, (storage_base,))
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
        if path.suffix.lower() in {".java", ".kt"}:
            context_prefix, context_refs, context_warnings = resolve_spring_context_path(
                path, spring_context_candidates
            )
            warnings.extend(context_warnings)
        parse_spring_routes(
            text,
            path,
            root,
            interfaces,
            java_schemas,
            context_prefix=context_prefix if path.suffix.lower() in {".java", ".kt"} else None,
            context_refs=context_refs if path.suffix.lower() in {".java", ".kt"} else None,
            language=language["code"],
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
        )
        parse_frontend_routes(text, path, root, features)
    for document in args.openapi:
        path = Path(document).expanduser()
        if not path.is_absolute():
            path = root / path
            load_openapi(path.resolve(), root, interfaces, warnings, language["code"])
    explicit_documents: set[str] = set()
    for document in args.openapi:
        document_path = Path(document).expanduser()
        if not document_path.is_absolute():
            document_path = root / document_path
        explicit_documents.add(str(document_path.resolve()))
    for path in files:
        if path.name.lower() in DEFAULT_API_DOCUMENT_NAMES and str(path.resolve()) not in explicit_documents:
            load_openapi(path, root, interfaces, warnings, language["code"])
    success_code_candidates, success_code_warnings = discover_success_code_values(root, files)
    warnings.extend(success_code_warnings)
    success_assertions = build_success_assertion_assets(
        interfaces, success_code_candidates, configured_success_assertions
    )
    add_inferred_features(interfaces, features)
    test_cases, flows, test_plans = build_assets(
        interfaces, features, package_version, project_key
    )
    localize_assets(interfaces, features, test_cases, flows, test_plans, language)
    if not interfaces["http"] and not interfaces["ws"]:
        warnings.append("No HTTP or WebSocket interfaces were discovered")
    output_path = (
        Path(args.output).expanduser()
        if args.output
        else default_manifest_path
    )
    if not output_path.is_absolute():
        output_path = Path.cwd() / output_path
    output_path = output_path.resolve()
    project_description = (
        "由项目静态扫描生成的导入草稿，接口、流程和计划需人工审核。"
        if language["code"].lower().startswith("zh")
        else "Generated from static project scanning; review interfaces, flows, and plans before import."
    )
    manifest = {
        "format": "qa-platform-import",
        "version": "1.0",
        "package_version": package_version,
        "language": language,
        "storage": storage_metadata(root, storage, package_version),
        "project": {
            "key": project_key,
            "name": project_name,
            "description": project_description,
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
        },
        "interfaces": {
            "http": sorted(interfaces["http"].values(), key=lambda item: item["key"]),
            "ws": sorted(interfaces["ws"].values(), key=lambda item: item["key"]),
        },
        "assertion_definitions": success_assertions["assertion_definitions"],
        "assertion_profiles": success_assertions["assertion_profiles"],
        "success_assertions": {
            "source": success_assertions["source"],
            "detected_success_codes": success_assertions["detected_success_codes"],
            "profile_keys": success_assertions["profile_keys"],
            "default_profiles": success_assertions["default_profiles"],
        },
        "features": sorted(features.values(), key=lambda item: item["key"]),
        "test_cases": test_cases,
        "flows": flows,
        "test_plans": test_plans,
        "architecture": detect_architecture(root, files),
        "warnings": sorted(set(warnings)),
    }
    if config_path:
        manifest["source"]["config_path"] = _relative_source_path(config_path, root)
    previous_manifest = args.previous_manifest
    if not previous_manifest and output_path.is_file():
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
    output = (
        Path(args.output).expanduser()
        if args.output
        else storage_paths(root, storage, str(manifest["package_version"]))[0]
    )
    if not output.is_absolute():
        output = Path.cwd() / output
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "http": len(manifest["interfaces"]["http"]), "ws": len(manifest["interfaces"]["ws"]), "features": len(manifest["features"]), "test_cases": len(manifest["test_cases"]), "flows": len(manifest["flows"]), "test_plans": len(manifest["test_plans"]), "warnings": len(manifest["warnings"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
