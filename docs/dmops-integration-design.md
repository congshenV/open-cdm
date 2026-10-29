# dmops 接入方案：console 通配路径反向代理

> 决策（2026-10-22 与聪神确认）：
> - console 上加一个路由器，`/api/dmops/**` 全部转发到 dmops，路径截取后重新拼接。
> - 实时进度**暂不做 WebSocket**，前端用轮询。
> - dmops 执行 SQL **只走 console 的 HTTP OpenAPI**（`/api/open/query/syncQuery`，AK/SK 鉴权）。

## 1. 方案总览

```
前端（clouddm-web，同一份代码）
  ├─ 原有页面 ─────────────► console ──────► sidecar ─────► DB
  └─ 运维控制台（新页面）──► console /api/dmops/** ──► dmops ──► 阿里云 API
                                                        └──► console /api/open/query/syncQuery ──► sidecar ──► DB
```

关键点：**前端只与 console 通信**（同源），console 把 `/api/dmops/**` 原样转发给 dmops。
这样同时解决三件事：跨域、二次登录、会话复用。dmops 可以独立部署、独立迭代，甚至独立技术栈。

## 2. 转发规则的路径拼接

建议规则（约定清晰、不易出错）：

| 前端请求 | 转发到 dmops |
|---|---|
| `/api/dmops/instance/create` | `{dmopsBase}/api/instance/create` |
| `/api/dmops/backup/list?dsId=1` | `{dmopsBase}/api/backup/list?dsId=1` |

即：**去掉 `/api/dmops` 前缀，保留其余路径与 query string，前面补 dmops 自己的 base path。**

不建议"完全原样透传"（连 `/api/dmops` 一起发），因为那样 dmops 的接口就被 console 的路径前缀绑定了，
将来想绕过 console 直连 dmops 调试时会不一致。加一层 base path 更干净。

## 3. console 侧实现

### 3.1 技术选择

已核实的事实：

| 项 | 结论 | 依据 |
|---|---|---|
| Spring Boot 版本 | 4.0.6 / Spring 7.0.7 | `backend/gradle.properties` |
| HTTP 客户端 | **okhttp 4.12.0 直接可用** | `cgdm-share-libs/build.gradle` 以 `api` 导出，console 依赖它 |
| 拦截器是否拦 `/api/dmops/**` | 会，且是全局注册 | `WebConfigurer.addInterceptors()` 无 path 限制 |
| 鉴权如何放行 | 代理方法上标 `@RequestAuth` 即可 | `JwtInterceptor` 读 `HandlerMethod` 的注解 → `JwtManager.preHandle` |
| 前端开发代理 | `/api` 已开 `ws: true` | `frontend/vue.config.js` |

**结论：不需要新增任何依赖，用已有的 okhttp 写一个通配转发器即可。**

### 3.2 控制器骨架

```java
@RestController
public class DmOpsProxyController {

    private static final String PREFIX = "/api/dmops";

    @Resource
    private DmOpsProxyConfig config;   // dmopsBaseUrl / 超时 / 是否启用

    // 通配：/api/dmops/**，任意方法
    @RequestAuth(value = "", strategy = RequestAuth.AuthStrategy.RefAnyOnes)
    @RequestMapping(value = PREFIX + "/**")
    public void proxy(HttpServletRequest request, HttpServletResponse response) throws IOException {
        if (!config.isEnabled()) {
            response.sendError(503, "dmops is not configured.");
            return;
        }

        String target = buildTargetUrl(request);
        Request okRequest = buildOkRequest(request, target);

        try (Response okResponse = config.getClient().newCall(okRequest).execute()) {
            response.setStatus(okResponse.code());
            copyHeaders(okResponse, response);
            copyBody(okResponse, response);
        }
    }

    private String buildTargetUrl(HttpServletRequest request) {
        String uri = request.getRequestURI();            // /api/dmops/instance/create
        String rest = uri.substring(PREFIX.length());    // /instance/create
        String query = request.getQueryString();
        String base = config.getBaseUrl();               // http://dmops:8080/api
        return base + rest + (query == null ? "" : "?" + query);
    }
}
```

### 3.3 必须处理的细节（这部分不做会出事）

1. **JWT 透传而不是重新签发**。转发时把原始 JWT（cookie 或 header）带给 dmops，让 dmops 用
   console 的公钥验签，从而识别"是哪个用户"。否则 dmops 只能看到 console 这个"系统身份"，
   审计日志无法区分人。
   若不想让 dmops 验 JWT，退而求其次：console 校验后，在 header 里塞
   `X-DmOps-User: {uid}` + `X-DmOps-Signature: HMAC(uid, sharedSecret)`，dmops 只验这个。
   **第二种更简单，推荐第一期用**。

