# CloudDM 当前架构与请求链路

> 基于对仓库源码的实际核验（2026-10-22），标注每一条结论的代码依据。
> 适用于 open-cdm 4.5.1 分支。

## 1. 结论摘要

- **前端不直连 sidecar**。所有请求都打到 console，sidecar 不暴露任何 HTTP 业务接口
  （`cgdm-sidecar` 全模块无 `@RestController`）。
- **链路不是同一条**，分为三类：
  1. **一般功能**（用户、权限、数据源管理、审批、审计等）：`web → console` 即结束，**不碰 sidecar**。
  2. **SQL 查询 / 元数据浏览 / 导出**：`web → console → sidecar → 数据库`，console 是中间人。
  3. **查询结果回传**：不走 HTTP 响应，而是 `sidecar → console → WebSocket → web` 异步推送。
- **两个方向相反的长连接**，这是理解整套架构的关键：
  - `web → console`：WebSocket（前端发起）。
  - `sidecar → console`：RSocket over TLS（sidecar 发起，因为 sidecar 在隔离网络内，只能出站）。
- **端口**：console 业务 HTTP `8222`；console RSocket `8008`；sidecar HTTP `8223`；元数据库 MySQL。
  sidecar 的 `8223` 在开源代码里没有业务 Controller，实质是空转端口，不要依赖它。

## 2. 组件与职责

| 组件 | 职责 | 关键代码 |
|---|---|---|
| `clouddm-web` | Vue 3 前端，静态资源由 console 一并托管 | `frontend/` |
| `clouddm-console` | 业务中枢：鉴权（JWT）、权限判定、数据源管理、审批、审计、异步任务调度、WebSocket 推送、RSocket 服务端 | `cgdm-console` |
| `clouddm-sidecar` | 数据面执行器：持有 JDBC 连接池、执行 SQL、跑导出、跑自动执行作业 | `cgdm-sidecar` |
| 元数据库（MySQL） | console 的全部状态：用户、数据源、worker 注册、会话、任务、审计 | `cgdm-dao` |
| 插件（数据源 / Provider） | 各数据库的驱动与协议实现，以及钉钉/企微/飞书等集成 | `clouddm-plugins` |

## 3. 三条链路

### 3.1 一般功能：`web → console`（不经 sidecar）

**适用**：登录鉴权、用户与角色、数据源增删改查（配置层面）、权限与审批、审计查询、系统设置、国际化。

```
web ──HTTPS REST──► console ──JDBC──► 元数据库
```

- 入口前缀 `DmControllerUrlPrefix.CONSOLE_PREFIX = "/api/entry"`
- 鉴权：`@RequestAuth` 注解 + JWT（`JwtService`），cookie 名 `dm_jwt_token`
- 这一层**完全不涉及数据库实例连接**，因此天然不受网络隔离影响。

### 3.2 SQL 查询 / 元数据浏览 / 导出：`web → console → sidecar → DB`

```
web ──HTTPS REST──► console ──RSocket(TLS :8008)──► sidecar ──JDBC──► 数据库实例
```

关键步骤（以查询为例，代码在 `QueryServiceImpl`）：

1. 前端 `POST /api/entry/editor/query/...`
2. console 找到数据源绑定的集群（`dm_ds.bind_cluster_id`）
3. 从 worker 注册表选出已连接的 sidecar：
   `systemDal.workerMapper().queryConnectedByClusterId(clusterId)`
4. 构造 `RSocketSendDTO` 并**显式指定目标 worker**：
   ```java
   sendDTO.setClusterId(worker.getClusterId());
   sendDTO.setWorkerSeqNumber(worker.getWorkerSeqNumber());
   sendDTO.setWorkerIP(worker.getWorkerIp());
   sendDTO.setRSocketSendType(RSocketSendType.SPECIFIED);
   ```
