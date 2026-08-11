---
name: qa-platform-skill
description: Scan Python, Spring Boot/Java, Go, Node, and other common projects for HTTP and WebSocket interfaces, assign business-oriented API/flow/plan keys, detect microservice topology and gateway evidence, compare scan results by test version, generate draft business flows and test plans, and build or preview-publish a validated ZIP for qa-platform. Use when asked to inventory interfaces, bootstrap API tests, decide update versus new test version, configure the qa-platform service, or import scan results.
---

# QA Platform Scanner

Use this skill to create a reproducible inventory of a project and prepare it for qa-platform. Keep scanning, normalization, version decisions, and platform import as separate concerns.

## Operating rules

- Treat source scanning as read-only. Do not modify the target project while discovering routes or pages. The explicit `init_project_config.py` command is the only bundled command that writes the project-local `.qa-platform.json`; package validation requires its `variables.base_url` project variable.
- Prefer existing OpenAPI, Swagger, or AsyncAPI documents, then inspect framework route declarations and frontend route configuration. The bundled scanner covers common Python decorators, Spring Boot annotations, Go router calls, Node routes, and Java/Node/Python WebSocket declarations; it is static analysis, not a guarantee that every dynamically generated route is discoverable.
- For Spring Boot/Cloud routes, also inspect module-scoped `application*.yml`, `application*.yaml`, `application*.properties`, and `bootstrap*` files. Apply literal `server.servlet.context-path`, `server.context-path`, `spring.mvc.servlet.path`, or `spring.webflux.base-path` values to Spring HTTP/`@MessageMapping` paths, retain configuration source references, and warn when profile candidates disagree. Leave OpenAPI/Swagger paths unchanged because those documents may already include the deployed prefix.
- Initialize success assertions from `.qa-platform.json` `success_assertions`: its `definitions`, `profiles`, and per-protocol `default_profile` are importable assets. Bind every HTTP/WS API to that configured default through `assertion_profile_key`; reject a missing/invalid profile or binding rather than silently falling back. An AI may draft project-specific assertion assets from source facts, but they remain reviewable configuration. Keep the inline `success_contract` only as importer compatibility metadata; legacy configs without this section retain the prior inferred system profile.
- Use CodeGraph for targeted codebase-structure questions when it is available. Run `codegraph status` first and prefer symbol queries before broad scans; fall back to the bundled scanner when the installed version lacks a requested command.
- Emit one `qa-platform-import` JSON document with a schema version, `package_version`, `architecture`, `import_decision`, and draft `test_plans`. Keep stable `key` values for every project asset so repeated imports are idempotent.
- Generate at most one test plan for each `package_version`. Aggregate all generated flows into that plan, then add direct API items only for interfaces not covered by a flow so the plan has complete scope without duplicate execution.
- Preserve `source_refs`, `discovery_method`, `confidence`, and `warnings`. Never present an inferred feature or guessed request body as a confirmed fact.
- Construct imported API parameters only with qa-platform's executable `path`/`query`/`header`/top-level JSON `body` model. Every emitted parameter must have a non-empty description and a safe example; preserve documented values first, otherwise derive neutral location/type wording and a deterministic UI-only example. Emit `default` only when source/config explicitly supports it. Do not copy raw OpenAPI Parameter Objects or pretend multipart/scalar bodies are executable.
- Give every API a specific display name. Prefer OpenAPI summaries/operation IDs, then combine Spring controller/interface JavaDoc with method JavaDoc; apply the same rule to Spring `WebSocketConfigurer#addHandler` registrations. Preserve that source-derived name during localization. Without comments, use a meaningful Java identifier or route token before a generic fallback. For a residual collision, add the HTTP/WS method and request target deterministically instead of leaving repeated names such as “查询接口”.
- Do not put credentials, tokens, cookies, private keys, or secret values in the manifest. Represent runtime values as variable references or leave them unresolved.
- Keep the project-local qa-platform configuration non-secret. Its top-level `base_url` is the qa-platform service address and defaults to `http://localhost:8000`; `variables.base_url` is the required target project `ip:port` value, without `http://`. Use `QA_PLATFORM_TOKEN` from the environment when authentication is required.
- Resolve the display language from the configured `language`, then project comments, then the system locale; if there is no reliable evidence, use `zh-CN`. Stable business keys remain language-neutral while generated names and descriptions follow the selected language.
- Resolve `package_version` from an explicit CLI override, `.qa-platform.json`, or project metadata. Prefer a root Maven `<revision>`/`<version>` for Maven projects; for non-Maven projects support Python `pyproject.toml`/`setup.cfg`/`setup.py`, Node `package.json`, Gradle, and root `VERSION` files. Remove only a terminal `-SNAPSHOT` suffix and record the source evidence in `source.release_version`.
- Store scan manifests and archives under the configured `storage.directory`; the default is `releases/<package_version>/` with one manifest and ZIP bucket per version. Generated release files are excluded from later scans.
- Generate test cases and flows as `draft` assets with `origin: scanner` unless their behavior is directly documented. AI-supplemented assets must remain draft until a human approves them.
- A one-click import is an external entry point that creates a pending approval session; it does not bypass review. Do not silently call mutating qa-platform endpoints.

