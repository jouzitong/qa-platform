---
name: qa-platform-skill
description: Scan Python, Spring Boot/Java, Go, Node, and other common projects for HTTP and WebSocket interfaces; deterministically convert OpenAPI, Swagger, and AsyncAPI contracts into complete executable definitions including recursive request fields and response schemas; discover safe reusable API templates from project request and gateway configuration; read project-configured flow documents; generate editable module JSON files; and build or preview-publish a validated ZIP for qa-platform. Use when asked to inventory interfaces, bootstrap API tests, generate documented flows, decide update versus new test version, configure qa-platform assets, or import scan results.
---

# QA Platform Scanner

Use this skill to create a reproducible inventory of a project and prepare it for qa-platform. Keep scanning, normalization, version decisions, and platform import as separate concerns.

## Operating rules

- Treat source scanning as read-only. Do not modify the target project while discovering routes or pages. The explicit `init_project_config.py` command is the only bundled command that writes the project-local `.qa-platform.json`; package validation requires its `variables.base_url` project variable.
- Prefer existing OpenAPI, Swagger, or AsyncAPI documents, then inspect framework route declarations and frontend route configuration. Resolve local `$ref` objects, composed schemas, parameters, request bodies, response schemas, descriptions, constraints, defaults, and examples deterministically. Do not ask AI to recreate facts already present in a standard API document. The bundled scanner covers common Python decorators, Spring Boot annotations, Go router calls, Node routes, and Java/Node/Python WebSocket declarations; it is static analysis, not a guarantee that every dynamically generated route is discoverable.
- Read `.qa-platform.json` as the project-owned bootstrap contract. It may define `project`, `variables`, reusable `api_templates`, `api_template_discovery`, `success_assertions`, `flow_documents`, `openapi`, language, version, storage, and qa-platform publishing settings. Keep these values non-secret. Explicit `api_templates` take precedence; when the list is empty, source-based discovery is enabled by default and can be disabled with `api_template_discovery.enabled: false`.
- Use configured `openapi.documents` for local files and `openapi.urls` for explicit runtime documents. Optional `openapi.runtime_discovery` maps recognized Springdoc, Springfox, FastAPI, Nest Swagger, and Swaggo evidence to conventional read-only endpoints under `variables.base_url`; runtime discovery is disabled until the project config enables it. A failed optional endpoint becomes a warning, while a required source fails the scan.
- Read every configured `flow_documents` file before AI-generated flow work. Standalone JSON/YAML flow files and Markdown fenced `qa-platform-flow`, `qa-platform-flow-json`, or `qa-platform-flow-yaml` blocks become deterministic draft flows. Markdown, AsciiDoc, and text prose remains AI guidance in local `flow_documents.json`; use it to refine `flow.json`, retain source references, and keep AI-authored steps disabled/draft until review.
- For Spring Boot/Cloud routes, also inspect module-scoped `application*.yml`, `application*.yaml`, `application*.properties`, and `bootstrap*` files. Apply literal `server.servlet.context-path`, `server.context-path`, `spring.mvc.servlet.path`, or `spring.webflux.base-path` values to Spring HTTP/`@MessageMapping` paths, retain configuration source references, and warn when profile candidates disagree. Leave OpenAPI/Swagger paths unchanged because those documents may already include the deployed prefix.
- Initialize success conditions from `.qa-platform.json` `success_assertions`: its `definitions` and per-protocol `default_assertion` are importable assets. Bind every HTTP/WS API to one configured condition through `success_assertion_key`; reject a missing/invalid condition rather than silently falling back. An AI may draft project-specific condition definitions from source facts, but they remain reviewable configuration. Keep the inline `success_contract` only as importer compatibility metadata.
- Use CodeGraph for targeted codebase-structure questions when it is available. Run `codegraph status` first and prefer symbol queries before broad scans; fall back to the bundled scanner when the installed version lacks a requested command.
- Emit an editable module bundle as the primary scan result: `manifest.json`, `project.json`, `api_templates.json`, `assertion_definitions.json`, `inventory.json`, `flow_documents.json`, `api.json`, `flow.json`, and `plans.json`. Also emit `qa-platform-import.json` as a compatibility snapshot. Validation and ZIP construction must read the module directory so later AI/reviewer edits to one module are authoritative.
- Generate at most one test plan for each `package_version`. Aggregate all generated flows into that plan, then add direct API items only for interfaces not covered by a flow so the plan has complete scope without duplicate execution.
- Preserve `source_refs`, `discovery_method`, `confidence`, and `warnings`. Never present an inferred feature or guessed request body as a confirmed fact.
- Use `key` as the only public HTTP/WS interface identity: `http:<METHOD>:<path>` for HTTP and `ws:<path-or-url>` for WebSocket. The scanner may use the same route key internally to merge duplicate source references, but it does not emit a separate `identity_key` or `business_key` on interface records.
- Construct imported API parameters only with qa-platform's executable `path`/`query`/`header`/JSON `body` model. Materialize every resolved `object.properties` tree as recursive `children`; child nodes omit `in` and inherit the parent location. Keep arrays as `items` rather than inventing array-index paths. Every root and child parameter must have a non-empty description and a safe example; preserve documented values first, otherwise derive neutral location/type wording and a deterministic UI-only example. Emit `default` only when source/config explicitly supports it. Do not copy raw OpenAPI Parameter Objects or pretend multipart/scalar bodies are executable.
- Treat a strongly evidenced HTTP `{code, data}` response envelope as two views: keep the complete wire schema in `response_unpack.envelope_schema`, emit the logical `data` schema as `response_schema`, and set `response_unpack` to `{"enabled": true, "source": "body.data"}`. Strong evidence means `code` and `data` are both required or `code` has a documented `const`/`enum`; do not infer an envelope from a field name alone. At runtime `response.body` remains the raw response and `response.payload` is the extracted value; response-schema assertions and extractors use `payload` when enabled. Missing paths fail execution instead of silently validating a different value. Non-envelope responses and WebSocket APIs keep `response_unpack` disabled/empty.
- For Java/Spring DTOs, strip JavaDoc before parsing declarations, use JavaDoc as field metadata, resolve nested classes/records/enums recursively, and preserve enum fields as `string` with `enum`. When OpenAPI/Swagger response data is absent, use the Spring method return type as a secondary response contract source; unwrap `ResponseEntity<T>`/`Optional<T>`, expand DTOs, and represent common `R<T>`/`Result<T>` wrappers as reviewable `code`/`data` fields with warnings where the wrapper is inferred.
- Discover reusable templates from a shared frontend request-header builder and Spring gateway security configuration when explicit templates are absent. Emit only safe headers and variable references such as `{{ access_token }}`, `{{ random.uuid(32) }}`, and `{{ frontend_environment }}`; never copy secrets. Bind an auth template before a public fallback template and honor gateway `ignore-urls` through template exclusion matches.
- Give every API a specific display name. Prefer OpenAPI summaries/operation IDs, then combine Spring controller/interface JavaDoc with method JavaDoc; apply the same rule to Spring `WebSocketConfigurer#addHandler` registrations. Preserve that source-derived name during localization. Without comments, use a meaningful Java identifier or route token before a generic fallback. For a residual collision, add the HTTP/WS method and request target deterministically instead of leaving repeated names such as “查询接口”.
- Do not put credentials, tokens, cookies, private keys, or secret values in the manifest. Represent runtime values as variable references or leave them unresolved.
- Keep the project-local qa-platform configuration non-secret. Its top-level `base_url` is the qa-platform service address and defaults to `http://localhost:8000`; `variables.base_url` is the required target project `ip:port` value, without `http://`. Use `QA_PLATFORM_TOKEN` from the environment when authentication is required.
- Resolve the display language from the configured `language`, then project comments, then the system locale; if there is no reliable evidence, use `zh-CN`. Stable business keys remain language-neutral while generated names and descriptions follow the selected language.
- Resolve `package_version` from an explicit CLI override, `.qa-platform.json`, or project metadata. Prefer a root Maven `<revision>`/`<version>` for Maven projects; for non-Maven projects support Python `pyproject.toml`/`setup.cfg`/`setup.py`, Node `package.json`, Gradle, and root `VERSION` files. Remove only a terminal `-SNAPSHOT` suffix and record the source evidence in `source.release_version`.
- Store scan modules, the compatibility manifest, and archives under the configured `storage.directory`; the default is `releases/<package_version>/` with one editable module/ZIP bucket per version. Generated release files are excluded from later scans. When `--output` points elsewhere, modules default to a sibling `<output-stem>.modules/` directory unless `--modules-dir` is explicit.
- Generate test cases and flows as `draft` assets with `origin: scanner` unless their behavior is directly documented. AI-supplemented assets must remain draft until a human approves them.
- A one-click import is an external entry point that creates a pending approval session; it does not bypass review. Do not silently call mutating qa-platform endpoints.

