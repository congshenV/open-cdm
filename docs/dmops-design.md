# dmops 设计文档

> dmops（Database Operations Service）是 CloudDM 的运维补充服务，独立部署、独立迭代，
> 通过 console 的 `/api/dmops/**` 反向代理与既有前端同源集成。
>
> 关联文档：
> - `docs/current-architecture.md` — CloudDM 现状与请求链路
> - `docs/dmops-integration-design.md` — console 代理接入方案（已实现）
> - `docs/ops-service-architecture.md` — 运维能力与网络隔离的架构论证

## 1. 定位与边界

### 1.1 做什么

| 域 | 能力 |
|---|---|
| 实例生命周期 | 新建实例、规格查询、实例清单、实例纳管 |
| 库与账号 | 建库、建账号、授权、权限回收 |
| 备份恢复 | 备份发起、备份清单、恢复、过期清理 |
| 任务中心 | 长事务状态跟踪、重试、取消 |

### 1.2 不做什么（明确的边界）

- **不做 SQL 客户端**。查询、编辑器、结果集浏览属于 CloudDM，dmops 不复刻。
- **不做权限模型**。用户、角色、审批属于 CloudDM，dmops 只消费其身份。
- **不直连数据库实例**。一律经 CloudDM 的 console → sidecar 通道执行。
- **不直连 sidecar**。不理解 RSocket，不知道 worker 地址。
- **不读写 CloudDM 的元数据库**。只通过 HTTP API 交互。

### 1.3 与 CloudDM 的关系

```
                    ┌──────────────────────────────┐
clouddm-web ────────┤ /api/entry/**  → console 本体 │
                    └──────────────────────────────┘
                    ┌──────────────────────────────┐
clouddm-web ────────┤ /api/dmops/**  → dmops 代理   │──► dmops
                    └──────────────────────────────┘
                                       ▲
                          dmops 回打 /api/open/**（AK/SK）
```

dmops 是**平级的服务**，不是 CloudDM 的模块。两者的契约只有两组 HTTP 接口：
console 提供给 dmops 的 OpenAPI，以及 dmops 提供给前端的业务 API。

## 2. 技术选型建议

| 项 | 建议 | 理由 |
|---|---|---|
| 语言/框架 | 任意，推荐 JDK 17+ / Spring Boot 3.x | 与 CloudDM 团队技能栈一致，但**不需要**跟 CloudDM 的 Spring Boot 4 绑定 |
| 数据库 | 独立 MySQL/PostgreSQL | 存任务、步骤、资源映射。**禁止**复用 CloudDM 的库 |
| 调度 | 单实例 + DB 任务表 + 定时轮询 | 见 §5.3，不需要工作流引擎 |
| 云 SDK | 阿里云官方 SDK | 建实例、备份、查规格 |
| 部署 | 独立容器/进程，与 console 不同主机 | 已确认 |

**重要**：dmops 与 CloudDM 的版本完全解耦。CloudDM 升级不影响 dmops，反之亦然。

## 3. 对外 API 设计

### 3.1 约定

- 所有接口挂在 `/v1/` 下，console 代理配置 `dmops.proxy.allowed-path=/v1/`，
  只转发该前缀，避免误转发。
- 前端实际访问路径为 `/api/dmops/v1/...`，console 剥掉 `/api/dmops` 后转发为 `{dmopsBase}/v1/...`。
- 统一响应体：

```json
{ "success": true, "code": "OK", "message": "", "data": { } }
```

失败：

```json
{ "success": false, "code": "INSTANCE_NOT_FOUND", "message": "instance 123 not found", "data": null }
```

- 所有响应 HTTP 状态码保持语义正确（200/400/403/404/500），**不要一律返回 200**。
  代理层会原样透传状态码。

### 3.2 身份识别

console 代理转发时注入两个 header：

| Header | 含义 |
|---|---|
| `X-DmOps-User` | 当前登录用户的 uid |
| `X-DmOps-Signature` | `HmacSHA1(uid, dmops.proxy.identity.secret)` |
| `X-Request-Id` | 请求追踪 ID |

