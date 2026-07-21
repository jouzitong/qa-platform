# qa-platform 协作说明

本仓库使用 Python 3 + FastAPI + SQLite 构建后端，Vue 3 + Element Plus 构建前端。

- 修改前优先使用 CodeGraph 理解符号与影响范围。
- 后端代码位于 `backend/app/`，测试位于 `backend/tests/`。
- 前端代码位于 `frontend/src/`。
- 保持测试执行引擎与 Web/API 层解耦，协议扩展放在执行器模块中。
- 数据库迁移应通过 Alembic 管理；MVP 初始化阶段允许 SQLAlchemy 自动建表。
- 提交前运行后端测试与前端构建。

CodeGraph 常用命令：

- `codegraph context "<task>"`
- `codegraph query <symbol>`
- `codegraph callers <symbol>`
- `codegraph callees <symbol>`
- `codegraph impact <symbol>`
- 编辑后运行 `codegraph sync`，大规模变更后运行 `codegraph index`。

不要提交 `.codegraph/`、SQLite 数据文件、虚拟环境、`node_modules/` 或构建产物。
