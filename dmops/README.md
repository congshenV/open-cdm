# dmops

CloudDM 的运维补充服务（Database Operations Service），独立部署，通过 CloudDM console 的
`/api/dmops/**` 反向代理与既有前端同源集成。

技术栈：**Python 3.11+ / Flask 3**，参考 `dms-service` 的分层与响应体约定。

## 定位

dmops 是**平级独立服务**，不是 CloudDM 的模块：

- 不直连数据库实例，一律经 CloudDM 的 `console → sidecar` 通道执行 SQL
- 不直连 sidecar，不理解 RSocket
- 不读写 CloudDM 的元数据库，只通过 HTTP OpenAPI 交互
- 与 CloudDM 版本完全解耦，各自独立升级

## 目录结构

```
dmops/
├── main.py                 应用入口，create_app()
├── app/
│   ├── config.py           配置（仅环境变量，不依赖配置中心）
│   ├── route.py            路由注册
│   ├── api/v1/ping.py      /v1/ping、/v1/hello
│   └── util/
│       ├── auth/identity.py        身份签名校验
│       └── web/
│           ├── response.py         统一响应体
│           └── request_scope.py    请求上下文（requestId / costTime）
├── requirements.in
└── .env.example
```

## 接口

| 接口 | 说明 |
|---|---|
| `GET /v1/ping` | 连通性验证，返回服务状态与时间 |
| `GET /v1/hello` | 冒烟测试，返回 `hello world` |
| `GET/POST /v1/cloud/accounts` | 阿里云账号列表 / 新建账号 |
| `GET/PUT/DELETE /v1/cloud/accounts/{id}` | 账号详情 / 修改 / 删除 |
| `GET/PUT/DELETE /v1/cloud/accounts/{id}/credential` | 账号认证配置（Secret 只写不读） |
| `GET /v1/cloud/accounts/{id}/regions` | 账号可用地域（`DescribeRegionInfos` + 已同步资源的地域） |
| `POST /v1/cloud/accounts/{id}/sync` | 同步该账号的 RDS 实例到 `ops_resource` |
| `GET /v1/instances` | 实例列表，读 `ops_resource`，需先选账号 |
| `GET /v1/instances/{instance_id}` | 实例详情，实时调用 `DescribeDBInstanceAttribute` |
| `GET/POST /v1/configs` | 配置项全量列表（可选 `scope`/`keyword` 过滤，加密项脱敏）/ 新建 |
| `GET/PUT/DELETE /v1/configs/{id}` | 配置项详情（返回明文）/ 全量修改 / 删除 |

所有 `/v1/**` 请求必须携带 console 转发的签名头，无例外。

账号/认证管理与配置管理接口暂未做管理员权限校验，已在代码中留 TODO。

## 统一响应体

兼容两种风格，任一侧前端都能直接判断成功：

```json
{
  "success": true,
  "code": 0,
  "userMessage": "操作成功",
  "message": "操作成功",
  "data": { "message": "hello world", "service": "dmops" },
  "ctx": {
    "requestId": "84dd9fdd-df79-4477-a7c7-0b34d43a10b8",
    "requestBeginTs": "2026-10-26T14:59:14.887641",
    "costTime": 0.000713,
    "atHostname": "dmops-host-01"
  }
}
```

字段语义：

| 字段 | 说明 |
|---|---|
| `success` | CloudDM 风格补充字段，布尔判真假 |
| `code` | dms-service 风格业务码，**`0` 为成功**；失败为负数（`-401`/`-404`/`-500` 等） |
| `userMessage` | 给终端用户看的提示 |
| `message` | 给开发看的细节 |
| `ctx.requestId` | 优先复用上游 `X-Request-Id`，便于全链路追踪 |
| `ctx.costTime` | 本次请求耗时（秒） |

失败示例：

```json
{
  "success": false,
  "code": -401,
  "userMessage": "身份校验失败",
  "message": "invalid identity signature",
  "data": {},
  "ctx": { "...": "..." }
}
```

HTTP 状态码保持语义正确（401/404/500），console 代理层直接透传。

