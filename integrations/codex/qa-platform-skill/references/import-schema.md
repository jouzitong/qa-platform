# qa-platform import schema

The scanner emits a JSON document with `format: "qa-platform-import"` and a semver-like `version`. The first implementation targets version `1.0`.

## Top-level shape

```json
{
  "format": "qa-platform-import",
  "version": "1.0",
  "package_version": "0.1.2",
  "language": {
    "code": "zh-CN",
    "label": "中文",
    "source": "project_comments",
    "confidence": 0.9
  },
  "storage": {
    "directory": "releases",
    "versioned": true,
    "manifest_filename": "qa-platform-import.json",
    "archive_filename": "qa-platform-import.zip",
    "version": "0.1.2",
    "version_directory": "releases/0.1.2",
    "manifest_path": "releases/0.1.2/qa-platform-import.json",
    "archive_path": "releases/0.1.2/qa-platform-import.zip"
  },
  "project": {
    "key": "order-system",
    "name": "Order System",
    "description": "",
    "language": "zh-CN",
    "variables": {
      "base_url": "127.0.0.1:9764"
    }
  },
  "source": {
    "repository": "local",
    "root_name": "order-system",
    "commit": null,
    "scanned_at": "2026-08-03T10:00:00Z",
    "release_version": {
      "value": "0.1.2",
      "source": "maven.revision",
      "raw": "0.1.2-SNAPSHOT",
      "path": "pom.xml"
    }
  },
  "architecture": {
    "is_microservices": false,
    "type": "monolith_or_unknown",
    "confidence": 0.7,
    "gateway": {
      "detected": false,
      "address": null,
      "source_refs": [],
      "confidence": 0,
      "warnings": []
    },
    "services": [],
    "evidence": {},
    "warnings": []
  },
  "import_decision": {
    "mode": "create",
    "version": "0.1.2",
    "previous_version": null,
    "changed_sections": [],
    "summary": {},
    "reason": "No previous manifest was supplied"
  },
  "interfaces": {
    "http": [],
    "ws": []
  },
  "assertion_definitions": [],
  "assertion_profiles": [],
  "success_assertions": {
    "source": "project_config",
    "default_profiles": {"http": "config:http-success", "ws": "config:ws-success"},
    "detected_success_codes": [],
    "profile_keys": ["config:http-success", "config:ws-success"]
  },
  "features": [],
  "test_cases": [],
  "flows": [],
  "test_plans": [],
  "warnings": []
}
```

`version` is the schema format version. `package_version` is the test/release version used for generated plans and the version directory in the ZIP. They must not be conflated. `source.release_version` records the resolved value, the metadata source, and (when relevant) the raw source value. The resolver uses CLI/config overrides first, then Maven, Python, Node, Gradle, and a root version file. A terminal `-SNAPSHOT` is removed, while other qualifiers are preserved. `language` records the selected display language and its evidence; generated names/descriptions follow it while stable keys remain language-neutral. `storage` records where the scan manifest and archive are kept locally; it is metadata and does not grant the importer filesystem access.

## Stable keys

Use business-oriented keys for imported entities:

- API/WS: `user.auth.login`, `user.auth.logout`, or another dot-separated business key.
- Feature: `feature:<business-key>` or `page:<normalized-route>`.
- Test case: `case:<api-business-key>:smoke`.
- Flow: `flow:<feature-business-key>`.
- Test plan: `plan:<project-key>:<version-slug>:smoke` (exactly one per `package_version`).

Derive an API key from OpenAPI `operationId`/`x-business-key` first, then meaningful route segments after removing generic `api`/version prefixes. Keep at most four meaningful segments. If two routes produce the same key, append `:<method>` and then a numeric suffix. `identity_key` remains the protocol/method/path identity used to merge duplicate source references; it is not the display key.

Keys are external identifiers. qa-platform should persist the API/flow/plan `key` (or an equivalent external-key field) and use it for upsert and repeat-import detection. Names are display labels and are not safe deduplication keys.

## Interface fields

Every interface should include:

```json
{
  "key": "orders.list",
  "business_key": "orders.list",
  "identity_key": "http:GET:/api/orders",
  "protocol": "http",
  "method": "GET",
  "path": "/api/orders",
  "name": "List orders",
  "service": "order-service",
  "parameters": [],
  "request_schema": {},
  "response_schema": {},
  "assertion_profile_key": "config:http-success",
  "auth": "unknown",
  "tags": [],
  "source_refs": [
    {"file": "src/order/routes.py", "line": 32}
  ],
  "discovery_method": "source",
  "confidence": 0.9,
  "warnings": []
}
```

Use `protocol: "ws"` for WebSocket records. A WS record may use `url` instead of `path` and may include `handshake`, `messages`, and `receive_count`.

Do not place live authorization headers, cookies, passwords, or tokens in request examples. Use variable references or empty values.

## Executable parameter contract

`parameters` is not raw source metadata. It must contain qa-platform executable parameter objects, for example:

```json
[
  {"name": "id", "in": "path", "type": "integer", "required": true, "description": "Path parameter `id` (integer).", "example": 1},
  {"name": "page", "in": "query", "type": "integer", "required": false, "description": "Query parameter `page` (integer).", "example": 1, "default": 1},
  {"name": "name", "in": "body", "type": "string", "required": true, "description": "Request body parameter `name` (string).", "example": "example-name"}
]
```