2. **不要在代理层做业务判断**。只做"路径改写 + 透传"，任何业务逻辑写进 console 都会重新耦合。

3. **超时要比 dmops 长**。建实例、备份是分钟级。okhttp 默认 readTimeout 必须调大
   （建议 5 分钟），或对这类请求直接返回"已受理 + taskId"，由前端轮询——
   **后者更好，推荐**：代理层超时保持 60 秒，长任务走异步任务模型。

4. **响应流式透传**。文件下载/大响应不要先读进内存再写，用
   `okResponse.body().byteStream()` → `IOUtils.copy` 直接流式输出。

5. **不要转发 hop-by-hop header**。`Connection`、`Transfer-Encoding`、`Host`、`Content-Length`
   等要剔除，否则响应会错乱。

6. **错误要好排查**。dmops 不可达时返回明确错误（`503 dmops unreachable`），
   并打日志带 target url，不要吞异常返回空 200。

### 3.4 配置项

```properties
dmops.proxy.enabled=true
# 只到 dmops 的 scheme://host:port，不要带 /api。
# 转发时 targetUrl = base-url + restPath，restPath 是 /api/dmops 之后的部分，
# 例如 /api/dmops/v1/hello → http://dmops:8080/v1/hello
dmops.proxy.base-url=http://dmops:8080
dmops.proxy.allowed-path=/v1/
dmops.proxy.connect-timeout-ms=3000
dmops.proxy.read-timeout-ms=60000
# 与 dmops 共享的签名密钥，必填；留空则代理不启动
dmops.proxy.identity.secret=<随机串>
```

`identity.secret` 用于给转发请求签名，dmops 侧校验签名并取出真实 uid，
因此 dmops **不能**信任请求里自带的身份头，只能信任签名结果。

这三项写在哪里：

| 场景 | 文件 |
|---|---|
| 部署包运行 | `<APP_HOME>/conf/console.properties`（源码 `package/pkg/console/console.properties`，打包时落到 `cgdm/console/conf/`） |
| IDEA 直跑 | `backend/clouddm-boot/boot-console/src/main/resources/console.properties` |
| 想覆盖配置文件 | `package/pkg/bin/setenv.sh` 的 `JAVA_OPTS` 里加 `-Ddmops.proxy.xxx=...`（系统属性优先级高于配置文件） |

`DmConsoleLauncher` 里 `System.setProperty("spring.config.name","default_console,console")`，
`pkg/console/app.conf` 又把 `${app.home}/conf/` 挂进了 plexus classworld 的类路径，
所以 `conf/console.properties` 会被当作 `classpath:/console.properties` 读到；
`boot-console/build.gradle` 的 `jar { exclude 'console.properties' }` 说明这份文件本来就是**外置**的，
改完重启 console 即可，不用重新打 jar。`default_console.properties` 才是打进 jar 的默认值模板。


## 4. 前端侧实现

### 4.1 三种顶层区域与切换入口

CloudDM 前端在 `Home`（`src/views/home/index.vue`）一层做**区域分流**，三个区域互相独立，
不共用侧边栏：

| 区域 | 路由 | 布局 | 头部 |
|---|---|---|---|
| 控制台 | 除 `/sql`、`/dmops` 外的业务路由 | `app-layout`（左侧边栏 + 卡片内容区） | `AppContentHeader` |
| 数据查询 | `/sql` | `sql-layout`（无侧边栏） | `sql-compact-header` |
| 运维控制台 | `/dmops` | `dmops-layout`（无侧边栏） | `sql-compact-header`（静态品牌，不可点） |

切换入口是统一组件 `AppSwitchNav`（`src/components/layout/AppSwitchNav.vue`），
渲染为右上角的三段式切换：**控制台 / 数据查询 / 运维控制台**。
三处挂载位置：

- `AppContentHeader` 的 `__right`（控制台区域）
- `sql-layout` 头的 `__actions`（数据查询区域）
- `dmops-layout` 头的 `__actions`（运维控制台区域）

`AppSwitchNav` 里只有两处与主站相关的逻辑，其余完全独立：

- "控制台"按 `resolveWorkbenchRoute()` 回到**上次访问的工作台页面**，避免丢失上下文；
- "数据查询"仅在 `myCatLog` 含 `CAT_DM_CONSOLE` 时出现，与既有 `showSqlLink` 判断保持一致；
- "运维控制台"登录即可见（不对应 CloudDM 权限目录）。