## 身份校验

console 代理转发时注入：

| Header | 含义 |
|---|---|
| `X-DmOps-User` | 当前登录用户 uid |
| `X-DmOps-Signature` | `Base64(HmacSHA1(uid, identitySecret))` |
| `X-Request-Id` | 请求追踪 ID |

dmops 用同一 secret 重算比对，不匹配返回 401。签名算法与 CloudDM 的
`OpenApiSigner.signString` 字节级一致：HmacSHA1 + UTF-8 + Base64。

**不能假设"经过 console 就可信"**——console 代理是通配转发，dmops 必须自己验。

## 配置

仅从环境变量读取，见 `.env.example`：

| 变量 | 默认 | 说明 |
|---|---|---|
| `DMOPS_HOST` | `0.0.0.0` | 监听地址 |
| `DMOPS_PORT` | `8080` | 监听端口 |
| `DMOPS_DEBUG` | `false` | Flask debug |
| `DMOPS_LOG_LEVEL` | `INFO` | 日志级别 |
| `DMOPS_IDENTITY_SECRET` | 空 | **必填**，与 console 的 `dmops.proxy.identity.secret` 一致 |
| `DMOPS_IDENTITY_VERIFY_ENABLED` | `true` | 仅本地直连调试可设 false |
| `DMOPS_DB_HOST` | `127.0.0.1` | 复用 CloudDM 的 MySQL 地址 |
| `DMOPS_DB_PORT` | `13307` | MySQL 端口 |
| `DMOPS_DB_NAME` | `cdmgr` | 数据库名 |
| `DMOPS_DB_USER` | `root` | 数据库用户 |
| `DMOPS_DB_PASSWORD` | 空 | 数据库密码，部署平台注入 |
| `DMOPS_CONFIG_ENCRYPT_SECRET` | 空 | 配置管理 AES-256 加密密钥，32 字节（`openssl rand -hex 16`） |
| `DMOPS_ALIYUN_READ_TIMEOUT_MS` | `30000` | 阿里云 OpenAPI 读超时 |
| `DMOPS_ALIYUN_CONNECT_TIMEOUT_MS` | `10000` | 阿里云 OpenAPI 连接超时 |
| `DMOPS_ALIYUN_SYNC_WORKERS` | `4` | 实例同步的 Region 并发数 |
| `DMOPS_ALIYUN_MAX_INSTANCES_PER_REGION` | `5000` | 单地域单次同步的实例上限 |

生成密钥：

```bash
openssl rand -hex 32
```

同一个值同时配到 CloudDM console 的 `-Ddmops.proxy.identity.secret=...`。

## 阿里云账号与实例

- 账号、认证、实例同步依赖 DBA 预先建好的 `ops_cloud_account`、`ops_cloud_credential`、`ops_resource` 三张表；
- 认证表当前支持 `access_key`、`sts`、`ram_role_arn`、`assume_role`、`credentials_uri`、`oidc_role_arn`、`profile`、`default`；
- AK/SK 当前明文存储，代码与表注释中有 `TODO(security)`，后续改为 KMS 加密；
- 实例列表读 `ops_resource`，由账号列表的“同步”按钮触发云上拉取，不做自动刷新；
- 实例详情实时调用 `DescribeDBInstanceAttribute`，并回写资源快照。

## 配置管理

平台级键值配置中心，语义参考 dms 的 `dms_common_config`（见 `app/service/config_service.py`）：

- `config_scope` 模块：`base` / `rds` / `redis`，接口强校验；
- `config_type` 数据类型：`str` / `int` / `float` / `bool` / `str_list` / `int_list` / `json` / `json_list`，写入前按类型校验并规范化存储；
- `is_encrypt=true` 的项用 `DMOPS_CONFIG_ENCRYPT_SECRET` 做 AES-256-CBC 加密（密文 `base64(iv+cipher)`，与 dms 的 `crypt.py` 格式一致）；列表接口脱敏返回 `******`，详情接口返回明文供编辑回填；
- `(config_scope, config_key)` 唯一，重复创建返回 409；
- 列表全量返回不分页，支持可选 `scope` / `keyword`（匹配配置键与配置名）过滤。

