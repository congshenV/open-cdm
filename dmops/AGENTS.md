# AGENTS.md（dmops）

本文件约束 `dmops/` 目录下的 Python 运维服务，优先级高于仓库根 `AGENTS.md`。根文件里的 Java、前端规则不适用于本目录。

## 定位

- dmops 是平级独立服务，不是 CloudDM 的模块，与 `backend/` 没有编译期依赖。
- 与 CloudDM 只通过 HTTP 交互：前端经 console 的 `/api/dmops/**` 代理进来，dmops 回打 console OpenAPI。
- 不直连业务数据库实例，不直连 sidecar，不理解 RSocket。
- 版本随主版本发布，镜像 tag 复用 `backend/gradle.properties` 的 `cg.clouddm.main.version`。

## 技术栈与命令

- Python 3.11+、Flask 3、SQLAlchemy + PyMySQL、gunicorn。
- 依赖声明在 `requirements.in`，锁定版本在 `requirements.txt`，两者同步维护。

```bash
cd dmops && make venv PYTHON=python3.12 && make install   # 环境准备（Python 3.11+）
cp .env.example .env                                      # 填 DMOPS_IDENTITY_SECRET（与 console 一致）
cd dmops && make run                                       # 本地启动，会自动加载 .env
cd dmops && make lint                                      # compileall
cd dmops && make test                                      # pytest
```

## 目录与分层

- `main.py`：`create_app()` 入口，注册错误处理、请求钩子、路由。
- `app/api/v1/`：Controller，只做参数校验、调用 service、组装响应，不写业务逻辑。
- `app/service/`：业务编排，持有事务边界。
- `app/infra/`：MySQL 访问，纯 SQL 与行对象转换。
- `app/adapter/`：外部依赖隔离（阿里云 SDK 等），便于 mock。
- `app/util/`：认证、统一响应、请求上下文、参数解析等基础设施。
- 新增接口时在 `app/api/v1/` 建 Blueprint，并在 `app/route.py` 注册；URL 统一挂在 `/v1/` 下。

## 编码约定

- 4 空格缩进，单引号，行宽不超过 120，遵循现有文件的 import 分组（标准库、第三方、`app.*`）。
- 配置只从环境变量读取，统一收在 `app/config.py`，不要在业务代码里直接 `os.getenv`。
- 响应统一走 `app/util/web/response.py`：成功用 `success_response`，失败抛 `ApiError`，不要手写 JSON。
- 业务异常用 `ApiError` 表达，带 `code`、`user_message`、`message`、`http_status`；不要吞异常。
- 日志用模块级 `logging.getLogger(__name__)`，关键路径打印 requestId 与上下文，不要打印密钥和 AK/SK。
- 数据库表由 DBA 预先建好，代码里不做 migration；`db.py` 只负责连接池。
- 新增依赖前先确认标准库或现有依赖能否满足，避免为单个小功能引入框架。
- 不把 `.env`、密钥、真实 AK/SK 写进仓库；本地调试用环境变量。

## 安全约束

- 所有 `/v1/**` 请求必须校验 `X-DmOps-User` + `X-DmOps-Signature`，不能因为"请求来自 console"就跳过校验。
- 认证配置在 `app/util/auth/identity.py`，签名算法必须与 console 的 `OpenApiSigner.signString` 字节级一致。
- 新增对外接口时同时评估：是否需要管理员权限、是否会返回凭据、是否需要审计日志。
- dmops 与 CloudDM 同库，**经用户（cong）逐次确认的场景**可以直接读写 CloudDM 的表
  （如 `dm_ds`）；未确认的场景仍只通过 HTTP OpenAPI 交互。例外访问一律收在
  `app/infra/cdm_*_repository.py`，并在代码注释与本文件登记获准日期与范围。
