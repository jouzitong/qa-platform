# qa-platform API 参数构建协议

本协议定义扫描器如何把 OpenAPI、Swagger、Spring 等源码事实转换为 qa-platform 可执行的 `ApiDefinition.parameters`。它约束扫描 JSON 的 `interfaces.http[]` / `interfaces.ws[]`，并由 ZIP 构建器原样复制到 `<version>/api.json`。

完整的 `http-api/v1` 可移植示例见 `../assets/http_api.json`。

## 运行时边界

qa-platform 执行四类请求位置；参数树的根节点使用 `in`，`object` 子节点通过 `children` 递归继承根节点位置：

| `in` | 写入请求位置 | 说明 |
| --- | --- | --- |
| `path` | `request.path_params[name]`，替换 URL/Path 占位符 | 必须为 `required: true` |
| `query` | `request.query[name]` | HTTP URL 查询串 |
| `header` | `request.headers[name]` | HTTP Header 或 WS 握手 Header |
| `body` | `request.body[name]` | JSON 对象字段；嵌套字段通过 `children` 合并到对应对象 |

执行器会先将未传入的 `default` 写入上下文，再根据 `type` 将字符串转换为整数、浮点数、布尔值或 JSON 对象/数组。`example` 仅供编辑和测试界面展示，不会自动发送。

扫描器把 JSON 对象顶层字段构造成 `body` 参数，并把每个可识别的嵌套对象递归构造成 `children`。子节点不重复写 `in`，执行器沿父节点继承 `body` 位置；不使用 `user.profile.name`、`items[0].id` 等伪路径。数组保留 `items` 类型，不展开数组索引，也不把数组元素伪装成普通子参数。根标量、根数组、`multipart/form-data`、文件上传和 `application/x-www-form-urlencoded` 不能由当前执行器正确序列化，保留 schema 与警告，改由人工请求覆盖处理。

## 规范参数对象

每个参数使用下面的结构；`name`、`in`、`type`、`required`、非空 `description` 和已填充的 `example` 都是必填字段。`default` 只有源码或配置明确提供时才出现。

```json
{
  "name": "page",
  "in": "query",
  "type": "integer",
  "required": false,
  "description": "页码",
  "default": 1,
  "example": 2,
  "minimum": 1,
  "maximum": 100
}
```

允许值：

- `in`：`path`、`query`、`header`、`body`。
- `type`：`string`、`integer`、`number`、`boolean`、`object`、`array`。
- `description`：必须为非空字符串；优先保留源码说明，未知时使用位置、名称和类型构成中性说明，不把猜测的业务含义写成事实。
- `example`：必须为已填充的 JSON 值。优先保留源码示例；没有时按类型、格式或枚举生成安全、确定性的 UI 示例。
- `default`：可选 JSON 值，只传播源码或项目配置明确声明的默认值。数组和对象使用 JSON 值，不使用序列化后的 JSON 字符串。
- 约束：可选 `format`、`enum`、`pattern`、`minimum`、`maximum`、`minLength`、`maxLength`、`minItems`、`maxItems`、`uniqueItems`。`array` 可附带 `items: {"type": "..."}`。
- `children`：仅 `object` 使用的可选数组。子节点继续使用 `name`、`type`、`required`、非空 `description`、`example` 和可选 `default`/约束，但省略 `in` 并继承父节点位置；子节点名称在同一对象内必须唯一。

参数唯一键为 `(in, name)`；Header 名字大小写不敏感。`path` 即使上游声明为可选，也必须归一为必填。

## 构建顺序与优先级

1. 所有 HTTP/WS 请求目标先提取 `{id}` 和 `:id` 占位符，创建必填 `path` 参数，并补齐说明和示例。
2. 合并框架源码中可确认的类型、必填、默认值和 DTO 顶层字段。
3. 合并 OpenAPI/Swagger/AsyncAPI 的操作数据。它是最高可信来源，可补充或覆盖描述、类型、默认值、示例和约束。
4. 按 `path`、`query`、`header`、`body`，再按参数名排序，保证重复扫描稳定。