**dmops 必须在每个接口校验签名**，校验失败返回 401。
不能假设"来自 console 就可信"——代理是通配转发，路径白名单之外的防护必须由 dmops 自己做。

**必须实现**：dmops 侧对每个 `/v1/**` 接口校验签名，校验失败返回 401。

### 3.3 接口清单（第一期）

#### 实例

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/v1/instance/query` | 查实例列表（分页、按环境/状态过滤） |
| POST | `/v1/instance/create` | 新建实例（**异步**，立即返回 taskId） |
| GET | `/v1/instance/{id}` | 实例详情 |
| POST | `/v1/instance/{id}/register` | 纳管到 CloudDM（注册为数据源） |

`instance/create` 请求体示例：

```json
{
  "engine": "MySQL",
  "version": "8.0",
  "spec": "rds.mysql.c1.large",
  "storageGB": 100,
  "region": "cn-hangzhou",
  "vpcId": "vpc-xxx",
  "vswitchId": "vsw-xxx",
  "database": { "name": "app_db", "charset": "utf8mb4" },
  "account": { "name": "app_user", "password": "***" },
  "grants": [ { "database": "app_db", "privileges": ["SELECT","INSERT","UPDATE"] } ]
}
```

响应：

```json
{ "success": true, "code": "OK", "data": { "taskId": "tsk_20261023_xxx", "status": "PENDING" } }
```

#### 库与账号

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/v1/database/create` | 建库（同步，秒级） |
| POST | `/v1/account/create` | 建账号（同步） |
| POST | `/v1/account/grant` | 授权（同步） |
| POST | `/v1/account/revoke` | 回收权限（同步） |

这类同步接口的成功判定：console `syncQuery` 返回 `success=true` 且无 SQL 错误。

#### 备份

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/v1/backup/create` | 发起备份（异步） |
| GET | `/v1/backup/{id}` | 备份详情 |
| POST | `/v1/backup/query` | 备份清单 |
| POST | `/v1/backup/{id}/restore` | 恢复（异步） |
| DELETE | `/v1/backup/{id}` | 删除备份 |

#### 任务

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/v1/task/{taskId}` | 任务状态与进度（前端**轮询**此接口） |
| POST | `/v1/task/{taskId}/retry` | 重试失败任务 |
| POST | `/v1/task/{taskId}/cancel` | 取消未完成任务 |
| POST | `/v1/task/query` | 任务列表 |

`task` 响应包含步骤级进度，供前端展示：

```json
{
  "taskId": "tsk_20261023_xxx",
  "type": "INSTANCE_CREATE",
  "status": "RUNNING",
  "currentStep": "WAIT_INSTANCE_READY",
  "percent": 40,
  "steps": [
    { "name": "CREATE_INSTANCE", "status": "DONE" },
    { "name": "WAIT_INSTANCE_READY", "status": "RUNNING" },
    { "name": "CREATE_DATABASE", "status": "PENDING" }
  ],
  "result": null,
  "error": null
}
```

