# 运维补充服务（ops-service）架构设计 v2

> 目标：为 CloudDM 补充运维能力（新建实例、建库、账号与授权管理、备份恢复），
> 业务逻辑完全在 CloudDM 之外，通过接口交互；解决跨网络隔离问题。
>
> **v2 修订要点（基于 2026-10-22 补充）**：
> 1. 备份恢复改为调用阿里云 API，**不再需要在 VPC 内部署任何新组件**，"ops-agent" 方案作废。
> 2. 调用链路确认为 `前端 → ops-service → console → sidecar`，ops-service 是唯一后端入口。

## 1. 结论摘要

- **网络隔离问题不需要任何新解法**。ops-service 与 CloudDM console 同置于控制面（可访问阿里云 API 侧），
  所有涉及实例的动作都通过 console 的既有 OpenAPI 转发到 sidecar 执行。VPC 内只保留原有的 sidecar，
  **不新增任何常驻进程、不新增任何入站规则**。
- ops-service 唯一需要的能力是**异步任务管理**，承担两类长事务：云 API 侧的长耗时操作（实例创建、
  备份），以及超过 syncQuery 54 秒限制的 DDL。
- **CloudDM 侧需要开一个异步 SQL 口子**。经核验，当前 `openapi` 仅有 `syncQuery`（54 秒超时硬编码），
  没有异步 SQL 接口；但 console 已内置完整的 `AutoExecService`（作业/任务两级，支持重试、停止、跳过）
  与 `AsyncTaskServiceService`（支持暂停/恢复/取消/重试/依赖），**口子只需薄封装，不需要新建机制**。

## 2. 调用链路（已确认）

### 原 CloudDM 功能（不变）

```
clouddm-web ──► clouddm-console ──► clouddm-sidecar
clouddm-web ──► clouddm-sidecar        （直连场景）
```

### 自定义运维功能（新增）

```
clouddm-web ──► ops-service ──► clouddm-console ──► clouddm-sidecar   （涉及实例）
clouddm-web ──► ops-service ──► 阿里云 OpenAPI                        （不涉及实例）
clouddm-web ──► ops-service ──► clouddm-console                       （仅需 console 侧数据）
```

要点：

- **前端只与 ops-service 交互**，ops-service 是运维域的唯一后端入口。
- ops-service **不直接连 sidecar**。所有实例操作一律经 console 转发，复用 console 已有的：
  连接池、worker 路由（`RSocketSendDTO.clusterId/workerSeqNumber`）、权限模型、审计日志。
- 好处：ops-service 完全不需要理解 RSocket、不需要知道 sidecar 的地址、不需要持有数据源凭据。

## 3. 已验证的 CloudDM 关键机制

| 机制 | 代码依据 | 对设计的含义 |
|---|---|---|
| sidecar 主动出站连 console，TLS，断线 5s 自动重连 | `WorkerRSocketClient.prepareRequestMono()` | 隔离问题的既有解法，无需改动 |
| console RSocket 端口 `clouddm.rsocket.console.port`（默认 8008） | `ConsoleConfig` | 仅需既有出站白名单 |
| 对外 OpenAPI 层，AK/SK 签名鉴权 | `controller/openapi/*`、`OpenApiSessionManager` | 复用鉴权，不自建 |
| **同步** SQL 接口，54 秒超时硬编码 | `QueryApi.syncQuery()` | 短 DDL 可用，长 DDL 需异步口子 |
| **无**异步 SQL 的 openapi 接口 | 仅 `syncQuery` 一个查询方法 | 需新增口子 |
| 已有异步作业引擎（作业/任务两级） | `AutoExecService`：`createJob/startJob/dispatchJob/retryJob/stopJob/skipTask` | 口子复用此引擎 |
| 已有异步任务框架（暂停/恢复/取消/重试/依赖） | `AsyncTaskServiceService.submitTask()`、`AsyncTaskConfig`（含 `subTask`/`parallel`/`dependOnBizId`） | 同上 |
| 可定向投递到具体 sidecar | `RSocketSendDTO.clusterId/workerSeqNumber` | 精确路由到目标隔离网络 |
| 数据源 OpenAPI（增删改查） | `DataSourceApi`：`listDs/detailDs/deleteds/updateaccountandpassword` 等 | 新实例纳管复用 |

## 4. 动作与通道映射