同一参数的合并不得丢失必填约束、已有说明或更精确的非字符串类型。若来源冲突，保留高可信来源的值并在接口 `warnings` 中记录无法执行的协议差异；不要创建两个同位置同名称的参数。

`request_schema` 使用 `http-api/v1` 包装结构：`schema` 保存可供审阅的请求 JSON Schema，`accept` 表示期望响应媒体类型，导入适配器会把它映射为实际请求头 `Accept`。OpenAPI 请求体媒体类型写入 `request.headers.Content-Type`，成功响应媒体类型写入 `request_schema.accept`。OpenAPI 请求体同时保留 `source_request_schema` 以追踪原始引用。只有上面的参数对象才会参与 qa-platform 的调用表单和默认值注入。

```json
{
  "request_schema": {
    "accept": "application/json",
    "schema": {
      "type": "object",
      "required": ["name"],
      "properties": {
        "name": {"type": "string", "description": "名称", "example": "示例名称"}
      }
    }
  },
  "response_schema": {
    "type": "object",
    "required": ["id"],
    "properties": {
      "id": {"type": "integer", "description": "资源 ID", "example": 1}
    }
  }
}
```

嵌套对象示例：

```json
{
  "name": "profile",
  "in": "body",
  "type": "object",
  "required": false,
  "description": "用户资料。",
  "example": {},
  "children": [
    {
      "name": "locale",
      "type": "string",
      "required": true,
      "description": "语言。",
      "example": "zh-CN"
    }
  ]
}
```

## 来源映射

### OpenAPI 3 / Swagger 2

- 合并 Path Item 的 `parameters` 与 Operation 的 `parameters`；Operation 同身份参数优先。
- 解析本地 `#/...` `$ref`，包括参数、请求体、响应和 schema 属性。外部或循环引用保留警告，不能伪造字段。
- OpenAPI `in: path/query/header` 映射为同名位置。`cookie` 不导入为可执行参数；请求运行时不应把 Cookie 当成普通 Header 默认值。
- Swagger 2 直接位于 Parameter Object 的 `type`、`format`、`items`、`default`、`enum` 等字段须归一为 schema。
- OpenAPI `requestBody.content.application/json` 或 `application/*+json` 的顶层 `properties` 映射为 `body`，嵌套 `object.properties` 递归映射为 `children`。每一层的 `required` 数组决定该层字段必填。
- Swagger 2 `in: body` 使用同一 JSON 对象展开规则。`in: formData` 只生成警告，不作为 JSON `body` 参数。
- OpenAPI 请求媒体类型或 Swagger 2 `consumes` 生成 `Content-Type`；成功响应 JSON 媒体类型或 `produces` 生成 `request_schema.accept` / `Accept`。
- 解析参数、请求体、响应及嵌套 schema 的本地 `$ref`，并把 `allOf` 继承字段展开到可视化编辑器可见的 `properties` / `required`。
- 媒体级对象示例下沉到同名请求/响应字段。字段缺少说明或示例时生成中性的确定性占位，并在 API `warnings` 中明确记录；不由 AI 猜测业务含义。
- 成功响应 schema 不构造请求参数；它完整进入 `response_schema`，保留字段说明、必填、示例、枚举和约束，供响应字段编辑器和成功条件使用。非 204 成功响应没有可读 JSON Schema 时必须警告。

### Spring Boot / Java

扫描器从 Mapping 后的方法签名提取：

| Spring 声明 | qa-platform 参数 |
| --- | --- |
| `@PathVariable` | `path`；名称取 `value`/`name` 或 Java 变量名，始终必填 |
| `@RequestParam` | `query` |
| `@RequestHeader` | `header` |
| `@RequestBody SomeDto` | `SomeDto` 的 JSON 顶层字段映射为 `body` |

