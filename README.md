# qa-platform

面向项目的 API 自动化测试平台。将 HTTP / WebSocket API 作为可复用资产进行说明、调试和组合，通过上下文变量、断言、结果提取与失败重试形成完整测试流程。

演示地址: https://qa-platform.pp5119259.chatgpt.site/

## 当前能力

- 项目空间：隔离 API、流程和项目级变量。
- API 模板：在项目内统一维护基础地址、公共请求头、查询参数、超时、参数说明和参考案例。
- API 资产：支持 HTTP / WebSocket，记录功能说明、参数文档、参考案例并可直接执行。
- API 目录：API 可归入类似 `/用户服务/用户管理` 的多级业务目录，列表支持按父目录筛选子目录；目录节点悬浮后可新增、重命名和删除空目录。
- 流程编排：按顺序组合 API，支持步骤开关、请求覆盖和拖动式顺序调整（当前为上移/下移）。
- 上下文：按 `项目变量 < 流程变量 < 本次输入 < 步骤提取值` 的优先级合并。
- 模板：在 URL、请求头、查询参数、Body、WS 消息中使用 `{{ variable.path }}`。
- 成功条件：项目级成功条件，API 直接绑定一个条件；未绑定的新/历史 API 继续兼容内置成功契约。
- 校验与提取：支持路径比较、JSON Schema、安全 Python 风格表达式、响应分支，并将响应值提取给后续步骤。
- 失败重试：配置最大尝试次数、间隔和指数退避倍数，每次尝试单独留痕。
- 运行观察：保存请求/响应快照，敏感请求头脱敏；通过 WebSocket 推送运行事件。
- 工程化：后端测试、前端类型检查/构建、GitHub Actions、Docker Compose、CodeGraph 索引规则。

## 技术架构

```text
Vue 3 + Element Plus
        │ REST + WebSocket events
        ▼
FastAPI API layer
        │
        ├── Project / API / Flow / Run services
        └── Flow runner
              ├── Context & template renderer
              ├── HTTP executor (httpx)
              ├── WebSocket executor (websockets)
              └── Assertions / extractors / retry
        │
        ▼
SQLite (SQLAlchemy)
```

## Codex 扫描集成

面向任意被测项目的 HTTP/WebSocket 扫描器已迁入本仓库，源码位于 [`integrations/codex/qa-platform-skill`](integrations/codex/qa-platform-skill)。它优先稳定转换 OpenAPI/Swagger/AsyncAPI，读取项目流程说明，生成可独立维护的模块 JSON 并打包为待审核的 `qa-platform-import` ZIP；平台只会在预览后由人工确认导入，不会因扫描或一键入口直接修改项目资产。

从本仓库安装或更新用户级 Codex Skill：

```bash
./scripts/install-codex-skill.sh
```

已安装旧版时，使用 `--force`；旧目录会先保存为带时间戳的备份：

```bash
./scripts/install-codex-skill.sh --force
```

默认安装目录为 `${CODEX_HOME:-$HOME/.codex}/skills/qa-platform-skill`。维护扫描器或导入格式时，运行 `make test-skill` 与 `make test-skill-contract`，后者覆盖“扫描 → 校验 → ZIP → 平台预览 → 人工确认导入”的真实契约。详见 [Codex Skill 集成说明](docs/integrations/codex-skill.md)。

## 本地启动

需要 Python 3.11+ 和 Node.js 20+。

首次安装依赖：

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

另开终端安装前端依赖：

```bash
cd frontend
npm install
```

完成依赖安装后，在仓库根目录一键启动前后端：

```bash
./scripts/start-dev.sh
```

按 `Ctrl+C` 会同时停止两个进程。也可以分别启动：

```bash
./scripts/start-backend.sh
./scripts/start-frontend.sh
```

支持通过环境变量覆盖监听地址和端口：

```bash
BACKEND_PORT=9000 FRONTEND_PORT=5174 ./scripts/start-dev.sh
```

- Web UI: <http://localhost:5173>
- OpenAPI: <http://localhost:8000/docs>
- Health: <http://localhost:8000/health>

也可以直接运行：

```bash
docker compose up --build
```

访问 <http://localhost:8080>。

为当前本地演示项目补充一组完整的用户管理 API（幂等，可重复执行）：

```bash
cd backend
.venv/bin/python ../scripts/seed-user-apis.py \
  --project-id 62a2cfa1-4aac-4bf1-9b7e-e907d05b4b37
```

示例会创建 `GET/POST/PATCH/DELETE /api/v1/users` 相关接口，并归入 `/用户服务/用户管理`；如果项目中存在网关 HTTP 模板和默认成功条件，会自动绑定它们。

## 配置示例

项目变量：

```json
{
  "base_url": "https://api.example.com",
  "ws_url": "wss://ws.example.com",
  "username": "qa-user"
}
```

HTTP API 请求配置：

```json
{
  "method": "POST",
  "url": "{{ base_url }}/login",
  "headers": { "Content-Type": "application/json" },
  "body": { "username": "{{ username }}", "password": "{{ password }}" },
  "timeout_seconds": 20
}
```

项目级 API 模板可以统一维护公共配置：