## Standard workflow

1. Identify the application root and read its nearest `AGENTS.md` before inspecting source files. Record the project name and, if available, the current Git commit.
2. Look for OpenAPI, Swagger, AsyncAPI, route manifests, API examples, frontend router files, service configuration, literal success assertion definitions, and controller/interface plus method comments. For Spring projects, include application/bootstrap config when resolving the module's effective route prefix. Do not treat generated build output, dependency directories, or `.codegraph` as application source.
3. Run the bundled scanner. Let it detect the target project's release version by default; provide `--plan-version` (or `--package-version`) only to override it. Provide the previous manifest when deciding whether to update that version or create a new one:

   ```bash
   python3 /path/to/qa-platform-skill/scripts/scan_project.py \
     /path/to/project \
     --project-key my-project \
     --previous-manifest /path/to/previous-import.json
   ```

   A Maven root using `<revision>0.1.2-SNAPSHOT</revision>` produces `package_version: "0.1.2"`, `releases/0.1.2/`, and a `0.1.2/` ZIP directory. Without `--output`, the manifest is written to that detected version bucket. Use `--language zh-CN` for a one-off override or configure `language` in `.qa-platform.json`.

   Add `--openapi path/to/openapi.json` for documents outside the default discovery paths. Repeat the option for multiple documents.
   Read `references/api-definition-protocol.md` before extending or reviewing parameter extraction, especially for OpenAPI references, Spring request bodies, or non-JSON content types.
4. Review `architecture` and `import_decision` before importing:

   - `architecture.is_microservices` and `architecture.gateway` are static evidence, not runtime proof.
   - An explicit gateway address is safe to carry into the project variables. An inferred address is emitted with low confidence and must be confirmed; an unknown address remains `null`.
   - `create` means no previous package (or a changed project key), `update` means same version with stable-key changes, `new_version` means the test version changed, and `unchanged` means no stable-key content changed.
   - Feature grouping and flow step order are inferred. Generated flows and plans remain draft/disabled.
5. Validate before showing or importing the result:

   ```bash
   python3 /path/to/qa-platform-skill/scripts/validate-import.py /path/to/qa-platform-import.json
   ```

6. Summarize counts for HTTP interfaces, WS interfaces, assertion definitions/profiles, features, test cases, flows, test plans, warnings, gateway evidence, and unresolved assumptions. Highlight low-confidence items and any missing schemas.
7. If an earlier manifest exists, compare it before import:

   ```bash
   python3 /path/to/qa-platform-skill/scripts/diff-import.py \
     /path/to/old-import.json /path/to/qa-platform-import.json
   ```

