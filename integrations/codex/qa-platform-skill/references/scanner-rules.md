# Scanner rules

The scanner is a read-only, standard-library heuristic scanner. It produces a reviewable interface inventory; it does not prove runtime reachability or business behavior.

## Discovery order

Prefer high-signal sources and retain the discovery method in every record:

1. OpenAPI, Swagger, or AsyncAPI documents: `openapi`, `asyncapi`.
2. Explicit backend routes: `source`.
3. Frontend router declarations and page metadata: `frontend-route`.
4. Documentation and naming heuristics: `inferred`.

Merge records by `identity_key`. Never discard a second source reference because the first source already found the same route. The route identity is `http:<METHOD>:<path>` for HTTP and `ws:<path-or-url>` for WebSocket; the imported `key` is a business-oriented key such as `user.auth.login`.

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

Prefer a project-local `.qa-platform.json` `success_assertions` section. It declares `definitions`, `profiles`, and `default_profile.http` / `default_profile.ws`; the scanner imports those assets and assigns every discovered API the configured default profile for its protocol. The initialized starter configuration uses HTTP 2xx and one WebSocket message. An AI may generate or refine additional definitions/profiles from source facts, but they remain reviewable config rather than an inferred runtime truth.

Validate configured profile names, protocol matches, and binding definition keys before scanning. A missing or invalid configured profile fails the scan; it must not silently switch APIs to another collection. Projects without the section retain the legacy inferred system profile for compatibility. Literal application declarations such as `SUCCESS_CODE`, `CODE_SUCCESS`, `ResultCode.SUCCESS(0, ...)`, and `success-code` still provide source evidence for the inline compatibility `success_contract`; conflicting values remain unresolved with a warning. Do not infer a success assertion from a method named `success` or from runtime-only behavior.

Each generated API carries `assertion_profile_key`, and the manifest/ZIP carries the referenced `assertion_definitions` and `assertion_profiles`. The inline `success_contract` remains for compatibility with older importers.

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

Skip `.git`, `.codegraph`, virtual environments, dependency directories, build output, coverage output, and binary files. Read source as UTF-8 with replacement for malformed bytes. Do not fetch arbitrary URLs or execute application code during static scanning.

If dynamic discovery is later added, require an explicit base URL and host allowlist, redact response secrets, and keep it separate from the deterministic source scan.

## Version decision

Resolve `package_version` before comparing manifests. Use an explicit `--plan-version`/`--package-version` first, then `.qa-platform.json` `package_version`, then root project metadata: Maven `<revision>` or `<version>`, Python `pyproject.toml`/`setup.cfg`/`setup.py`, Node `package.json`, Gradle, and a root `VERSION` file. Remove only a terminal `-SNAPSHOT` suffix and preserve the selected source in `source.release_version`. Do not require a Maven file for Python or other non-Maven projects.

When `--previous-manifest` is provided, compare the current and previous assets by stable key:

- `create`: no previous manifest or the project key changed.
- `update`: the package version is unchanged and one or more interface, feature, case, flow, or plan records changed.
- `new_version`: the package version changed; generated plan keys include the new version.
- `unchanged`: no stable-key content changed.

This decision is explanatory metadata for preview and approval. It must not cause the scanner to mutate a project.

## Feature, flow, and plan grouping

Use explicit feature metadata first. If unavailable, group related API routes by their first meaningful literal path segment and use frontend route paths as page features. Mark these groups as inferred and retain the contributing interface keys. Do not claim that a path group represents a complete business process.

For each feature with related interfaces, generate one disabled draft flow. Then generate at most one disabled draft smoke plan for the whole project `package_version`: add every generated flow first, followed by direct API items only for interfaces that no generated flow covers. This keeps the plan scope complete without running the same interface both inside a flow and as a direct item. Sort interface keys only to make output reproducible; that order is not a verified business sequence. Features without related interfaces remain inventory only.

Business keys prefer OpenAPI `operationId` or `x-business-key`, then derive from meaningful route segments after removing generic `api` and version prefixes. Use dot-separated segments and keep at most four. Resolve collisions deterministically with `:<method>` and numeric suffixes; never use display names alone as identities.
