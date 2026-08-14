# Scanner rules

The scanner is read-only and deterministic. It uses the Python standard library plus optional PyYAML for YAML contracts. It produces a reviewable interface inventory; it does not prove runtime reachability or business behavior.

## Discovery order

Prefer high-signal sources and retain the discovery method in every record:

1. OpenAPI, Swagger, or AsyncAPI documents: `openapi`, `swagger`, `asyncapi`.
2. Explicit backend routes: `source`.
3. Frontend router declarations and page metadata: `frontend-route`.
4. Documentation and naming heuristics: `inferred`.

Merge records by the normalized route key. Never discard a second source reference because the first source already found the same route. The route key is `http:<METHOD>:<path>` for HTTP and `ws:<path-or-url>` for WebSocket, and it is emitted as the interface `key`. Business labels are used only for feature grouping and display names.

## Standard API document conversion

Read sources in this order: CLI/configured local documents, automatically discovered conventional filenames, explicit configured runtime URLs, then optional framework runtime discovery. Runtime sources are read-only HTTP(S) requests and are used only when the user/config enables them.

- Resolve local `$ref` for Path Items, operations, parameters, request bodies, responses, messages, and nested schemas. Keep warnings for external, missing, or cyclic references.
- Merge Path Item parameters before Operation parameters so operation facts win by `(in, name)`.
- Preserve `summary`, `description`, `operationId`, tags, security override, types, formats, required fields, enum, pattern, numeric/string/array constraints, defaults, and examples.
- Flatten resolved `allOf` object properties/required names into the visible schema while retaining the composed schema, so qa-platform's request/response field editors do not lose inherited fields.
- Map OpenAPI request JSON media type to request `Content-Type`. Map the selected successful response JSON media type (or Swagger `produces`) to `request_schema.accept`, which materializes as the HTTP `Accept` header.
- Preserve request fields in `request_schema.schema`, response fields in `response_schema`, and executable request fields in `parameters`. Media-level object examples propagate to matching fields.
- If a documented field lacks description/example, generate only a deterministic neutral placeholder and add an API warning. If a non-204 successful response has no readable JSON schema, keep it empty and warn rather than letting AI invent a response.

`openapi.runtime_discovery` recognizes conventional paths only when matching framework evidence exists: Springdoc `/v3/api-docs`, Springfox `/v2/api-docs`, FastAPI `/openapi.json`, Nest Swagger `/api-json`, and Swaggo `/swagger/doc.json`. Projects with custom endpoints should configure `openapi.urls` or `runtime_discovery.paths` explicitly.

## Supported static patterns in the bundled scanner

The standard-library scanner recognizes common forms for:

- Python FastAPI/Flask-style decorators: `@router.get`, `@app.post`, `@app.route`, and `@router.websocket`.
- Spring Boot/Java annotations: `@GetMapping`, `@PostMapping`, `@RequestMapping`, `@MessageMapping`, and `@ServerEndpoint`; literal `WebSocketConfigurer`/`WebSocketHandlerRegistry` `addHandler(..., "/path")` registrations.
- Node Express/Nest-like calls: `router.get`, `app.post`, and similar method calls.
- Go Gin/Echo-like calls: `router.GET`, `e.POST`, and similar method calls.
- Vue/React route objects containing `path: "/..."`.

These are conservative recognizers, not complete parsers. Preserve a warning when a declaration is dynamic, generated, or missing a literal path.

Literal route patterns are reliable. Dynamic prefixes, generated routers, reflection, framework plugins, and routes assembled across modules may be missed; provide an explicit OpenAPI/AsyncAPI document or review warnings when completeness matters.

### Spring application path prefixes

For Spring Boot/Cloud source routes, inspect module-scoped `application*.yml`, `application*.yaml`, `application*.properties`, and `bootstrap*` files. The scanner recognizes these relaxed-binding keys:

- `server.servlet.context-path` and legacy `server.context-path`;
- `spring.mvc.servlet.path`;
- `spring.webflux.base-path`.

Literal values are normalized as route prefixes and composed with class/method mappings. For example, `server.servlet.context-path=/chat` plus `@GetMapping("/users")` becomes `/chat/users`. The selected configuration line is retained in `source_refs`. When profile files in the same module declare different prefixes, the base `application` file is selected and a warning is emitted because the active runtime profile is not knowable from static scanning. OpenAPI/Swagger paths are left unchanged to avoid duplicating a prefix that is already present in the document.

### Success assertion discovery

Prefer a project-local `.qa-platform.json` `success_assertions` section. It declares `definitions` and `default_assertion.http` / `default_assertion.ws`; the scanner imports those assets and assigns every discovered API one configured success condition. The initialized starter configuration uses HTTP 2xx and one WebSocket message. An AI may generate or refine additional definitions from source facts, but they remain reviewable config rather than an inferred runtime truth.

Validate configured success-condition keys and definition keys before scanning. A missing or invalid configured condition fails the scan; it must not silently switch APIs to another condition. Projects without the section retain the legacy inferred system condition for compatibility. Literal application declarations such as `SUCCESS_CODE`, `CODE_SUCCESS`, `ResultCode.SUCCESS(0, ...)`, and `success-code` still provide source evidence for the inline compatibility `success_contract`; conflicting values remain unresolved with a warning. Do not infer a success condition from a method named `success` or from runtime-only behavior.

Each generated API carries `success_assertion_key`, and the manifest/ZIP carries the referenced `assertion_definitions`. The inline `success_contract` remains for compatibility with older importers.

## API display names and descriptions