| 动作 | 是否触碰实例 | 通道 | 是否异步 | CloudDM 改动 |
|---|---|---|---|---|
| 新建实例、查规格、计费 | 否 | 阿里云 OpenAPI | 是（分钟级） | 0 |
| 备份（RDS 快照 / 逻辑备份） | 否（阿里云侧执行） | 阿里云 OpenAPI | 是（分钟~小时） | 0 |
| 恢复 | 否（阿里云侧执行） | 阿里云 OpenAPI | 是 | 0 |
| 建库 `CREATE DATABASE` | 是（SQL） | console → sidecar | 短则同步，长则异步 | 0（短）/ 异步口子（长） |
| 建账号 `CREATE USER` | 是（SQL） | console → sidecar | 短，同步 | 0 |
| 授权 `GRANT/REVOKE` | 是（SQL） | console → sidecar | 短，同步 | 0 |
| 实例纳管（建完注册进 CloudDM） | 否 | console OpenAPI | 否 | 0 |
| 查实例连接信息 | 否 | console OpenAPI | 否 | 0 |

**关键结论：除"长 DDL 异步化"外，CloudDM 侧不需要任何新代码。**

## 5. ops-service 内部架构

ops-service 的本质是：**云资源生命周期编排器 + 异步任务中心 + 实例 SQL 透传代理**。

```
┌─ ops-service ──────────────────────────────────────────────┐
│                                                            │
│  API 层（REST，对前端）                                     │
│    ├─ /instance/**     实例生命周期                        │
│    ├─ /backup/**       备份与恢复                          │
│    ├─ /database/**     建库/建账号/授权（SQL 透传）        │
│    └─ /task/**         统一任务查询/取消/重试              │
│                                                            │
│  编排层（核心）                                             │
│    ├─ 任务状态机（持久化，可恢复）                          │
│    ├─ 步骤编排（建实例→等就绪→建库→建账号→授权→纳管）      │
│    └─ 补偿/回滚（失败时按步骤逆序清理）                    │
│                                                            │
│  适配层                                                     │
│    ├─ AliyunAdapter   阿里云 SDK 封装（实例/备份/规格）     │
│    └─ CdmAdapter      CloudDM OpenAPI 封装（SQL/数据源）    │
│                                                            │
│  存储                                                       │
│    └─ 任务表、步骤表、资源映射表（独立库，不碰 CloudDM 库） │
└────────────────────────────────────────────────────────────┘
```

### 5.1 任务状态机（替代原先的"执行器"）

由于备份与建实例都是**阿里云侧异步执行**，ops-service 不需要在本地跑重活，只需要：

1. 调阿里云 API 拿到 `requestId` / `taskId`；
2. 持久化任务记录（状态 `PENDING → RUNNING → DONE/FAILED`）；
3. **轮询或接收阿里云回调**更新状态；
4. 状态变更时通知前端（WebSocket / SSE / 前端轮询）。

这比"在 VPC 里跑 mysqldump"简单得多：无大文件传输、无本地磁盘、无进程隔离问题。

推荐的调度实现（按复杂度递增）：

| 方案 | 适用 | 评价 |
|---|---|---|
| 单实例 + 定时轮询（每 N 秒扫未完成任务） | 任务量小、部署单副本 | **推荐起步**，最简单 |
| 数据库行锁 + 多副本抢占 | 多副本部署 | 与 CloudDM 的 `AsyncTaskServiceImpl` 同思路 |
| 引入消息队列 / 工作流引擎（Temporal 等） | 步骤编排复杂、需强一致性 | 过度设计，暂不建议 |

**明确建议**：先用"数据库任务表 + 定时轮询"，不要引入 Temporal/XXL-Job。
编排步骤数只有 5~6 个，状态机手写足够清晰，引入工作流引擎会增加一个需要运维的组件。

### 5.2 步骤编排示例：新建实例全流程

```
1. 校验配额/规格（阿里云 API，同步）
2. 创建实例（阿里云 API，异步）        → 记录 cloudInstanceId
3. 轮询实例状态至 Running             → 超时则任务 FAILED
4. 初始化库（console syncQuery）       → 幂等：IF NOT EXISTS
5. 建账号（console syncQuery）         → 幂等：IF NOT EXISTS
6. 授权（console syncQuery）           → 幂等：可重复执行
7. 注册为 CloudDM 数据源（DataSourceApi）→ 记录 dsId
8. 完成，返回实例信息 + dsId
```

每一步都记录"已执行"标记，任务中断后可从断点续跑。失败时的补偿策略：

- 步骤 2~3 失败：无残留，直接 FAILED。
- 步骤 4~6 失败：库/账号已建但未纳管，标记 `ORPHAN` 供人工处理（不建议自动删库，风险过高）。
- 步骤 7 失败：实例与库已就绪，仅纳管失败，可单步重试。

### 5.3 备份的特殊考虑