## Standard workflow

1. Identify the application root and read its nearest `AGENTS.md` before inspecting source files. Record the project name and, if available, the current Git commit.
2. Look for OpenAPI, Swagger, AsyncAPI, route manifests, API examples, frontend router files, service configuration, literal success assertion definitions, and controller/interface plus method comments. For Spring projects, include application/bootstrap config when resolving the module's effective route prefix. Do not treat generated build output, dependency directories, or `.codegraph` as application source.
   For template completeness, inspect shared frontend request-header builders and Spring gateway security blocks; these are source evidence for safe `api_templates`, not a license to copy runtime tokens.
3. Run the bundled scanner. Let it detect the target project's release version by default; provide `--plan-version` (or `--package-version`) only to override it. Provide the previous manifest when deciding whether to update that version or create a new one:

   ```bash
   python3 /path/to/qa-platform-skill/scripts/scan_project.py \
     /path/to/project \
     --project-key my-project \
     --previous-manifest /path/to/previous-import.json
   ```

   A Maven root using `<revision>0.1.2-SNAPSHOT</revision>` produces `package_version: "0.1.2"`, `releases/0.1.2/`, and a `0.1.2/` ZIP directory. Without `--output`, the manifest is written to that detected version bucket. Use `--language zh-CN` for a one-off override or configure `language` in `.qa-platform.json`.

   Add `--openapi path/to/openapi.json` for local documents outside the configured/default discovery paths, or `--openapi-url http://127.0.0.1:8080/v3/api-docs` for an explicit running service. Repeat either option for multiple documents. The command prints both the compatibility `output` and authoritative `modules` directory.
   Read `references/api-definition-protocol.md` before extending or reviewing parameter extraction, especially for nested OpenAPI/Swagger schemas, Spring request bodies/DTOs, or non-JSON content types.