8. Build the actual ZIP consumed by the current qa-platform import center:

   ```bash
   python3 /path/to/qa-platform-skill/scripts/build_import_archive.py \
     /path/to/project/releases/0.1.2/qa-platform-import.json
   ```

   The archive contains `manifest.json`, `project.json`, `inventory.json`, root-level `assertion_definitions.json` and `assertion_profiles.json`, plus a version directory with `api.json`, `flow.json`, and `plans.json`. The current platform accepts ZIP only; RAR is rejected.
9. Create the project-local configuration before generating an import package:

   ```bash
   python3 /path/to/qa-platform-skill/scripts/init_project_config.py \
     /path/to/project \
     --base-url http://localhost:8000 \
     --project-base-url 127.0.0.1:9764 \
     --endpoint preview
   ```

   This creates `.qa-platform.json` with the required `variables.base_url`, detected language, optional `package_version` override, versioned artifact storage, and a reviewable `success_assertions` starter section. The project variable is an `ip:port` value because qa-platform adds `http://` when resolving it. The top-level `base_url` remains the qa-platform service location. The file never contains a token.
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

1. OpenAPI/AsyncAPI operation data.
2. Explicit framework route declarations and typed schemas.
3. Frontend router and page metadata.
4. Controller/service names, documentation, and comments.
5. Heuristic grouping by URL path or page route.

Merge duplicate interfaces by internal `identity_key` (`http:METHOD:path` or `ws:path`) and retain all source references. Expose a business-oriented `key` for imported entities. For WebSocket message details, record only messages found in source or AsyncAPI; use warnings for an endpoint whose message contract is unknown. For basic functionality, connect frontend entrypoints and backend interfaces through explicit references where possible. A feature with no reliable interface relation may still be imported as an inventory item but should not receive a flow.

For architecture detection, distinguish these cases:

- Explicit gateway configuration or a named gateway component is strong evidence of a gateway.
- Service discovery markers or multiple service build roots are evidence of a multi-service project, but not proof that every client must use the gateway.
- An explicit gateway/base URL may be recorded. A `server.port`-based URL is only an inference and must carry a warning. Never invent a production host, scheme, or port.

Generate only conservative bootstrap assets:

- One draft smoke-case skeleton per discovered interface. These cases are retained in `inventory.json` because the current platform has no standalone test-case model.
- One draft flow per feature only when it has related interfaces, plus one disabled draft smoke plan for the whole project version. The plan contains every generated flow and direct API items only for interfaces not covered by a flow.
- Materialize configured success assertion definitions/profiles and set every API's `assertion_profile_key` to its configured protocol default. Let AI-supplemented definitions/profiles remain draft/reviewable configuration; preserve the fallback `success_contract`.
- Keep generated flow steps and plan items disabled until a reviewer confirms the inferred grouping, order, request values, and success contract.
- Do not invent authentication credentials, IDs, business values, or step ordering. Put unresolved values in `warnings` and use variables such as `{{ access_token }}` only when the project already defines them.

Business key rules:

- Prefer an explicit OpenAPI `operationId` or `x-business-key`.
- Otherwise derive a dot-separated key from the meaningful route segments after removing generic `api`/version prefixes: `/user/auth/login` becomes `user.auth.login`.
- Keep up to four meaningful segments; convert path parameters to names such as `id`.
- API keys are business keys; flows use `flow:<feature-business-key>`, and the one version plan uses `plan:<project-key>:<version>:smoke`.
- When two routes resolve to the same business key, append `:<http-method>` and then `:<http-method>:2`, etc. The route identity remains in `identity_key`, so collision handling is deterministic and reviewable.

## References

- Read [references/import-schema.md](references/import-schema.md) when producing or reviewing the scanner JSON and ZIP mapping.
- Read [references/api-definition-protocol.md](references/api-definition-protocol.md) when constructing, validating, or extending API parameter definitions.
- Read [references/scanner-rules.md](references/scanner-rules.md) when choosing discovery methods, interpreting architecture evidence, or deciding confidence.
- Read [references/qa-platform-import-api.md](references/qa-platform-import-api.md) when integrating with the FastAPI ZIP import, preview, one-click, approval, and rejection endpoints.