依赖 DBA 预先建好的 `ops_config` 表：

```sql
CREATE TABLE ops_config (
  id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  config_name  VARCHAR(255) NOT NULL DEFAULT '' COMMENT '配置项展示名',
  config_scope VARCHAR(64)  NOT NULL COMMENT '模块：base/rds/redis',
  config_type  VARCHAR(32)  NOT NULL COMMENT '值类型：str/int/float/bool/str_list/int_list/json/json_list',
  config_key   VARCHAR(255) NOT NULL COMMENT '配置键',
  config_value TEXT         NOT NULL COMMENT '配置值；is_encrypt=1 时存 AES 密文(base64(iv+cipher))',
  is_encrypt   TINYINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '是否加密',
  create_user  VARCHAR(128) NOT NULL DEFAULT '' COMMENT '创建人 uid',
  description  VARCHAR(512) NOT NULL DEFAULT '' COMMENT '用途描述',
  created_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_scope_key (config_scope, config_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='dmops 配置管理';
```

## 本地运行

需要 **Python 3.11+**，macOS 自带的 `python3` 通常还是 3.9，要用 `PYTHON=` 指定解释器：

```bash
make venv PYTHON=python3.12
make install

cp .env.example .env    # 填 DMOPS_IDENTITY_SECRET、DMOPS_DB_PASSWORD
make run                # run 会先加载 .env，再启动
```

`DMOPS_IDENTITY_SECRET` 必须与 console 的 `dmops.proxy.identity.secret` **完全一致**，否则 console
转发过来的请求全部 401。本目录的 `.env`（不提交）已经按 console 的值对齐；换机器时用
`openssl rand -hex 32` 生成一个值，同时填到两边即可。

直接用 `python main.py` 启动不会加载 `.env`，需要自己 `export`，推荐统一用 `make run`。
另外 `verify_enabled=true` 而 secret 为空时 dmops 会拒绝启动并在日志首屏说明原因，不再静默地
对所有请求返回 401。

也可以用 `python3.12 -m venv .venv` 手工建环境，效果一样。已有的 `.venv` 如果版本不对，先
`rm -rf .venv` 再重建。

验证（**注意本机有 HTTP_PROXY 时必须加 `--noproxy '*'`**）：

```bash
SECRET=<同上，与 DMOPS_IDENTITY_SECRET 相同>
SIG=$(printf 'u1' | openssl dgst -sha1 -hmac "$SECRET" -binary | base64)

curl --noproxy '*' -H "X-DmOps-User: u1" -H "X-DmOps-Signature: $SIG" \
  http://127.0.0.1:8080/v1/hello
```

## 生产运行

```bash
gunicorn -w 4 -b 0.0.0.0:8080 "main:create_app()"
```

## 经 console 联调

console 侧配置：

```properties
dmops.proxy.enabled=true
dmops.proxy.base-url=http://127.0.0.1:8080
dmops.proxy.identity.secret=<与 dmops 相同>
dmops.proxy.allowed-path=/v1/
```

前端访问 `/api/dmops/v1/hello`，console 剥掉 `/api/dmops` 后转发到 `{base-url}/v1/hello`。

## 镜像打包

dmops 作为第四个服务参与 `package/` 的统一打包，镜像名为 `cgdm-dmops`，与 console、sidecar、alone
共用同一个版本号和架构标签：

```bash
cd package && ./package.sh --build --docker x86_64
# 产出 clougence/cgdm-dmops:x86_64-<version>
```

镜像内以 gunicorn 启动，配置全部通过环境变量注入，不需要 conf 卷。cluster 部署清单已经包含 dmops
服务，console 通过 `dmops.proxy.base-url=http://dm-dmops:8080` 转发 `/api/dmops/**`。

## 后续规划

详见 `../docs/dmops-design.md`：实例生命周期、建库/账号/授权、备份恢复、任务中心。