4. Review the generated modules before importing:

   - `project.json`, `api_templates.json`, and `assertion_definitions.json` are project-level reusable assets.
   - When `api_templates` was empty in project config, inspect `api_templates.json` for scanner-generated frontend/gateway templates, their `source_refs`, and `match.exclude_paths`; review public-route exclusions before import.
   - `api.json`, `flow.json`, and `plans.json` are independently editable. If AI improves a documented flow, edit `flow.json`; do not hand-edit the compatibility aggregate.
   - `flow_documents.json` contains local AI-readable prose and hashes. Its prose content is omitted from the compatibility manifest and final ZIP; only document metadata is packaged.
   - `architecture.is_microservices` and `architecture.gateway` are static evidence, not runtime proof.
   - An explicit gateway address is safe to carry into the project variables. An inferred address is emitted with low confidence and must be confirmed; an unknown address remains `null`.
   - `create` means no previous package (or a changed project key), `update` means same version with stable-key changes, `new_version` means the test version changed, and `unchanged` means no stable-key content changed.
   - Feature grouping and flow step order are inferred. Generated flows and plans remain draft/disabled.
   - For an API with `response_unpack.enabled`, review both the logical `response_schema` (the fields users assert) and `response_unpack.envelope_schema` (the raw `{code,data}` contract); do not duplicate envelope fields inside the logical response editor.
5. Validate before showing or importing the result:

   ```bash
   python3 /path/to/qa-platform-skill/scripts/validate-import.py \
     /path/to/project/releases/0.1.2
   ```

6. Summarize counts for HTTP interfaces, WS interfaces, API templates, success conditions, flow documents, features, test cases, flows, test plans, warnings, gateway evidence, and unresolved assumptions. Report each discovered template's source and exclusion rules. Highlight low-confidence items, generated placeholder descriptions/examples, missing request/response schemas, and inferred Java response wrappers.
7. If an earlier manifest exists, compare it before import:

   ```bash
   python3 /path/to/qa-platform-skill/scripts/diff-import.py \
     /path/to/old-release-modules /path/to/project/releases/0.1.2
   ```

8. Build the actual ZIP consumed by the current qa-platform import center:

   ```bash
   python3 /path/to/qa-platform-skill/scripts/build_import_archive.py \
     /path/to/project/releases/0.1.2
   ```

   The archive contains `manifest.json`, `project.json`, `api_templates.json`, `inventory.json`, `flow_documents.json` metadata, root-level `assertion_definitions.json`, plus a version directory with imported `api.json`, `flow.json`, and `plans.json`. The current platform accepts ZIP only; RAR is rejected.