- **备份产物不出 VPC**。阿里云备份直接落在 OSS 或云侧快照，ops-service 只保存 `backupId` / `oss://路径`
  与元数据。这消除了原方案里"大文件打爆控制面带宽"的问题。
- **跨账号/跨地域**：备份若需恢复到其他实例，走阿里云侧的跨实例恢复 API，ops-service 仍只做编排。
- **保留策略**：ops-service 记录备份清单与过期时间，定期清理由它自己的定时任务发起（调阿里云 API），
  不依赖 CloudDM。

## 6. CloudDM 侧要开的口子

| 口子 | 用途 | 改动量 | 优先级 |
|---|---|---|---|
| `POST /openapi/query/syncQuery` | 短 DDL（建库/账号/授权） | **0，已存在** | — |
| `POST /openapi/datasource/*` | 实例纳管、查连接信息 | **0，已存在** | — |
| **新增** `POST /openapi/query/asyncExec` | 长 DDL、批量变更 | 薄封装 `AutoExecService` | P1 |
| **新增** `POST /openapi/query/asyncTask/{id}` | 查异步任务状态 | 薄封装 | P1 |
| **新增** `POST /openapi/query/asyncTask/{id}/cancel` | 取消任务 | 薄封装 | P2 |

异步口子的实现建议（不改动既有逻辑，只加一层）：

```
OpenApiAsyncExecController
  ├─ 鉴权：复用 OpenApiSessionManager（AK/SK）
  ├─ 入参：dsId/levels + sql 列表 + bizId（幂等键）
  ├─ 调用：AutoExecService.createJob(...) → startJob(...)
  └─ 返回：jobBizId，供后续查询
```

`AutoExecService.createJob(AutoExecCreateMO, Stream<SplitScript>)` 已经接受拆分好的 SQL 流，
ops-service 侧负责把 DDL 文本拆成 `SplitScript`，或由口子内部调用现有 SQL 解析器拆分。

## 7. 鉴权与会话

ops-service 对前端、对 CloudDM 各用一套鉴权：

**前端 → ops-service**

- 复用 CloudDM 的 JWT（前端已持有），ops-service 用 CloudDM 公钥验签；
- 或前端带 JWT 调 `console/api/ops/**` 由 console 代理（约 50 行），换取 ops-service token。

**ops-service → CloudDM**

- 用 CloudDM 的 **AK/SK 签名**（`OpenApiSessionManager` 已支持从 header 读取
  `AccessKeyId/Signature/SignatureMethod/SignatureNonce`）。
- 建议为 ops-service 单独申请一对 AK/SK，绑定一个专用子账号，权限收敛到"仅能对指定数据源执行 SQL +
  管理数据源"。这样审计日志里能清晰区分"人操作"与"ops-service 操作"。

## 8. 方案对比：为什么不需要 ops-agent

| 方案 | 是否需要 VPC 内新组件 | 备份怎么跑 | 评价 |
|---|---|---|---|
| v1：独立 ops-agent（mysqldump 本地执行） | 需要 | 本地导出 + 上传 OSS | **作废**。备份走云 API 后完全没必要 |
| v1：复用 sidecar 插件 jar | 不需要（复用） | 同上 | 作废。且与 SDK 版本绑定 |
| **v2：纯云 API + console 透传** | **不需要** | 阿里云侧执行 | **推荐**。VPC 零新增，架构最简 |

## 9. 风险

1. **备份能力受限于云厂商**。若某些自建实例（非 RDS）阿里云 API 管不到，备份无法覆盖。
   这类实例只能回退到"经 console 执行 SQL 逻辑导出"，受 54 秒限制，需单独评估。
2. **幂等性必须自己做**。ops-service 的每个步骤都要有幂等键（如 `bizId + step`），
   否则任务重试会造成重复建库或重复授权。
3. **长 DDL 的异步口子是新增代码**。虽然薄，但它是唯一真正需要在 CloudDM 里写代码的地方，
   需要随 CloudDM 升级维护（建议放在独立 controller 文件，减少与上游冲突）。
4. **不要污染 CloudDM 数据库**。ops-service 使用独立库，只通过 API 与 CloudDM 交互。
   一旦直接读写 CloudDM 的表，就再也无法干净升级。

## 10. 落地顺序

| 期次 | 范围 | CloudDM 改动 | VPC 新增组件 |
|---|---|---|---|
| 第一期 | 新建实例 + 建库 + 建账号 + 授权 + 纳管 | **0** | **0** |
| 第二期 | 备份 / 恢复（阿里云 API）+ 任务中心 | **0** | **0** |
| 第三期 | 长 DDL 异步化、批量变更 | 异步 SQL 口子 | **0** |

第一期与第二期均可零侵入 CloudDM 完成。