5. 通过注解式 RPC 调用 sidecar 的实现：`ExecuteRService` → `ExecuteRServiceProvider`
6. sidecar 用数据源插件建立/复用 JDBC 会话，执行 SQL
7. 结果以 `WS_RES_QUERY` 等类型经 **console 的 WebSocket 回传**给前端

涉及的主要 RPC 接口（均为 `@RSocketApiClass`）：

| 接口 | 方向 | 用途 |
|---|---|---|
| `ExecuteRService` | console → sidecar | 执行 SQL、会话管理 |
| `MetaRService` | console → sidecar | 库表元数据浏览 |
| `ResultSetRService` | console → sidecar | 结果集分页拉取 |
| `AutoExecRService` | console → sidecar | 自动执行作业 |
| `ToolsRService` | console → sidecar | 线上工具会话（如 online DDL） |
| `SshRService` | console → sidecar | SSH 探测与连通性测试 |
| `DriversRService` | console → sidecar | 驱动下载 |
| `NotifyRService` | sidecar → console | 反向通知（转换进度、失败） |

### 3.3 结果回传：`sidecar → console → WebSocket → web`

**这是一个容易误解的点**：查询的 HTTP 请求通常只负责"下发"，结果不通过 HTTP 响应体返回。

- 前端 WebSocket 地址：`ws(s)://{window.location.host}/api/entry/ws/channel`
  （代码：`frontend/src/store/actions.js` → `createWebSocket(...)`）
- 后端端点：`@ServerEndpoint(DmControllerUrlPrefix.CONSOLE_PREFIX + "/ws/channel")`
  （代码：`WsChannel`）
- 消息类型（`WsType`）：`WS_REQ_QUERY` / `WS_RES_QUERY` / `WS_RES_ERROR` / `WS_RES_ASYNC_EVENT` /
  `WS_RES_EXPORT_EVENT` / `WS_RES_DRIVER_DOWNLOAD_EVENT` / `WS_SYS_STATUS`
- **WebSocket 只连 console，不连 sidecar**。sidecar 的结果先回到 console，再由 console 推给前端。

例外：OpenAPI 的同步查询 `POST /api/open/query/syncQuery` 是**同步返回**的，
用 `CgFuture` 等 54 秒拿结果，不走 WebSocket。这是给外部系统用的，不是前端主路径。

### 3.4 大文件下载：`web → console → sidecar`（HTTP 流式代理）

导出结果是**两步**，容易忽略第二步：

1. **生成**：sidecar 把结果写成文件，存放在 **sidecar 本地磁盘**。
   `dm_exec_file.file_uri` 记录为 `wsn://{workerSeqNumber}/{path}` —— 用 `wsn` 作为 URI scheme，
   host 部分就是拥有该文件的 sidecar 标识。
2. **下载**：前端 `POST /api/entry/query/downloadResult` 到 console。
   console 解析 `wsn` scheme，**通过 RSocket 向该 sidecar 分段拉取**，再写进 HTTP 响应流。

```java
// DsQueryEditorServiceImpl.fetchFileUri 分支
if (StringUtils.equalsIgnoreCase(fsName, "wsn")) {
    String wsn = fileUri.getHost();
    requireConnectedWorker(wsn);
    return this.remoteFileService.fetchFileSize(wsn, fileUri.getPath());
}
```

`RemoteFileServiceImpl` 内部全部走 `ResultSetRService`（RSocket）：
`fileSize` / `fileRead(sendDTO, path, offset, length)` / `resultPageRead` / `resultDataRead` / `convertFile`。

**含义**：
- 大文件下载是 **HTTP 请求 + RSocket 分段拉取** 的混合模式，不是纯 WebSocket。
- **导出文件留在 sidecar 所在机器上**，console 只是中转。sidecar 磁盘需要预留导出空间。
- `wsn` scheme 是这套设计的核心抽象：文件寻址 = 哪个 worker + 哪个路径。

## 4. 协议与端口清单