`required = false` 或 `Optional<T>` 生成非必填参数；`defaultValue` 生成 `default` 并使该参数非必填。Java `String`、整数包装类型、浮点类型、布尔类型、集合、Map 和数组映射到六个规范类型。`@NotNull`、`@NotBlank`、`@NotEmpty` 标记 DTO 字段必填；`@Size`、`@Min`、`@Max`、`@Pattern`、`@Schema` / `@Parameter` 的可读元数据会尽可能保留。

DTO 解析是静态、保守的：支持类、嵌套类和 record 的字段，并对索引到的嵌套 DTO 递归生成 `children`；循环引用在当前可解析边界停止。未知 DTO、Map、根数组或标量 body 不生成虚假的顶层字段，而是添加警告。`MultipartFile` / `Part` 不生成可执行参数，因为当前运行时只发送 JSON。

### 其他框架与 WebSocket

- Python、Node、Go 等路由在没有可确认的参数元数据时，至少使用请求路径占位符构建 `path` 参数；建议提供 OpenAPI 文档以获得 Query/Header/Body 完整契约。
- AsyncAPI Channel 的路径占位符和 `channels.*.parameters` 构造 WS 握手 `path` 参数。消息 payload 保留在 `messages`，不与 HTTP `body` 参数混用。
- WS `query`/`header` 参数只表示握手配置；消息体字段不应错误地显示在执行表单的 HTTP `body` 分组中。

## 默认值、示例与安全

- 只传播源码或 API 文档明确给出的默认值和约束；扫描器不得凭名称猜测 ID、账号、业务数据或鉴权值。
- 缺失示例时，按类型、format 或 enum 生成安全的确定性示例；这只是编辑器展示/草稿输入，不是运行事实，也不是默认值。
- 名称包含 `authorization`、`cookie`、`password`、`secret`、`token`、`api_key`、`credential` 等敏感含义时，不传播 `default` 或源码示例；仍写入安全变量占位符（例如 `{{ access_token }}`）满足参数示例契约。
- 需要运行时凭证时，由项目变量或安全的模板表达式提供，例如 `{{ access_token }}`；不要将真实值写入 manifest 或 ZIP。
- HTTP API 的 `X-trade-id` 和 `Accept: application/json` 是 qa-platform 的平台级默认 Header，不应重复作为扫描出的业务参数。

## 校验与导入

`validate-import.py` 会拒绝：非数组参数集、空名称、未知位置/类型、非布尔 `required`、非必填 Path 参数、空说明、缺失/空示例、重复 `(in, name)`、Header 名字仅大小写不同的重复项、非 `object` 参数挂载 `children`、同一 object 内重复子字段、子节点声明了不同于父级的位置、非对象 `request_schema.schema` / `response_schema`，以及响应 Schema 中缺少非空说明或示例的可见字段。验证成功后，ZIP 构建器才将递归参数和请求/响应 Schema 写入 API 实体；导入预览和人工审批仍是生效的前置条件。

## 示例

OpenAPI：

```yaml
paths:
  /users/{userId}:
    get:
      parameters:
        - name: userId
          in: path
          required: true
          schema: { type: integer }
        - name: locale
          in: query
          schema: { type: string, default: zh-CN }
```

输出：

```json
[
  {"name": "userId", "in": "path", "type": "integer", "required": true, "description": "路径参数 `userId`（integer）。", "example": 1},
  {"name": "locale", "in": "query", "type": "string", "required": false, "description": "查询参数 `locale`（string）。", "example": "示例值", "default": "zh-CN"}
]
```

Spring：

```java
@PutMapping("/{id}")
void update(@PathVariable Long id,
            @RequestParam(value = "dryRun", required = false, defaultValue = "false") Boolean dryRun,
            @RequestBody UpdateRequest request);
```

若 `UpdateRequest` 包含 `@NotBlank String name` 和 `Boolean enabled`，输出会包含 Path `id`、Query `dryRun` 以及 Body `name`、`enabled`；`name` 为必填，`dryRun` 默认 `false`。