The execution engine writes `path`, `query`, `header`, and top-level JSON `body` values into distinct request locations. `description` and `example` are mandatory in every generated parameter; `default` remains absent unless supported by source/config facts. Validate this array with `validate-import.py`; read [api-definition-protocol.md](api-definition-protocol.md) for required fields, source mappings, merge rules, defaults, security, and unsupported content types.

## Project-configured success assertions

`.qa-platform.json` can declare the default assertion profile and the assets needed to initialize it. `init_project_config.py` writes a safe HTTP/WS starter section. An AI may add project-specific definitions and profiles after inspecting source facts, but the result remains draft configuration for human review.

```json
{
  "success_assertions": {
    "default_profile": {"http": "config:http-success", "ws": "config:ws-success"},
    "definitions": [
      {"key": "config:http-success-status", "name": "默认 HTTP 成功状态码", "engine": "expression", "config": {"expression": "response.status_code >= 200 and response.status_code <= 299"}, "default_params": {}, "severity": "success", "message": "HTTP 状态码不在 200–299 范围内"}
    ],
    "profiles": [
      {"name": "config:http-success", "protocol": "http", "description": "项目默认 HTTP 成功断言集合", "is_default": true, "bindings": [{"assertion_id": "config:http-success-status", "enabled": true}]}
    ]
  }
}
```

Each configured default must reference a profile in the same config, use the matching protocol, and bind only declared definition keys. During scan, every HTTP/WS API receives its corresponding configured `assertion_profile_key`; invalid or missing referenced profiles fail validation instead of falling back silently. Projects without this section retain the legacy inferred-system profile for compatibility.

## Features, cases, and flows

Features describe discovered capabilities, not guaranteed business workflows:

```json
{
  "key": "feature:orders",
  "name": "Orders",
  "description": "",
  "entrypoints": ["/orders"],
  "related_interfaces": ["orders.list"],
  "preconditions": [],
  "source_refs": [],
  "confidence": 0.6,
  "warnings": []
}
```

Bootstrap test cases should be safe skeletons:

```json
{
  "key": "case:orders.list:smoke",
  "name": "Smoke: GET /api/orders",
  "type": "api_smoke",
  "target": {"interface_key": "orders.list"},
  "priority": "P1",
  "status": "draft",
  "origin": "scanner",
  "preconditions": [],
  "request": {},
  "assertions": [],
  "source_refs": [],
  "confidence": 0.5,
  "warnings": ["Request values and authentication are unresolved"]
}
```

Flows reference interfaces by key until the importer resolves them to database IDs:

```json
{
  "key": "flow:orders",
  "name": "Orders draft flow",
  "status": "draft",
  "origin": "scanner",
  "variables": {},
  "steps": [
    {
      "id": "step-1",
      "name": "GET /api/orders",
      "interface_key": "orders.list",
      "enabled": false,
      "request": {},
      "assertions": [],
      "extractors": []
    }
  ],
  "source_refs": [],
  "confidence": 0.3,
  "warnings": ["Step ordering is inferred"]
}
```

Generated manifests contain at most one plan. It carries the same `version` as `package_version`, references all generated flows by `target_key`, and may contain direct API items only for interfaces not covered by any flow:

```json
{
  "key": "plan:order-system:0-1-2:smoke",
  "version": "0.1.2",
  "name": "Order System 0.1.2 smoke plan",
  "status": "draft",
  "origin": "scanner",
  "items": [
    {"id": "flow-item-1", "type": "flow", "target_key": "flow:orders", "enabled": false},
    {"id": "api-item-1", "type": "api", "target_key": "health.check", "enabled": false}
  ],
  "warnings": ["Plan item is disabled until a reviewer confirms the flow"]
}
```

The scanner's `import_decision` is a comparison result, not an instruction to mutate the platform. The modes are `create`, `update`, `new_version`, and `unchanged`; a human still reviews the platform preview.

## Import mapping

Map `project` to `Project`, `assertion_definitions` to atomic assertion definitions, `assertion_profiles` to assertion profiles, `interfaces.http/ws` to `ApiDefinition`, `flows` to `TestFlow`, and `test_plans` to `TestPlan`. `project.variables.base_url` is required and must be an `ip:port` value without a URL scheme; qa-platform adds `http://` when resolving it. API `assertion_profile_key` values resolve to the imported or existing profile name and must match the configured default when `success_assertions.source` is `project_config`. `features` and `test_cases` are retained in the scanner JSON and ZIP `inventory.json`; the current qa-platform importer warns and skips them because there is no standalone feature or test-case model. The archive builder maps each API's `success_contract` into the API asset as a compatibility fallback.

## ZIP mapping

The archive consumed by the current import center is:

```text
manifest.json       # package_version, source, architecture, import_decision, warnings
project.json        # project metadata and variables
inventory.json      # scanner-only features and test_cases
assertion_definitions.json # atomic success assertion definitions
assertion_profiles.json    # API-referenced success assertion profiles
<version>/api.json  # HTTP and WS API assets
<version>/flow.json # flow assets with api_key references
<version>/plans.json# test plan assets with target_key references
```

The archive is sent as raw `application/zip` bytes. It is not a multipart upload, and RAR is not currently supported.

Apply imports in dependency order: project, API templates/assertion assets, interfaces, flows, then test plans. `features` and `test_cases` remain scanner inventory until the platform adds corresponding models. Resolve all API/flow references before committing. Reject unresolved required references rather than creating broken flow steps.