#### 健康检查

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/v1/ping` | 连通性验证，返回版本与构建时间 |

## 4. 内部架构

```
┌─ dmops ────────────────────────────────────────────────────┐
│                                                            │
│  api 层          Controller，只做参数校验与响应封装          │
│    ├─ InstanceController / DatabaseController              │
│    ├─ BackupController   / TaskController                  │
│    └─ 统一鉴权拦截器（验 X-DmOps-Signature）                │
│                                                            │
│  orchestration  编排层（核心）                              │
│    ├─ TaskEngine      任务状态机，DB 驱动                   │
│    ├─ StepExecutor    步骤执行与断点续跑                    │
│    └─ Compensator     失败补偿（逆序、幂等）                │
│                                                            │
│  adapter 层                                                 │
│    ├─ AliyunAdapter   阿里云 SDK：实例/备份/规格            │
│    └─ CdmAdapter      CloudDM OpenAPI：SQL/数据源           │
│                                                            │
│  domain         领域服务，纯逻辑无 IO                       │
│                                                            │
│  infra          Mapper、配置、日志                          │
└────────────────────────────────────────────────────────────┘
```

分层原则：

- **Controller 不写业务逻辑**，只做校验、调用编排、组装响应。
- **编排层持有事务状态**，所有长流程都在这里，可中断、可续跑。
- **Adapter 隔离外部依赖**，阿里云 SDK 与 CloudDM 客户端都被封装，便于 mock 测试。

## 5. 任务模型

### 5.1 表结构

```sql
-- 任务主表
CREATE TABLE ops_task (
  id            BIGINT PRIMARY KEY AUTO_INCREMENT,
  task_id       VARCHAR(64)  NOT NULL,
  task_type     VARCHAR(32)  NOT NULL,   -- INSTANCE_CREATE / BACKUP / RESTORE
  status        VARCHAR(16)  NOT NULL,   -- PENDING/RUNNING/DONE/FAILED/CANCELED
  current_step  VARCHAR(64),
  percent       INT DEFAULT 0,
  biz_key       VARCHAR(128) NOT NULL,   -- 幂等键，见 §5.4
  params        TEXT,                    -- 原始请求，JSON
  result        TEXT,                    -- 结果，JSON
  error         TEXT,
  operator      VARCHAR(64)  NOT NULL,   -- uid
  created_at    DATETIME     NOT NULL,
  updated_at    DATETIME     NOT NULL,
  UNIQUE KEY uk_task_id (task_id),
  UNIQUE KEY uk_biz_key (biz_key),
  KEY idx_status (status, updated_at)
);

-- 步骤表，支持断点续跑
CREATE TABLE ops_task_step (
  id         BIGINT PRIMARY KEY AUTO_INCREMENT,
  task_id    VARCHAR(64) NOT NULL,
  step_name  VARCHAR(64) NOT NULL,
  seq        INT         NOT NULL,
  status     VARCHAR(16) NOT NULL,       -- PENDING/RUNNING/DONE/FAILED/SKIPPED
  ext_ref    VARCHAR(256),               -- 外部引用，如 aliyunInstanceId
  error      TEXT,
  started_at DATETIME,
  ended_at   DATETIME,
  UNIQUE KEY uk_task_step (task_id, step_name)
);

-- 云资源映射，便于对账
CREATE TABLE ops_resource (
  id              BIGINT PRIMARY KEY AUTO_INCREMENT,
  resource_type   VARCHAR(32) NOT NULL,  -- INSTANCE
  cloud_id        VARCHAR(128) NOT NULL, -- 阿里云实例 ID
  cdm_ds_id       BIGINT,                -- CloudDM 数据源 ID，纳管后回填
  region          VARCHAR(32),
  status          VARCHAR(16),
  created_at      DATETIME NOT NULL,
  UNIQUE KEY uk_cloud_id (cloud_id)
);
```

### 5.2 状态机

```
PENDING ──► RUNNING ──► DONE
              │
              ├──► FAILED ──(retry)──► PENDING
              └──► CANCELED
```

步骤级：

```
PENDING ──► RUNNING ──► DONE
              │
              └──► FAILED   （记录 error，任务整体 FAILED）