Keep imported API names useful and unique for reviewers. Prefer OpenAPI `summary` / `operationId`, then Spring controller/interface JavaDoc plus method JavaDoc, combining class business context with the method action. Apply the same rule to Spring `WebSocketConfigurer#addHandler` registrations: use the enclosing configuration class and registration-method JavaDoc. Preserve a source-derived name during localization; do not overwrite it with a generic path label. Without comments, use a meaningful Java identifier or route token before a generic fallback. When two display names still collide, append the protocol method and request target deterministically.

For path-only fallbacks, use meaningful route segments plus the HTTP action. A generic label such as “查询接口” or “虚拟数据业务接口” is insufficient when more specific source context exists. Never invent a business operation that is not documented or indicated by the route.

## Parameter discovery

Build API parameters with the executable contract in [api-definition-protocol.md](api-definition-protocol.md), not by copying framework/OpenAPI objects verbatim. Every emitted parameter must have a non-empty description and a safe example. Preserve source descriptions/examples when available; otherwise derive a neutral description from location/name/type and a deterministic UI-only example from type, format, or enum. Only emit a default when source/config explicitly declares one. Path placeholders are available for every route source. OpenAPI/Swagger and Spring typed signatures add higher-confidence parameter facts; unsupported multipart, form, scalar, and unresolved body shapes remain warnings instead of fabricated `body` fields.

## Confidence

Use confidence as a review hint, not as a pass/fail score:

- `0.95-1.0`: explicit OpenAPI operation or literal framework route.
- `0.75-0.94`: route plus useful source metadata or schema.
- `0.45-0.74`: frontend route or feature grouped from related routes.
- below `0.45`: inferred feature or inferred flow ordering.

Do not create executable flows from a feature with no related interface keys. A flow assembled only from URL ordering is a draft suggestion and must be disabled.

## Architecture and gateway detection

Architecture detection is static evidence aggregation:

- Named gateway components and configuration markers such as Spring Cloud Gateway, Zuul, Traefik, Kong, Envoy, or `proxy_pass` are strong gateway evidence.
- Eureka, Nacos, Consul, Spring Cloud discovery markers, and multiple nested service build roots indicate a multi-service or microservice-shaped repository, but do not prove the runtime topology.
- Read Maven/Gradle/Go/Node build metadata and `.properties` files as architecture evidence even though they are not route sources. Collapse nested modules below a named service root (for example `app-gateway/boot`) before presenting the service list.
- Explicit `GATEWAY_URL`, `API_GATEWAY_URL`, `API_BASE_URL`, or equivalent HTTP configuration may provide a gateway address. Preserve its source reference and mark it `explicit`.
- A `server.port` found in a gateway-looking file may produce `http://localhost:<port>` as `inferred` evidence only. It must carry a warning and must not be treated as a production address.
- When the project looks like a microservice system but no address is explicit, keep `architecture.gateway.address` as `null` and report the warning. Never invent a host, protocol, or port.

`is_microservices`, `gateway.detected`, and `gateway.address` are review signals. They do not replace runtime configuration or deployment inspection.

## Safe scanning

Skip `.git`, `.codegraph`, virtual environments, dependency directories, build output, coverage output, generated module directories, and binary files. Read source as UTF-8 with replacement for malformed bytes. Never execute application code. Fetch only CLI/configured HTTP(S) OpenAPI URLs or conventional paths explicitly enabled under the configured `variables.base_url`; cap response time and bytes. Do not crawl links or infer production hosts.

Configured flow documents must remain inside the project root and are capped at 2 MiB each. Their full prose is copied only to the local module context; compatibility JSON and ZIP output strip it. Flow and API artifacts still pass secret scanning before packaging.

## Version decision

Resolve `package_version` before comparing manifests. Use an explicit `--plan-version`/`--package-version` first, then `.qa-platform.json` `package_version`, then root project metadata: Maven `<revision>` or `<version>`, Python `pyproject.toml`/`setup.cfg`/`setup.py`, Node `package.json`, Gradle, and a root `VERSION` file. Remove only a terminal `-SNAPSHOT` suffix and preserve the selected source in `source.release_version`. Do not require a Maven file for Python or other non-Maven projects.

When `--previous-manifest` is provided, compare the current and previous assets by stable key:

- `create`: no previous manifest or the project key changed.
- `update`: the package version is unchanged and one or more project, API template, success condition, interface, flow-document metadata, feature, case, flow, architecture, or plan records changed.
- `new_version`: the package version changed; generated plan keys include the new version.
- `unchanged`: no stable-key content changed.

This decision is explanatory metadata for preview and approval. It must not cause the scanner to mutate a project.

## Feature, flow, and plan grouping

Use explicit feature metadata first. If unavailable, group related API routes by their first meaningful literal path segment and use frontend route paths as page features. Mark these groups as inferred and retain the contributing interface keys. Do not claim that a path group represents a complete business process.

Load structured project flow documents first. They may define exact step order but still remain disabled drafts until runtime values are reviewed. Mark their covered interface keys, then generate one disabled inferred flow for only the remaining interfaces of each feature. Generate at most one disabled draft smoke plan for the whole project `package_version`: add every documented/inferred flow first, followed by direct API items only for interfaces that no flow covers. This keeps the plan scope complete without running the same interface both inside a flow and as a direct item. Sort inferred interface keys only to make output reproducible; that order is not a verified business sequence. Features without related interfaces remain inventory only.

Business keys prefer OpenAPI `operationId` or `x-business-key`, then derive from meaningful route segments after removing generic `api` and version prefixes. Use dot-separated segments and keep at most four. Resolve collisions deterministically with `:<method>` and numeric suffixes; never use display names alone as identities.