| 链路 | 协议 | 端口 | 发起方 | 备注 |
|---|---|---|---|---|
| web → console | HTTPS REST (JSON) | 8222 | web | 前后端同源，console 同时托管前端静态资源 |
| web → console | WebSocket / WSS | 8222 | web | 路径 `/api/entry/ws/channel` |
| console → sidecar | **RSocket over TLS**（双向流） | 8008 | **sidecar 主动出站** | console 侧是服务端；配置项 `clouddm.rsocket.console.port` |
| sidecar → console | 同上（复用同一连接） | 8008 | sidecar | 反向 RPC 走同一 socket |
| sidecar → DB | JDBC / 各库原生协议 | 按实例 | sidecar | 由数据源插件实现 |
| console → 元数据库 | JDBC | 按库 | console | MySQL 8.0+ |
| console → 钉钉/企微/飞书 | HTTPS | 443 | console | 也支持反向 callback 到 console |

**关于 sidecar 的 8223 端口**：`boot-sidecar/src/main/resources/sidecar.properties` 配置了
`server.port=8223`，但 `cgdm-sidecar` 模块内没有任何 `@RestController`。该端口在开源版本中
没有业务用途，不要把它当作可编程接口。

## 4.1 前端所有交互通道汇总（结论表）

前端只有两种传输层手段：**HTTP（含 blob 下载）** 与 **WebSocket**。二者目标都是 console。
到 sidecar 的那一段由 console 用 RSocket 完成，前端不感知。

| 前端交互类型 | 前端用什么 | 到 console 后如何继续 |
|---|---|---|
| 一般功能（用户/权限/审批/数据源配置/审计/设置） | HTTP REST | **console 内部完成**，读写元数据库，不碰 sidecar |
| 下发 SQL 查询 / 元数据浏览 | HTTP REST（下发） | console → RSocket → sidecar → DB |
| 接收查询结果、进度、异步事件 | **WebSocket**（`WS_RES_QUERY` 等） | sidecar 结果回 console，console 再推前端 |
| 大文件下载（导出结果） | HTTP（blob 响应） | console 经 RSocket 从 sidecar **分段拉取**再流给前端 |
| 驱动下载 | HTTP（blob）或经 sidecar | `DriversRService` |
| OpenAPI（外部系统调用） | HTTP REST + AK/SK | `syncQuery` 同步返回；或 `DataSourceApi` |

**一句话**：`HTTP` 与 `WebSocket` 是前端的两条腿，但 **WebSocket 到 console 就终止了**，
它不"穿过" console。console 与 sidecar 之间永远是 **RSocket**，三种通道互不复用。

## 5. sidecar 为什么必须主动出站

这是整个网络隔离设计的根源：

```properties
# boot-sidecar/src/main/resources/global_conf.properties
clouddm.console.host=127.0.0.1
clouddm.console.port=8008
```

`WorkerRSocketClient.prepareRequestMono()` 读这两个配置，由 **sidecar 发起** TLS 连接：

- 5 秒 keepalive，30 秒最大存活
- 断线每 5 秒无限重试（`Retry.fixedDelay(Integer.MAX_VALUE, 5s)`）
- `RejectedSetupException` 时直接退出进程

**含义**：console 不需要能访问 sidecar，只需要能被 sidecar 访问。网络策略上，
业务 VPC 只需放通 `出站 → console:8008`，无需任何入站规则。

## 6. 前端链路的一个细节

前端 WebSocket 用的是 `window.location.host`，即**浏览器访问的地址**。
这意味着 console 必须与前端同源部署（或由同一入口网关代理），不能把前端单独部署到另一个域名下，
否则 WebSocket 会连到错误的主机。生产部署时若前面有 SLB/Ingress，需要同时透传 HTTP 和 WebSocket 升级头。

## 7. 一句话总结

CloudDM 是"**控制面 / 数据面分离 + 内网侧出站**"的架构：
console 掌管所有状态与决策，sidecar 只管执行，二者用一条 sidecar 主动建立的 TLS 双向 RSocket 长连接通信；
前端始终只与 console 对话，结果经 console 的 WebSocket 回推。
