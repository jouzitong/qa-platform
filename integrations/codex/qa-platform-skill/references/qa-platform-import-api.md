# qa-platform import API contract

The current qa-platform import service accepts a versioned ZIP as the raw request body. It creates a pending import session, returns a preview, and only changes project data after an explicit approval. The Skill prepares the archive and may call preview; it must not silently approve or mutate data.

## Endpoints

```text
POST /api/v1/imports/preview?project_id=<optional>
GET  /api/v1/imports/{import_id}
POST /api/v1/imports/{import_id}/approve
POST /api/v1/imports/{import_id}/reject
POST /api/v1/imports/one-click?project_id=<optional>
```

`project_id` is optional for a new project. Pass it when scanning an existing project so the preview can classify stable-key assets as create, update, or unchanged against that project.

The external `one-click` endpoint is a convenient entry point for partners or workspace actions. Despite its name, it creates a `pending` session and still requires `/approve`; it is not an approval bypass.

The Skill reads the project-local `.qa-platform.json` for project metadata, reusable assets, flow/API-document sources, project variables, and service settings. Its top-level service `base_url` defaults to `http://localhost:8000`, API prefix `/api/v1`, and the `preview` endpoint when omitted. `variables.base_url` is required for a valid project package. ZIP construction itself uses the generated module directory and does not make network requests; only an explicitly configured/enabled OpenAPI runtime scan performs read-only HTTP(S) fetches before packaging.

## Request

Send the ZIP bytes directly:

```text
Content-Type: application/zip
X-Import-Filename: qa-platform-import.zip
X-Import-Source: workspace       # local/workspace import
Body: <ZIP binary>
```

For the external entry point, use `X-Import-Source: external` (or a more specific partner channel). The filename is URL-decoded by the server and should end in `.zip`.

The current backend enforces archive safety limits and accepts JSON files only. It rejects RAR, encrypted archives, unsafe paths, invalid JSON, oversized archives, and archives with no readable JSON. RAR support is intentionally not claimed by this Skill.

## Archive contract

```text
manifest.json
project.json
api_templates.json
inventory.json
flow_documents.json
assertion_definitions.json
v1.0.0/
  api.json
  flow.json
  plans.json
```

The version directory may use the selected `package_version`. The importer recognizes the basenames `api.json`/`apis.json`, `flow.json`/`flows.json`, and `plans.json`/`test_plans.json` in any directory.

- `manifest.json`: package version, source, architecture evidence, import decision, and warnings.
- `project.json`: project name, description, and variables. `variables.base_url` is required and must be an `ip:port` value without `http://`; qa-platform adds the HTTP scheme when resolving it. An explicit gateway address may fill it only as a compatibility fallback.
- `api_templates.json`: reusable API templates imported before APIs; API `template_key` references resolve against their key/name.
- `inventory.json`: scanner-only `features` and `test_cases`; current qa-platform warns and skips these because it has no standalone models for them.
- `flow_documents.json`: configured source-document path, format, hash, size, usage, and structured flow keys. Source prose `content` is local AI context and is stripped before ZIP creation.
- `assertion_definitions.json`: success condition definitions, including the system status/body/message rules.
- APIs reference one success condition through `success_assertion_key`.
- `api.json`: HTTP and WebSocket API assets. API assets reference one success condition when available and retain `success_contract` as a compatibility fallback. The current platform also fills missing HTTP headers with `X-trade-id: {{ random.uuid(32) }}` and `Accept: application/json`.
- `flow.json`: flow assets whose steps reference API keys through `api_key`. Scanner-generated steps are disabled.
- `plans.json`: versioned plan assets whose items reference APIs or flows through `target_key`. Scanner-generated items are disabled.

The importer resolves `api_key` and `target_key` references before apply. Broken required references must remain preview errors and must not be applied.

## Response and review

The preview response contains an import ID, `pending` status, target project, package version, warnings/errors, and a summary of create/update/unchanged/error items. Review at least:

- project selection and version decision;
- HTTP/WS counts and low-confidence or unresolved routes;
- gateway address and whether it is `explicit` or `inferred`;
- API success contracts, request defaults, flow references, and disabled plan items;
- warnings for skipped features/test cases and unresolved references.

Approval:

```text
POST /api/v1/imports/{import_id}/approve
```

Approval applies project, API templates, success conditions, APIs, flows, and test plans in a transaction. It resolves references before commit and marks the session `applied`; failures roll back and mark the session `failed`.

Rejection:

```text
POST /api/v1/imports/{import_id}/reject
```

Rejection marks the pending session `rejected` and does not change project data. A non-pending session cannot be approved or rejected again.

## Idempotency and safety

Use stable `key` values generated by the scanner. Repeat scans should preserve the same interface, flow, and plan identities; changing `package_version` intentionally creates a new versioned plan identity. Never put tokens, cookies, passwords, private keys, or real authorization headers in the archive. Runtime values should be qa-platform variables such as `{{ access_token }}`.

The project-local configuration is non-secret JSON:

```json
{
  "base_url": "http://localhost:8000",
  "project": {
    "key": "order-system",
    "name": "Order System",
    "description": "订单系统测试资产"
  },
  "variables": {
    "base_url": "127.0.0.1:9764"
  },
  "api_prefix": "/api/v1",
  "project_id": null,
  "endpoint": "preview",
  "source": "workspace",
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
    "archive_filename": "qa-platform-import.zip"
  },
  "api_templates": [],
  "success_assertions": {
    "default_assertion": {
      "http": "config:http-success-status",
      "ws": "config:ws-success-messages"
    },
    "definitions": [
      {
        "key": "config:http-success-status",
        "name": "默认 HTTP 成功状态码",
        "engine": "expression",
        "config": {"expression": "response.status_code >= 200 and response.status_code <= 299"}
      },
      {
        "key": "config:ws-success-messages",
        "name": "默认 WebSocket 成功消息",
        "engine": "expression",
        "config": {"expression": "len(response.messages) >= 1"}
      }
    ]
  },
  "flow_documents": [
    {"path": "docs/test-flows.md", "required": true}
  ],
  "openapi": {
    "documents": [{"path": "docs/openapi.json", "required": true}],
    "urls": [],
    "auto_discover": true,
    "runtime_discovery": {
      "enabled": false,
      "scheme": "http",
      "paths": [],
      "timeout_seconds": 3,
      "max_bytes": 10485760
    }
  }
}
```

`publish_import.py` sends an existing ZIP to the configured preview or one-click endpoint. It never calls `/approve`; set `QA_PLATFORM_TOKEN` in the environment when the service requires a bearer token.