```json
{
  "base_url": "{{ base_url }}",
  "headers": {
    "Content-Type": "application/json",
    "Authorization": "Bearer {{ access_token }}"
  },
  "timeout_seconds": 20
}
```

引用该模板的具体 API 只需要保存差异：

```json
{
  "method": "GET",
  "path": "/v1/orders",
  "query": { "symbol": "{{ symbol }}" }
}
```

执行时按照 `模板配置 < API 覆盖 < 流程步骤覆盖/临时执行覆盖` 深度合并。`url` 字段优先；未提供 `url` 时，执行器会自动拼接模板的 `base_url` 与 API 的 `path`。修改模板后，所有引用 API 会在下次执行时使用新配置。

路径参数使用 `{参数名}`（也兼容 `:参数名`）声明，例如 `/users/{user_id}/orders/{order_id}`。登记页会自动识别并生成 Path 参数说明；执行时优先读取请求配置中的 `path_params`，其次读取项目/流程/运行输入的同名上下文变量，并对路径值进行 URL 编码。缺少参数时会返回明确的 `Missing path parameter` 错误。

断言定义可以选择三种引擎：

- `path`：通用路径与操作符比较，兼容流程中已有的内联断言。
- `json_schema`：使用 JSON Schema Draft 2020-12 校验响应结构。
- `expression`：用于跨字段或带参数的业务判断，例如 `response.body['min'] <= response.body['max']`。

表达式只支持比较、布尔逻辑、简单算术、字典/数组访问以及 `len`、`contains`、`exists`、`match`、`starts_with`、`ends_with`、`lower`、`upper` 等白名单函数。运行时使用 AST 白名单和自定义解释器，不调用 Python `eval`/`exec`，也不允许导入、赋值、推导式或任意函数调用。

响应分支用于声明同一个 API 的多种合法返回：

```json
[
  {
    "name": "not-found",
    "match": "response.status_code == 404",
    "schema": {
      "type": "object",
      "required": ["code"]
    },
    "assertions": [],
    "disabled_assertion_ids": [],
    "assertions": []
  }
]
```

有响应分支时，匹配到的预期 4xx 响应可以通过；没有配置响应分支时，系统保留 HTTP 状态码小于 400 的基础检查。所有规则都会执行并形成结构化结果，`warning` 失败不会导致步骤失败。

步骤局部断言与提取器：

```json
{
  "assertions": [
    { "source": "status_code", "operator": "equals", "expected": 200 },
    { "source": "body.success", "operator": "equals", "expected": true }
  ],
  "disabled_assertion_ids": ["project-assertion-id"],
  "extractors": [
    { "name": "access_token", "source": "body.data.token" }
  ],
  "retry": {
    "max_attempts": 3,
    "interval_ms": 1000,
    "backoff_multiplier": 2
  }
}
```

断言操作符包括 `equals`、`not_equals`、`contains`、`exists`、`gt`、`gte`、`lt`、`lte`。响应路径支持字典字段和数组下标，例如 `body.items.0.id`。

## 数据模型

- `Project`：项目及默认变量。
- `ApiTemplate`：项目级 HTTP/WS 公共配置，可被多个 API 实时引用。
- `ApiGroup`：项目级持久化 API 目录；根目录 `/` 为虚拟目录，API 创建或导入时会自动补齐路径目录。
- `ApiDefinition`：协议、请求定义、参数说明与案例。
- `ApiDefinition.group_path`：API 的规范化业务目录路径；`/` 表示未分组，目录不参与 `key` 唯一性。
- `AssertionDefinition`：项目级成功条件、引擎配置、默认参数和严重级别。
- `ApiDefinition.success_assertion_id`：API 直接引用的成功条件。
- `TestFlow`：流程变量及有序步骤定义。
- `TestRun`：一次运行的输入、最终上下文和状态。
- `StepRun`：步骤的单次尝试、耗时、快照、完整断言结果、提取值和错误。

## 自动化部署扩展路线

当前结构适合在流程执行器旁增加“部署执行器”，但不建议直接把 SSH / Kubernetes 操作塞进测试步骤。建议分阶段扩展：

1. 环境与密钥：增加 `Environment`、加密 `Secret`、目标域名白名单和 RBAC。
2. 任务基础设施：将进程内后台任务替换为 Redis + Celery/Dramatiq，支持取消、并发限制和分布式 Worker。
3. 持续测试：增加 Cron、Webhook、GitHub/GitLab 事件触发、报告与通知。
4. 部署能力：新增独立 `DeploymentPipeline`，支持镜像、Kubernetes/SSH Provider、审批关卡、回滚和审计。
5. 测试门禁：部署后触发 qa-platform 流程，将测试结果作为继续发布或自动回滚的条件。

生产化前必须补充：用户认证与权限、请求目标白名单/SSRF 防护、密钥加密、数据库迁移、执行沙箱、速率限制、审计日志和 PostgreSQL 支持。

## 名称建议

仓库名保留 `qa-platform` 最清楚。若需要更有辨识度的产品名，可以使用 **Qaflow**：它强调“API 资产 → 测试流程 → 发布门禁”的主线，同时不会限制未来加入 UI 测试或部署能力。