```

### 5.3 调度实现

**推荐：单实例 + 定时轮询**

```java
@Scheduled(fixedDelay = 5000)
public void dispatch() {
    // 取 RUNNING 且 updated_at 超过 N 秒未更新的任务，推进其当前步骤
    // 取 PENDING 任务，置 RUNNING 后开始第一步
}
```

- 建实例与备份都是**阿里云侧异步执行**，dmops 本地没有重活，只需轮询云侧状态。
- 单实例足够；任务量上来后再加 "DB 行锁抢占" 支持多副本（与 CloudDM 的
  `AsyncTaskServiceImpl` 同思路），不要提前引入工作流引擎。

### 5.4 幂等设计（关键）

每类操作的幂等键：

| 操作 | 幂等键 | 保证 |
|---|---|---|
| 建实例 | 客户端传入 `clientToken`（或 `operator + 业务单号`） | `uk_biz_key` 唯一约束，重复提交返回已有 taskId |
| 建库 | `dsId + databaseName` | SQL 用 `CREATE DATABASE IF NOT EXISTS` |
| 建账号 | `dsId + accountName + host` | `CREATE USER IF NOT EXISTS` |
| 授权 | `dsId + account + database + privileges 摘要` | `GRANT` 天然幂等 |
| 备份 | `dsId + 时间桶` | 同一时间桶内不重复发起 |

**任务重试必须从失败步骤继续**，不要从头重跑——否则会造成重复建实例。

## 6. 与 CloudDM 的交互

### 6.1 执行 SQL

```
dmops ──POST /api/open/query/syncQuery──► console ──RSocket──► sidecar ──► DB
```

- 鉴权：AK/SK 签名，header 传 `AccessKeyId` / `Signature` / `SignatureMethod` / `SignatureNonce`
- 请求体：

```json
{
  "levels": ["ds:1234", "database:app_db"],
  "queryType": "RequestQuery",
  "queryString": "CREATE DATABASE IF NOT EXISTS `app_db` DEFAULT CHARACTER SET utf8mb4",
  "queryForce": false
}
```

- **硬限制：54 秒超时**。超过此阈值的语句必须拆分或改为异步作业，第一期不做。
  建库、建账号、授权都是秒级，满足要求。

### 6.2 纳管实例

实例创建完成、库与账号就绪后，调 CloudDM 的数据源 OpenAPI 注册：

| 用途 | 接口 |
|---|---|
| 新增数据源 | `POST /api/open/datasource/...`（见 `DataSourceApi`） |
| 查询数据源 | `POST /api/open/datasource/listDs` |
| 数据源详情 | `POST /api/open/datasource/detailDs` |

纳管成功后把返回的 `dsId` 回填到 `ops_resource.cdm_ds_id`，形成闭环。

### 6.3 专用账号

为 dmops 单独申请一对 CloudDM AK/SK，绑定专用子账号：

- 权限收敛到"对指定数据源执行 SQL" + "管理数据源"
- 审计日志能够区分"人操作"与"dmops 操作"（靠 AccessKeyId 区分）

## 7. 配置

### 7.1 console 侧（已实现）

```properties
dmops.proxy.enabled=false
dmops.proxy.base-url=http://dmops-host:8080
dmops.proxy.connect-timeout-ms=3000
dmops.proxy.read-timeout-ms=60000
dmops.proxy.identity.secret=<与 dmops 共享的随机串，必填>
dmops.proxy.allowed-path=/v1/
```

默认 `enabled=false`，未配置时 `/api/dmops/**` 返回 503，不影响 CloudDM 原有功能。

**强制约束（已实现）**：`identity.secret` 为必填。开启代理但该值为空时，
代理拒绝启动并在日志报错，所有 `/api/dmops` 请求返回 503。
这是刻意的——空密钥意味着签名无效，任何人都能伪造 `X-DmOps-User`。

#### 配置的两种来源与优先级

`identity.secret` 支持两种注入方式，**启动参数优先于 properties 文件**：

**方式一：properties 文件（推荐正式部署用）**

编辑安装目录下的 `console.properties`（打包产物，位于 `<APP_HOME>/conf/console.properties`）：

```properties
dmops.proxy.enabled=true
dmops.proxy.base-url=http://10.0.1.20:8080
dmops.proxy.identity.secret=<64 位十六进制串>
dmops.proxy.allowed-path=/v1/
```

源码中的默认值在 `backend/clouddm-boot/boot-console/src/main/resources/default_console.properties`
的 `dmops Proxy` 分节，已被打包进发行包的默认配置。

**方式二：启动参数（适合临时验证、或不想把密钥写入文件）**

编辑 `<APP_HOME>/bin/setenv.sh`，追加到 `JAVA_OPTS`：

```bash
JAVA_OPTS="${JAVA_OPTS} -Ddmops.proxy.enabled=true"
JAVA_OPTS="${JAVA_OPTS} -Ddmops.proxy.base-url=http://10.0.1.20:8080"
JAVA_OPTS="${JAVA_OPTS} -Ddmops.proxy.identity.secret=$(cat /run/secrets/dmops_secret)"
```

**为什么这里用 `-D` 而不是命令行参数**：CloudDM 的启动链路是
`startup.sh` → `catalina.sh start` → `classworlds Launcher start <args>` → `DmConsoleLauncher.main(args)`，
而 `DmConsoleLauncher` 把 **`args[0]` 当作动作参数**（只接受 `start` / `stop`）。因此
`--dmops.proxy.identity.secret=xxx` 这种 Spring 风格命令行参数不能直接追加在 `startup.sh` 后面，
必须用 `-D` 系统属性注入。`-D` 是 JVM 级属性，Spring Boot 会将其纳入 Environment，
优先级**高于** properties 文件。

**校验顺序**：`-D` > `console.properties` > `default_console.properties` 中的默认值。

**关于命令行参数（已核实不可用，不要尝试）**：

启动链路是 `startup.sh` → `catalina.sh start` → `do_start` → `Launcher start "$@"` →
`DmConsoleLauncher.main(args)`。其中：

- `Launcher start` 已经把 `start` 占用为 `args[0]`；
- `DmConsoleLauncher` 会把 `args[0]` 当动作参数，不是 `start` / `stop` 就抛
  `UnsupportedOperationException`；
- 即使把参数追加到 `catalina.sh start` 后面，它也会落在 `args[1]` 之后，
  Spring Boot 的 `--key=value` 解析要求从 `args[0]` 开始逐个匹配。

因此 **`--dmops.proxy.xxx=yyy` 形式的命令行参数在这套启动链路里不可用**，
只能用 `-D` 系统属性。这是我在实测代码后确认的约束，不是推测。

**注意**：`startup.sh` 本身不透传额外参数（固定执行 `catalina.sh start`），
所以想加参数只能改 `setenv.sh` 的 `JAVA_OPTS`。统一用 `-D` 是唯一稳妥的方式。

### 7.1.1 `identity.secret` 是什么

一段只有 console 与 dmops 知道的共享密钥，用于给"转发过去用户身份"做签名。

**为什么需要**：dmops 在另一台主机，"请求来自 console 的 IP"不能作为信任依据（IP 可伪造、可绕开）。
所以 console 用密钥对 uid 签名，dmops 用同一密钥重算比对，从而实现认证 + 防篡改。

**签名流程**：

```
console 校验 JWT 得到 uid
  → signature = HmacSHA1(uid, secret)          # 复用 OpenApiSigner.signString
  → 转发时带 X-DmOps-User: uid / X-DmOps-Signature: signature
dmops 收到后
  → 用同一 secret 对 X-DmOps-User 重算
  → 与 X-DmOps-Signature 比对：相等则信任，不等返回 401
```

**生成方式**：

```bash
openssl rand -hex 32
```

把同一串配置到 console 的 `dmops.proxy.identity.secret` 与 dmops 的 `dmops.identity.secret`。

**泄露后果**：攻击者可伪造任意 uid 直接打 dmops，绕过 CloudDM 的登录与权限。
因此生产环境不要写进 properties 明文提交到仓库，用环境变量或密钥管理服务注入。

### 7.1.2 `allowed-path` 是什么

`/api/dmops/**` 是通配转发，任何路径都会被代理到 dmops。若不设边界，
dmops 上任何接口（包括你不打算暴露的内部接口）都会自动暴露给前端。

`allowed-path` 是**路径前缀白名单**，只有匹配的路径才转发，其余返回 403。

`allowed-path=/v1/` 的行为：

| 前端请求 | 结果 | 原因 |
|---|---|---|
| `/api/dmops/v1/instance/create` | 转发 | 以 `/v1/` 开头 |
| `/api/dmops/v1/task/123` | 转发 | 以 `/v1/` 开头 |
| `/api/dmops/admin/shutdown` | **403** | 不在白名单 |
| `/api/dmops/internal/metrics` | **403** | 不在白名单 |

配成空字符串即全部放行（不建议）。多前缀用逗号分隔，如 `/v1/,/v2/`。

**这也是要求 dmops 所有接口统一挂 `/v1/` 的原因**——不只为了版本管理，更是为了让白名单有明确边界。

### 7.1.3 已修复的路径穿越漏洞

初版实现只做前缀字符串匹配，存在可绕过问题。**已实测验证** OkHttp 会规范化 dot segment：

| 攻击输入 | 白名单前缀检查 | OkHttp 实际请求 | 结果 |
|---|---|---|---|
| `/api/dmops/v1/../../admin/x` | `startsWith("/v1/")` → **通过** | `/admin/x` | 绕过白名单 |
| `/api/dmops/v1/%2e%2e/admin` | 通过 | `/admin` | 编码形式同样绕过 |

修复方式：在匹配白名单**之前**先检查路径是否含穿越特征，命中直接拒绝：

```java
private boolean hasPathTraversal(String restPath) {
    if (restPath.contains("..") || restPath.contains("\\")) {
        return true;
    }
    String lower = restPath.toLowerCase();
    return lower.contains("%2e") || lower.contains("%00") || lower.contains("%5c") || lower.contains("%2f");
}
```

### 7.2 dmops 侧

```properties
server.port=8080
dmops.identity.secret=<与 console 共享>
dmops.cdm.base-url=http://console-host:8222
dmops.cdm.access-key=***
dmops.cdm.secret-key=***
dmops.aliyun.region=cn-hangzhou
dmops.aliyun.access-key-id=***
dmops.aliyun.access-key-secret=***
dmops.task.poll-interval-sec=5
dmops.task.step-timeout-sec=1800
```

**阿里云 AK/SK 只存在于 dmops**，绝不经过 console，也不落到前端。

## 8. 前端集成

### 8.1 入口

在 CloudDM 顶部「数据查询 / 返回控制台」区域新增一项 **运维控制台**，点击进入独立页面。

### 8.2 路由与目录

```
frontend/src/views/dmops/          全新目录，不引用主站 store
frontend/src/services/http/dmops.js  独立 axios 实例
```

路由新增 `path: 'dmops'`。

### 8.3 请求封装

```js
// src/services/http/dmops.js
import axios from 'axios';

const dmops = axios.create({ baseURL: '/api/dmops', timeout: 60000 });
// 统一携带 locale，与主站一致
export default dmops;
```

好处：前端代码里看不到 dmops 的真实地址，将来 dmops 换主机/端口无需改前端。

### 8.4 长任务交互

- 提交建实例/备份后立即拿到 `taskId`；
- 跳转到任务详情页，**每 2 秒轮询** `GET /api/dmops/v1/task/{taskId}`；
- 任务终态（DONE/FAILED/CANCELED）时停止轮询。

不做 WebSocket——代理层转发现有 WebSocket 通道会给 console 增加复杂度，轮询已足够。

## 9. 开发与联调顺序

| 阶段 | 内容 | 验收 |
|---|---|---|
| 1 | dmops 骨架 + `/v1/ping` | `curl console/api/dmops/v1/ping` 通 |
| 2 | 鉴权拦截器（验 signature） | 错误签名返回 401 |
| 3 | 任务表 + 状态机 + `/v1/task/{id}` | 手工塞数据能查到进度 |
| 4 | 建库/建账号/授权（走 console OpenAPI） | 对测试实例建出库与账号 |
| 5 | 建实例（阿里云 API）+ 全流程编排 | 端到端建出实例并纳管 |
| 6 | 备份/恢复 | 备份产物可在云侧查到 |
| 7 | 前端页面 | 菜单进入、提交、轮询、展示 |

## 10. 风险

1. **代理层是唯一入口**。console 不可用时运维控制台也打不开。可接受（主站同样依赖 console）。
2. **54 秒 SQL 超时**。大表变更、大批量授权无法走同步接口。第一期规避；
   后续若需要，应在 CloudDM 增加异步 SQL 口子（复用其 `AutoExecService`），而不是在 dmops 造轮子。
3. **通配转发放大攻击面**。三重防护：console 代理层强制 JWT + `allowed-path` 白名单；
   dmops 自己验签名；dmops 内部仍需参数校验与越权校验。
4. **实例创建是"部分失败"高发区**。库/账号已建但纳管失败时，不要自动删库，
   标记 `ORPHAN` 交人工处理，避免误删生产数据。
5. **云 API 限流与配额**。建实例、备份都有配额限制，需在编排层做前置校验与退避重试。