运维控制台页面本体 `src/views/dmops/` 只渲染 dmops 自己的界面，不接侧边栏、页签、面包屑，
后续整体替换成 dmops 自己的前端时，布局层无需改动。

### 4.2 请求封装

新页面统一用一个独立的 axios 实例，baseURL 设为 `/api/dmops`：

```js
// src/services/http/dmops.js
const dmops = axios.create({ baseURL: '/api/dmops', timeout: 60000 });
```

这样所有请求天然带 `/api/dmops` 前缀，由 console 转发。前端代码里看不到 dmops 的真实地址，
将来 dmops 换域名/换端口完全不影响前端。

### 4.3 侵入度评估

| 改动点 | 文件 | 侵入度 |
|---|---|---|
| 区域分流 + 独立布局 | `views/home/index.vue` | 1 处，加两个计算属性与一个分支 |
| 切换组件 | `components/layout/AppSwitchNav.vue` | 全新文件 |
| 控制台头部挂载 | `components/layout/AppContentHeader.vue` | 1 行 |
| 路由 | `src/router/index.js` | 1 处，几行 |
| 新页面 | `src/views/dmops/**` | 全新目录，零冲突 |
| 请求封装 | `src/services/http/dmops.js` | 全新文件 |
| 样式 | `styles/app-shell.less` | 追加 `dmops-layout` 与切换栏两段 |

后端改动仅 **1 个 controller + 1 个 config 类**（约 150 行），放在独立包 `...controller.dmops` 下，
与上游文件不重叠，merge 冲突概率极低。

## 5. dmops 执行 SQL 的路径

dmops 需要操作数据库实例时，**不直连实例、不直连 sidecar**，而是调 console 的 OpenAPI：

```
dmops ──HTTP POST /api/open/query/syncQuery──► console ──RSocket──► sidecar ──► DB
```

- 鉴权：AK/SK 签名（`AccessKeyId` / `Signature` / `SignatureMethod` / `SignatureNonce`，可放 header）。
  建议给 dmops 单独申请一对 AK/SK，绑定专用子账号，权限收敛。
- 入参：`levels`（数据源层级路径）、`queryType`、`queryString`、`queryForce`
- 限制：**54 秒超时**（`QueryApi.DEFAULT_QUERY_TIMEOUT_SEC = 54`）
- 因此 dmops 侧的 DDL 必须是秒级的：建库、建账号、授权 —— 都满足。
  大表变更不走这条路。

## 6. 相比"逐接口代理"的优势

| 维度 | 通配反向代理 | 逐接口代理 |
|---|---|---|
| console 改动量 | 1 个 controller，一次写完 | 每个 dmops 接口都要写一个方法 |
| dmops 新增接口 | **console 零改动** | 必须改 console 并重新发布 |
| 类型安全 | 无（透传 JSON） | 有 |
| 耦合度 | 极低 | 随接口数量线性上升 |
| 调试 | 稍难（需要看转发日志） | 直接 |

**结论**：你的选择是对的。只有在"需要对某个接口做精细鉴权或数据改写"时才考虑逐接口代理，
那属于例外而非默认。

## 7. 风险

1. **代理成为唯一入口，会是单点**。console 挂了，运维控制台也不可用。这是同源网关的固有代价，
   可接受（因为主站同样依赖 console）。
2. **通配转发可能放大攻击面**。`/api/dmops/**` 会转发任意路径到 dmops。必须：
   - 强制 `@RequestAuth` 鉴权，匿名不可访问；
   - dmops 侧仍需自己做鉴权与参数校验，**不能假设"经过 console 就是可信的"**；
   - 建议在代理层加路径白名单前缀（如只允许 `/api/dmops/v1/**`），避免误转发。
3. **不要用代理转发敏感凭据**。dmops 需要的阿里云 AK/SK 存在 dmops 自己那边，绝不经过 console。
4. **日志要能串起来**。代理层生成 `X-Request-Id` 并同时带给 dmops，出问题能一条链路查完。

## 8. 落地顺序

1. **console**：新增 `DmOpsProxyController` + `DmOpsProxyConfig`，配置化启用开关（默认关闭）。
2. **验证**：用 `curl` 打 `/api/dmops/ping`，确认转发、鉴权、错误码都正确。
3. **dmops**：提供 `/api/ping` 与最小接口集（建实例、建库）。
4. **前端**：新增菜单、路由、`views/dmops/` 目录、独立 axios 实例。
5. **联调**：前端 → console 代理 → dmops → console OpenAPI → sidecar，跑通一条完整链路。