9. Create the project-local configuration before generating an import package:

   ```bash
   python3 /path/to/qa-platform-skill/scripts/init_project_config.py \
     /path/to/project \
     --base-url http://localhost:8000 \
     --project-base-url 127.0.0.1:9764 \
     --project-key my-project \
     --project-name "My Project" \
     --api-document docs/openapi.json \
     --flow-document docs/test-flows.md \
     --endpoint preview
   ```

   This creates `.qa-platform.json` with project metadata, required `variables.base_url`, API templates, success conditions, flow-document sources, OpenAPI sources/runtime settings, detected language, optional `package_version` override, and versioned artifact storage. The project variable is an `ip:port` value because qa-platform adds `http://` when resolving it. The top-level `base_url` remains the qa-platform service location. The file never contains a token.
10. Keep ZIP generation independent from service publishing. To manually send an already-created ZIP to the configured service:

   ```bash
   python3 /path/to/qa-platform-skill/scripts/publish_import.py \
     /path/to/qa-platform-import.zip \
     --root /path/to/project
   ```

   The publisher defaults to `preview`, sends raw ZIP bytes, and never calls `/approve`. Use `--endpoint one-click` only when the external-entry semantics are intended; it still creates a pending session.
11. Review created/updated/unchanged items and warnings. Apply only after an explicit human approval through `/approve`; reject with `/reject` when needed. After import, report the import ID, project ID, version decision, architecture/gateway confidence, item counts, conflicts or unresolved references, and draft assets that still need human review.

## Discovery and interpretation

Use the following precedence for facts:

1. Configured or discovered OpenAPI/Swagger/AsyncAPI operation data.
2. Explicit framework route declarations and typed schemas.
3. Static shared-request/gateway evidence for reusable templates.
4. Structured project flow-document blocks for flow order and intent.
5. Frontend router and page metadata.
6. Controller/service names, prose flow documents, documentation, and comments.
7. Heuristic grouping by URL path or page route.

Merge duplicate interfaces by the normalized route key (`http:METHOD:path` or `ws:path`) and retain all source references. Expose that route key as the only public API/WS `key`; feature, flow, and plan assets retain their own business-oriented keys. For WebSocket message details, record only messages found in source or AsyncAPI; use warnings for an endpoint whose message contract is unknown. For basic functionality, connect frontend entrypoints and backend interfaces through explicit references where possible. A feature with no reliable interface relation may still be imported as an inventory item but should not receive a flow.

For architecture detection, distinguish these cases:

- Explicit gateway configuration or a named gateway component is strong evidence of a gateway.
- Service discovery markers or multiple service build roots are evidence of a multi-service project, but not proof that every client must use the gateway.
- An explicit gateway/base URL may be recorded. A `server.port`-based URL is only an inference and must carry a warning. Never invent a production host, scheme, or port.

Generate only conservative bootstrap assets:

- One draft smoke-case skeleton per discovered interface. These cases are retained in `inventory.json` because the current platform has no standalone test-case model.
- Documented structured flows first, then one inferred draft flow per remaining feature only when it has uncovered related interfaces, plus one disabled draft smoke plan for the whole project version. The plan contains every generated flow and direct API items only for interfaces not covered by a flow.
- Materialize configured success condition definitions and set every API's `success_assertion_key` to its configured protocol default. Let AI-supplemented definitions remain draft/reviewable configuration; preserve the fallback `success_contract`.
- Keep generated flow steps and plan items disabled until a reviewer confirms the inferred grouping, order, request values, and success contract.
- Do not invent authentication credentials, IDs, business values, or step ordering. Put unresolved values in `warnings` and use variables such as `{{ access_token }}` only when the project already defines them.

Interface and business grouping key rules:

- API/WS keys are deterministic route identities: `http:<METHOD>:<path>` and `ws:<path-or-url>`. If a supplied route key has this prefix, the method/path must match it exactly.
- OpenAPI `operationId` and `x-business-key` remain internal hints for feature names and grouping; they do not change the interface key.
- Feature grouping may still derive a dot-separated business label from the operation ID or meaningful route segments after removing generic `api`/version prefixes.
- Flows use `flow:<feature-business-key>`, and the one version plan uses `plan:<project-key>:<version>:smoke`.

## References

- Read [references/import-schema.md](references/import-schema.md) when producing or reviewing the scanner JSON and ZIP mapping.
- Read [references/api-definition-protocol.md](references/api-definition-protocol.md) when constructing, validating, or extending API parameter definitions.
- Read [references/scanner-rules.md](references/scanner-rules.md) when choosing discovery methods, interpreting architecture evidence, or deciding confidence.
- Read [references/qa-platform-import-api.md](references/qa-platform-import-api.md) when integrating with the FastAPI ZIP import, preview, one-click, approval, and rejection endpoints.
