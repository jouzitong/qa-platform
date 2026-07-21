# qa-platform

面向项目的 API 自动化测试平台。将 HTTP / WebSocket API 作为可复用资产进行说明、调试和组合，通过上下文变量、断言、结果提取与失败重试形成完整测试流程。

## 当前能力

- 项目空间：隔离 API、流程和项目级变量。
- API 模板：在项目内统一维护基础地址、公共请求头、查询参数、超时、参数说明和参考案例。
- API 资产：支持 HTTP / WebSocket，记录功能说明、参数文档、参考案例并可直接执行。
- 流程编排：按顺序组合 API，支持步骤开关、请求覆盖和拖动式顺序调整（当前为上移/下移）。
- 上下文：按 `项目变量 < 流程变量 < 本次输入 < 步骤提取值` 的优先级合并。
- 模板：在 URL、请求头、查询参数、Body、WS 消息中使用 `{{ variable.path }}`。
- 校验与提取：支持响应路径断言，并将响应值提取给后续步骤。
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

步骤断言与提取器：

```json
{
  "assertions": [
    { "source": "status_code", "operator": "equals", "expected": 200 },
    { "source": "body.success", "operator": "equals", "expected": true }
  ],
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
- `ApiDefinition`：协议、请求定义、参数说明与案例。
- `TestFlow`：流程变量及有序步骤定义。
- `TestRun`：一次运行的输入、最终上下文和状态。
- `StepRun`：步骤的单次尝试、耗时、快照、提取值和错误。

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
