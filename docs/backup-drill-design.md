# 备份恢复演练 · 设计文档

> 在任意 RDS 实例上人为触发：用指定备份集克隆实例，确认备份可恢复；克隆完成后对
> 源实例与克隆实例做数据对比。**分期交付**：一期只做备份恢复（发起 → 克隆 →
> Running 判成功 → 人工下线跟踪），数据对比（库级 + 用户选定表的行级校验）
> 与演练报告（md）二期。全部过程与结果落库。
>
> 关联：`docs/dmops-design.md`（dmops 总体设计）、`docs/dmops-integration-design.md`（console 代理 / OpenAPI 链路）。
> 版本：v7 · 2026-11-04 分期定稿（一期备份恢复 / 二期校验报告；v6 为 review 修订稿）

## 1. 总体流程

```
用户在实例详情 → 备份详情 Tab → 备份集列表 → 行内「备份恢复」按钮
（可用则点击 → 预览弹窗 → 编辑 → 参数检测 → 启动，见 §2.3）
        │
┌─ cloning ────────────────────────────────────────┐
│ 1. 实例详情接口回填克隆参数（§2.1 映射表）          │
│ 2. 调 CloneDBInstance 创建克隆实例（Postpaid 同规格）│
│ 3. 轮询实例状态至 Running                          │
│ 4. 在 CloudDM 注册克隆实例为数据源（拿 dsId）       │
└──────────────────────────────────────────────────┘
        │
┌─ comparing ──────────────────────────────────────┐
│ 自动对比（所有演练固定执行）：                      │
│   库名集合 + 每库表数量（只记 diff，不判终态）      │
│   每库数据量级（SUM data+index length，仅参考）     │
│ 行级校验（仅用户选定的库-表，逐表执行）：            │
│   选定表须有主键/唯一索引 + 自动更新时间列           │
│   选备份后未变更的行，主键点查克隆实例逐列对比       │
│   最多 10 次尝试，每次尝试独立落库                  │
└──────────────────────────────────────────────────┘
        │
   演练结束（不删实例）
        │
   演练详情 + 导出报告（第一期 md；html / pdf 后续按需开）
   克隆实例由运维同学在阿里云、CloudDM 中人工下线（见 §9）
```

状态机（`ops_backup_drill.status`）：

```
pending → cloning → comparing → success | partial | failed
   ↘ canceled（仅 pending 可取消；CloneDBInstance 请求发出后不可取消）
```

- **分期（2026-11-04 定）**：一期交付「发起 → 克隆 → Running → 人工下线跟踪」，
  数据源注册（§3.3）与数据校验（§4 整章）二期——一期不产生 comparing/partial 状态
- `success`：**一期 = 克隆实例 Running（§2.2）即成功**；二期 = 注册 + 对比 +
  行级校验全部通过的完整判定
- `partial`（二期出现）：行级校验未全部通过——任一选定表十次尝试全失败，
  或选定表全部被跳过（skip/warn）、零张表实际完成校验（零样本记 partial）
- AUTO 库级/表数量差异（§4.1）**只记录、不判定终态**：对比口径是
  "源当前元数据 vs 克隆（备份时点快照）"，备份后的正常业务变更（建库/删库/建表/删表）
  同样产生差异，无法与备份异常区分——报告中如实列出并标注"可能为备份后变更"
- `failed`：执行错误——一期为克隆提交失败、轮询硬错误、克隆超时；二期另有注册数据源失败、SQL 连续异常
- **无清理阶段**：演练完成后克隆实例保留，由运维人工下线
- 进程重启可从当前阶段续跑（状态落库 + 幂等推进，见 §8）

## 2. 克隆接口与参数映射

克隆接口为 **CloneDBInstance**；参数来源就是我们现有的实例详情接口
（DescribeDBInstanceAttribute，`GET /v1/instances/{id}`）+ 备份集列表（DescribeBackups）。

### 2.1 参数映射表

**A. 实例详情接口直接映射（弹窗自动回填，只读展示）**

| CloneDBInstance 参数 | 来源字段 | 说明 |
|---|---|---|
| `DBInstanceId` | `instance_id` | 必填，源实例 |
| `RegionId` | `region` | query 参数已有（与 account_id 一起传） |
| `ZoneId` | `zone_id` | 默认跟源实例可用区 |
| `DBInstanceClass` | `instance_class` | 不传 = 默认同规格（见 D） |
| `DBInstanceStorage` | `storage_gb` | 不传 = 默认同容量（5GB 递增） |
| `Category` | `category` | 文档明确克隆时保持与源一致，**无需传** |
| `InstanceNetworkType` | `network_type` | 默认与源一致，现网恒为 VPC |
| `VPCId` | `vpc_id` | 复用源实例 VPC |
| `VSwitchId` | `vswitch_id` | 复用源实例交换机 |
| `DBInstanceStorageType` | `storage_type` | **直传源值**（本地盘只能克隆为本地盘，直传不踩校验） |
| `BackupId` | 备份集 `backup_id` | 发起入口所在行 |
| `BackupType` | 备份集 `backup_type` | FullBackup / IncrementalBackup |

**B. 业务固定值（dmops 写死）**

| 参数 | 值 | 理由 |
|---|---|---|
| `PayType` | `Postpaid` | 按量付费，人工下线，绝不包年包月 |
| `DeletionProtection` | `false` | 释放保护会挡住运维人工下线 |
| `AutoPay` | `true` | 按量付费无支付动作 |
| `ClientToken` | `drill-{drill_no}` | 演练编号做幂等键，≤64 ASCII |
| `UsedTime` / `Period` | 不传 | Prepaid 专属 |
| `RestoreTable` / `TableMeta` / `DbNames` | 不传 | 演练要全量克隆，不做库表级恢复 |
| `DedicatedHostGroupId` | 不传 | 非专属集群；源详情该字段为空 |
| `PrivateIpAddress` | 不传 | 自动分配 |

**C. 前端输入项（弹窗可编辑）**

| 参数 | 交互 | 默认值 |
|---|---|---|
| `DBInstanceDescription` | 文本框 | 由「用途」联动生成（见 §2.3） |

**D. 边界决策**

1. **规格/容量/存储类型走默认**（不传）：克隆实例是静态快照，同容量必然够用，
   且规避"新实例磁盘不能小于源实例"与"规格已下线"两类校验错误；
   第一期不提供降配选项，后续要做最小规格克隆再引入规格查询
2. **`ZoneIdSlave1/2` 不传**：阿里云自行调度备可用区；不传备可用区也不触发
   "双交换机"约束，保持简单
3. **Serverless 实例克隆已支持**（v7 修订，原"第一期直接拦截"决策作废）：
   经 CloneDBInstance 官方文档核验，`PayType` 枚举含 `Serverless`
   （MySQL/PostgreSQL/SQL Server 支持，MariaDB 不支持），配合 `ServerlessConfig`
   传 RCU 配置即可。实现口径：源实例 `category` 以 serverless 开头时
   `PayType=Serverless` + `ServerlessConfig` 透传源详情返回的
   `serverless_config`（字段名映射：详情 `scale_min`/`scale_max` → 请求
   `min_capacity`/`max_capacity`；`auto_pause`/`switch_force` 仅 MySQL，同名透传）；
   非 Serverless 源实例不受影响，仍为 Postpaid。`Category` 两类都不传
   （官方文档明确克隆时保持与源一致）
4. 备份集必须 `IsAvail=1` 才允许发起（发起入口的可用性判定，见 §2.3）
5. **增量备份集未验证**：`BackupType = IncrementalBackup` 能否作为 CloneDBInstance
   的输入未验证——P1 联调时确认；若不支持，备份集列表对增量备份行禁用
   「备份恢复」按钮（tooltip "增量备份暂不支持恢复演练"）

### 2.2 克隆完成判定

CloneDBInstance 返回 `DBInstanceId` + `OrderId`；之后轮询
`DescribeDBInstanceAttribute({DBInstanceId})` 至 `DBInstanceStatus = Running`。

- **一期：Running 即演练 success**（不注册数据源、不做数据校验）
- `clone_instance_id` 在克隆提交成功后立即落库——后续无论成功失败都可追溯
  （failed 场景的孤儿实例跟踪见 §9）
- 轮询起点宽容：克隆是异步创建，请求返回后短时间内查不到实例属正常；
  "实例不存在"等硬错误连续出现（默认 10 次、间隔 30s）才判 failed，
  其余状态持续轮询至克隆超时（§8，默认 120 分钟）

### 2.3 发起入口与交互（备份集列表行内）

**入口**：备份集列表（实例详情 → 备份详情 Tab → 备份集子 Tab）每行最右侧加
「备份恢复」按钮：

- `IsAvail = 1` → 可点击
- `IsAvail ≠ 1`（不可用）→ disabled + tooltip "该备份集不可用"
- 增量备份集（若联调确认不支持克隆，§2.1-D5）→ disabled + tooltip "增量备份暂不支持恢复演练"
- 该行已有进行中的演练（未终态）→ disabled + tooltip "该备份集存在进行中的演练"

**弹窗（预览克隆实例信息）**：

```
┌─ 备份恢复 ────────────────────────────────────────┐
│ 用途      [备份恢复演练 ▾]          ← 顶部，暂时唯一选项 │
│ ─────────────────────────────────────────────── │
│ ◆ 克隆实例预览（只读，自动回填）                      │
│   源实例      rm-bp1xxxx ｜ mydb-prod              │
│   地域/可用区  cn-hangzhou / cn-hangzhou-b         │
│   规格        mysql.x8.large.2c（同源实例）          │
│   存储容量    500 GB（同源实例）                     │
│   存储类型    cloud_essd（同源实例）                 │
│   网络        源 VPC / 源交换机                      │
│   付费类型    按量付费                               │
│   所用备份集   3222768592 ｜ 2026-11-02 03:13 完成   │
│ ◆ 可编辑项                                         │
│   实例名称*   [drill-DR20261103001-备份恢复演练    ]  │
│   实例描述    [mydb-prod 备份恢复演练 3222768592    ]  │
│ ◆ 数据校验（二期交付，一期不展示）                    │
│ ─────────────────────────────────────────────── │
│            [取消]  [参数检测并启动]                   │
└──────────────────────────────────────────────────┘
```

- **用途联动命名**：用途 = 备份恢复演练时，实例名称自动生成
  `drill-{drill_no}`、描述 `{源实例名} 备份恢复演练 {backup_id}`，用户可改
  （名称规则：字母开头、2~255 字符——克隆接口对 DBInstanceDescription 的校验）；
  后续新增其他用途（如数据找回）时，按用途扩展命名模板
- **预览信息可编辑进行自定义**：第一期可编辑项为名称/描述/选定表；
  规格类字段只读展示"同源实例"（§2.1-D 的边界决策）

**参数检测（确认后、启动前，简单校验）**：

| 校验项 | 规则 | 错误呈现 | 期次 |
|---|---|---|---|
| 实例名称 | 字母/中文开头，2~255 字符，不含 http 前缀 | 字段内联标红 | 一期 |
| 备份集可用性 | `IsAvail=1` 且备份与实例归属一致 | Alert 区 | 一期 |
| 并发约束 | 全局无进行中演练、该实例无未终态演练 | Alert 区 | 一期 |
| 数据源绑定 | 源实例已绑定 CloudDM 数据源（未绑定给出引导文案） | Alert 区 | 二期（一期不查 dm_ds） |
| 选定表 | 语法 `db.table`，去重，≤ `DMOPS_DRILL_MAX_TABLES`（默认 5） | 字段内联标红 | 二期（选表器随行级校验交付） |

> Serverless 检测项已随 §2.1-D3 修订移除（克隆原生支持，不再拦截）。

检测通过 → 创建演练记录（pending）并返回 drill_no；检测失败 → 不关弹窗。

**错误呈现模式（字段内联 + Alert 混合）**：实例名称、选定表属于字段级错误，
在对应表单项下方标红展示（a-form-item validateStatus/help，或字段下红字，
P3 实现时按现有组件能力选择）；其余四项是全局条件类错误，在弹窗顶部
Alert 区域一次性列出（可多项并存），修正后重试。dmops 现有弹窗的
"Toast 弹第一条错"模式（AccountFormModal 等）不满足"8 项检测一次可见"
的要求，此弹窗引入内联模式，后续新弹窗可复用。

### 2.4 任务执行与面板

- 启动后 dmops 后台 worker 线程（§8）按 §1 状态机推进，发起请求立即返回
- **简易任务面板**：
  - 弹窗关闭后右下角 Toast "演练已启动，编号 DR20261103001"
  - 备份集列表行内按钮位置变为**状态徽标**（进行中 spinner / 成功 ✓ / 失败 ✗，
    悬浮显示当前阶段），点击可打开演练详情
  - 前端 10s 轮询（进行中时）刷新徽标；演练详情页展示分步进度（克隆 → 对比 → 完成）
    与耗时
- 任务终态后徽标定格（克隆完成 ✓ / 失败 ✗）；二期起，成功态行内再出
  「演练报告」按钮（点击下载 md 报告，§7），一期无此按钮
- **取消语义**：仅 pending 阶段（CloneDBInstance 请求尚未发出）可取消；
  一旦进入 cloning（克隆请求已提交），取消按钮失效——阿里云会把实例创建完，
  已进入 cloning 的演练要么走到终态，要么等克隆超时判 failed；
  canceled 演练不产生克隆实例，不进"待下线"清单

## 3. SQL 执行通道（不直连数据库）—— 二期

一期不涉及本章（不注册数据源、不执行任何 SQL）；**§3.2 数据源匹配、§3.3 复制式注册
随之整体后移二期**，一期的 clone 阶段编排在"克隆 Running → 落 clone_instance_id →
终态"处结束。以下为二期定稿内容，保留 v6 review 已核验的结论。

**沿用现有链路，console 零改动**：

```
dmops ──POST /api/open/query/syncQuery──► console ──RSocket──► sidecar ──► DB
```

### 3.1 dmops 侧封装

`app/adapter/clouddm/query.py` 提供唯一的 SQL 执行入口：

```python
def execute_query(ds_id: int, env_id: str, database: str, sql: str, timeout: int = 50) -> QueryResult:
    """对指定 CloudDM 数据源执行只读 SQL，返回列定义 + 行数据。

    - AK/SK 签名鉴权（与 CloudDM 专用账号绑定，签名规则同 console OpenAPI：
      AccessKeyId / SignatureMethod / SignatureNonce / Signature，HmacSHA1 + Base64）
    - 请求体（DmApiDsQueryFO）：queryString = sql，queryType = RequestQuery，
      queryForce = False，levels 如下
    - levels = [env_id, ds_id, database]   ← 裸值数字/字符串，不是 'ds:{id}' 前缀格式
      （DmDsConfigServiceImpl.parseLevels：get(0)=envId、get(1)=dsId、get(2)=MySQL 的
      Schema 层即 database；带 'ds:' 前缀会被当作 envId 解析，直接报 DS_NOT_EXIST）
    - env_id 取自 dm_ds.ds_env_id（cdm_ds_repository 查询时一并返回）
    - 硬约束：单条 SQL 必须秒级（syncQuery 服务端 54s future 超时，dmops 侧留 50s）
    - 结果行数上限保护（默认 1000 行，超出截断并标记）——console 侧不保证
      加 LIMIT（仅 SQL 重写开启时才加），截断必须由 dmops 自己实现
    """
```

> 签名实现注意：console 的 OpenApiSigner（percentEncode 排序拼接 + HmacSHA1 + Base64）
> 需要在 Python 侧按字节复刻；SK 是 dmops 侧自行保管的明文（env 配置），
> 不要求与 CloudDM 存储的加密格式一致。

对比引擎只依赖该函数，不 import 任何数据库驱动——"不直连实例"的红线保持。

### 3.2 实例 ↔ CloudDM 数据源映射（已定稿）

**核心事实**：console 的 syncQuery 执行 SQL 只需要 levels 里的 envId + dsId
（`["{envId}", "{dsId}", "{database}"]`），console 内部完成数据源→sidecar→DB 寻址。
dmops 侧的映射问题因此收敛为一个：**拿实例连接地址换 dsId**（envId 一并取出）。

**实现：直读 CloudDM 的 `dm_ds` 表（同库，已获准）**。

> 边界例外说明：dmops 与 CloudDM 同库部署。按 dmops/AGENTS.md 安全约束，
> 经用户逐次确认的场景允许直接操作 CloudDM 的表；本功能即属此类。
> 访问收在 `app/infra/cdm_ds_repository.py`，dmops 侧只做按 host 的等值 SELECT。

```python
# app/infra/cdm_ds_repository.py
def find_ds_by_host(host: str) -> dict | None:
    """按连接地址等值查 CloudDM 数据源，返回 {id, ds_env_id, host, instance_desc, status, life_cycle_state}。"""
    # SELECT id, ds_env_id, host, instance_desc, status, life_cycle_state
    # FROM dm_ds WHERE host = :host ORDER BY id LIMIT 1
    # （host 上是 127 前缀普通索引 idx_host，等值查询可用；无唯一键，多行时取 id 最小）
```

匹配与触发规则（按"实时查 + 缓存"的口径）：

1. **查询键只用 host**（RDS 连接地址是全局唯一域名，port 不参与匹配）
2. **发起演练 preflight 时实时查一次源实例**：命中 → 得到 dsId 并缓存回
   `ops_resource.cdm_ds_id`（列表页展示绑定状态用）；零命中 → 拦截，提示
   "该实例未在 CloudDM 录入数据源，请先在 CloudDM 控制台添加"
3. 缓存字段只在 preflight 命中时回写，不做独立同步任务
4. **不做手动绑定 UI**：`dm_ds` 表里没有（status 为启用）就引导去 CloudDM 加，
   加完重新发起即可（preflight 又是实时查，零延迟生效）

`ops_resource` 增列 DDL 不变：`cdm_ds_id BIGINT NULL`、`cdm_ds_synced_at DATETIME NULL`。

### 3.3 克隆实例注册为 CloudDM 数据源（已定稿：复制式写入）

克隆实例继承源实例的账号体系（access_key/secret_key 与源数据源一致），注册采用
**复制源实例的数据源记录 + 改三个字段**的方案，直接写 CloudDM 的表（AGENTS.md
例外规则，已获准）。相比调 console 造一条新配置，整行复制不会漏掉 charset、
driver 等隐藏配置项。

**幂等前置**：两张表均无唯一键（`dm_ds` 的 host / instance_id 是普通前缀索引，
`dm_ds_config_kv_4dm` 无唯一键），数据库不防重。插入前先
`SELECT id FROM dm_ds WHERE host = :clone_host`，已存在则直接复用该 dsId
（worker 重启重跑不产生重复数据源）。

**`dm_ds` 主表：复制源行后修改以下字段再 INSERT**（真实表 18 列，
含设计早期未列出的 `status_message`，整行复制策略天然覆盖）

| 字段 | 处理 |
|---|---|
| `id` | 不插（AUTO_INCREMENT），拿回新 dsId 落演练记录 |
| `gmt_create` / `gmt_modified` | NOW()，不复制源时间 |
| `host` | 克隆实例新连接地址（克隆 Running 后 DescribeDBInstanceAttribute 实时取） |
| `instance_id` | `{源instance_id}-drill`（辨识用，无唯一约束） |
| `instance_desc` | `{源desc}-drill`（用户在发起弹窗可改，即克隆实例名联动） |
| `uid` / `owner` | 复制源值 |
| 其余全部字段 | 原样复制（含 `access_key` / `secret_key` 密文——克隆继承账号，密文直接拷贝无需明文参与；`data_source_type` / `version` / `driver` / `security_type` / `ds_env_id` / `bind_cluster_id` / `status` / `life_cycle_state`…） |

**`dm_ds_config_kv_4dm`：按 `data_source_id = 源dsId` 整批复制到新 dsId**

- `config_name = 'host'` 的行：`config_value` 替换为克隆实例新地址
  （console 的 `syncConf` 证明 host 在两张表冗余，只改主表会导致两边不一致）
- 其余行按 `config_name` 原样复制。config_name 是 Java 字段名（驼峰），
  注意拼写：连接账号是 `userName`、口令是 `password`（isSecret，解密在
  console 侧完成）、驱动是 `driverVersion`（不是 `driver`）、`configVersion`
  行原值复制（console 兜底缺省为 "1"，带上源值即可）
- 复制前先检查目标 dsId 是否已有该 batch（幂等场景下查到即跳过）

**syncQuery 的数据源授权（已核验，区别于此前口径）**：console 的
`checkDsAuth` 链路会校验调用账号对数据源的授权——owner == 调用者 uid 直接放行，
其次全局授权放行，非 owner 主账号体系直接拒，兜底查授权表（真实相关的表是
`dm_auth_res`；早期文档引用的 `dm_auth_user_auth` 是零引用的死表）。
**因此 dmops 的 CloudDM 专用 AK 必须绑在具备数据源全局查询授权的账号上**
（管理员或已配全局授权的账号），这样 checkDsAuth 第二条直接放行，
克隆出的新数据源（owner 复制源值，可能属于任意主账号）无需任何授权同步。
dmops 不写任何 CloudDM 授权表。

**与源实例账号的关系（已定稿：一律复制源账号）**：源数据源配置的连接账号
（access_key）在克隆实例上同样有效——克隆继承账号体系；secret_key 是加密态
密文，直读直拷不需要明文。已核验 CryptService（AES/CBC/PKCS5 + 全局固定
key/salt + 密文内嵌 IV，不与行内其他数据绑定）：密文整行拷贝到新行可直接解密，
复制式写入在密码学上成立。**发起弹窗不再提供账号/口令输入项**，dmops 全程
不接触明文口令。后续若确需演练专用账号，前提是 CryptService 加密算法可移植到
Python 侧生成兼容密文，届时单独评估。

**演练结束后克隆实例的数据源保留**（配套人工下线流程，不自动注销）。

## 4. 数据校验设计（核心）—— 二期

一期不涉及本章（无 comparing 阶段、无 steps/diffs 数据）。以下为二期定稿内容。

SQL 只走 information_schema + 主键点查，**禁止全表扫描、禁止 COUNT(\*)**、
禁止任何锁表风险操作；每条 SQL 均须在 54s 内返回。

> 红线背景：syncQuery 的 54s 超时只杀服务端 future 等待（该链路 JDBC
> queryTimeout 未设置，超时后 DB 侧语句可能仍在执行），因此对比 SQL 必须
> 自身高效——游标扫描走主键索引、点查走主键等值，这是设计红线而非优化项。

### 4.1 自动对比：库级 + 每库表数量（每次演练固定执行）

两侧各执行一次：

```sql
SELECT table_schema                       AS db_name,
       COUNT(*)                           AS table_count,
       SUM(data_length + index_length)    AS data_bytes
FROM information_schema.tables
WHERE table_schema NOT IN ('mysql','sys','information_schema','performance_schema','__recycle_bin__')
GROUP BY table_schema
```

对比规则：

| 项 | 判定 |
|---|---|
| 库名集合 | 双向 diff，缺失/多余都记 diff |
| 每库表数量 | 不等记 diff |
| 每库 data_bytes | 近似值，只记录供报告参考，**不判定** |

**AUTO 层所有 diff 只记录、不判定终态**（§1 partial 语义）：对比口径是
"源实例当前元数据 vs 克隆实例（备份时点快照）"，备份完成后的正常业务变更
同样产生差异，与备份异常无法区分。diff 落库时在 note 标注
"可能为备份后变更"；终态结论只由行级校验（稳定行逐列对比）判定。

> 不做自动的表名集合 diff 与行数对比（对比简化决策）：表数量大时元数据扫描耗时
> 且对原实例有影响；行数用 COUNT(\*) 明确排除。表名/行级层面的核对收敛到用户选定的表。

### 4.2 行级校验（仅用户选定的库-表，逐表执行）

发起演练时用户在前端选定要校验的 `db.table`（可多选，默认最多 5 张）。
选定表须满足：

1. **有主键或唯一索引**（否则无法点查且行无稳定标识，该表记 skip 并说明原因）
2. **有自动更新时间列**：`information_schema.columns.extra` 含
   `on update CURRENT_TIMESTAMP`——该列是"行在备份后被改过"的判定依据，
   **必须确认是自动更新**；手动维护的时间列不可信，只能作为降级候选
   （标记 warning，不进判定）。无自动更新列的表记 warn，按"仅点查不校验稳定性"降级或跳过（可配）

元数据 SQL：

```sql
-- 主键列
SELECT column_name FROM information_schema.key_column_usage
WHERE table_schema = ? AND table_name = ? AND constraint_name = 'PRIMARY'
ORDER BY ordinal_position;

-- 唯一索引
SELECT index_name, COUNT(*) FROM information_schema.statistics
WHERE table_schema = ? AND table_name = ? AND non_unique = 0
GROUP BY index_name;

-- 自动更新列
SELECT column_name, data_type FROM information_schema.columns
WHERE table_schema = ? AND table_name = ?
  AND extra LIKE '%on update CURRENT_TIMESTAMP%';
```

#### 4.2.1 稳定行选择（关键）

选"备份开始前就存在、且备份开始后再没改过"的行，这样该行内容必然来自备份快照本身，
对比才有意义：

- 阈值用 `backup_start_time`（所选备份集的 BackupStartTime）而不是 EndTime：
  备份窗口内（Start ~ End 之间）被修改的行，其 update_time 仍可能 <= EndTime，
  按 End 判会把这类行误认为稳定行——该行源侧当前值与快照值必然不同，
  是确定的假 diff 来源。用 Start 做保守排除，代价只是候选行变少
  （50 批 × 100 行找一行，通常够用），换来零误判
- **时区口径（必须处理）**：BackupStartTime 是阿里云返回的 UTC 时间，而
  行内 `update_time` 列的字面量取决于实例会话时区（常见 +08），两侧口径
  不一致会差 8 小时——保守阈值会反向失效（把备份后改过的行误判为稳定行）。
  对比开始前在两侧各执行一次：

```sql
SELECT NOW(6) AS session_now, UTC_TIMESTAMP(6) AS utc_now;
```

  用 `session_now - utc_now` 得到该实例会话相对 UTC 的偏移，把
  backup_start_time 折算到与 update_time 相同的会话时区字面量后再比较；
  两实例偏移不同时按各自实例的偏移分别折算
- 在**源实例**按主键顺序游标推进（每批 100 行，最多 50 批），找到第一条满足
  `update_time <= backup_start_time(折算后)` 的行：

```sql
-- 按主键游标推进，避免依赖 update_time 索引导致全表扫描。
-- 游标扫描只取主键列和更新时间列，控制传输量；命中稳定行后再对全列做点查。
SELECT <pk_cols>, <update_col> FROM `db`.`t`
WHERE <pk_cursor_condition>          -- 上批最后一行的主键之后
ORDER BY <pk_cols> LIMIT 100;
-- 应用侧过滤 update_time <= backup_start_time
```

- 命中稳定行后，源侧同样按主键点查全列（与克隆侧点查对称）：
  `SELECT * FROM `db`.`t` WHERE <pk = ?>`
- 主键序走索引，每批 100 行代价极低，对原实例无压力
- 若 50 批内找不到稳定行（说明头部数据全是活跃更新的），该表记
  `no_stable_row`，不算失败，记 warning

#### 4.2.2 行对比与重试

克隆侧按主键点查同一行：

```sql
SELECT * FROM `db`.`t` WHERE <pk = ?>
```

逐列对比源/克隆两行：

- 类型规整：datetime/timestamp 统一格式；float/double 容差比较（相对误差 1e-9）；
  blob/binary 转 hex；NULL 相等；JSON 规范化后比较
- 差异列逐列记录（列名、源值、克隆值，默认脱敏为 hash 摘要 + 差异标记，导出报告时不落明文，可配）
- 源侧行已被删除（点查不到）→ 记 `row_deleted_in_source`，本次尝试失败，重试时重新选行

**重试机制（最多 10 次，任一次全列一致即通过）**：

| 触发重试的情况 | 说明 |
|---|---|
| 克隆实例刚就绪数据未完全可见 | 克隆 Running 后短暂窗口内点查可能异常 |
| sidecar 会话/网络抖动 | 瞬时错误 |
| 源侧选行失败 | 换行重选 |

- 每次尝试独立落库：`attempt_no`、状态（pass/fail/skipped）、耗时、失败原因、
  对比列数、差异列摘要——报告里十次尝试全部可见
- 重试间隔默认 30s（可配）；10 次全失败 → 该表记 fail，进 partial
- 判定为 pass 的数据：源行主键值、克隆行逐列一致（至少 1 个非主键列真实比对过）
- **零样本**：用户选了表但全部被跳过（无主键 skip / 无稳定行 warn 等），
  零张表实际完成校验——"有校验意图但零实际样本"，终态记 partial 而非 success，
  报告差异摘要写明"选定表均未完成校验（原因：…）"；审计口径上"没测过"不应绿灯

## 5. 数据模型

表由 DBA 预建（约定同 dmops 现有表），DDL：

```sql
-- 演练主表
-- drill_no 生成：DR + yyMMdd + 3 位当日序号（DR20261103001）。
-- 生成方式：事务内 SELECT drill_no ... WHERE drill_no LIKE 'DRyyMMdd%' ORDER BY
-- drill_no DESC LIMIT 1 FOR UPDATE 取当日最大序号 +1；罕见并发冲突由 uk_drill_no
-- 唯一键兜底（冲突时重试一次）。
CREATE TABLE ops_backup_drill (
  id                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  drill_no          VARCHAR(32)  NOT NULL COMMENT '演练编号 DR20261103001',
  account_id        INT          NOT NULL COMMENT 'dmops 账号',
  region            VARCHAR(32)  NOT NULL,
  source_instance_id VARCHAR(64) NOT NULL COMMENT '源实例',
  source_ds_id      BIGINT       NULL COMMENT '源实例 CloudDM 数据源',
  backup_id         VARCHAR(32)  NOT NULL COMMENT '使用的备份集',
  backup_start_time DATETIME     NULL,
  backup_end_time   DATETIME     NULL,
  clone_instance_id VARCHAR(64)  NULL COMMENT '克隆实例',
  clone_ds_id       BIGINT       NULL COMMENT '克隆实例 CloudDM 数据源',
  clone_params      TEXT         NULL COMMENT '克隆请求参数 JSON（含用户输入项）',
  target_tables     TEXT         NULL COMMENT '选定校验表 JSON ["db.t"]',
  status            VARCHAR(16)  NOT NULL DEFAULT 'pending'
                    COMMENT 'pending/cloning/comparing/success/partial/failed/canceled',
  error_message     TEXT         NULL,
  triggered_by      VARCHAR(64)  NOT NULL COMMENT 'X-DmOps-User',
  clone_started_at  DATETIME     NULL,
  clone_finished_at DATETIME     NULL,
  compare_started_at DATETIME    NULL,
  compare_finished_at DATETIME   NULL,
  finished_at       DATETIME     NULL,
  offline_status    TINYINT      NOT NULL DEFAULT 0
                    COMMENT '人工下线标记：0=待下线 1=已确认下线；仅 clone_instance_id 已落库的终态演练参与跟踪',
  offline_confirmed_at   DATETIME NULL,
  offline_confirmed_by   VARCHAR(64) NULL,
  created_at        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_drill_no (drill_no),
  KEY idx_source (account_id, source_instance_id, created_at),
  KEY idx_status (status)
);

-- 步骤表：自动对比一条 + 每张选定表各一张（二期才有数据，表随一期 DDL 一并预建）
-- target/差异表 target 长度：MySQL 标识符最长各 64 字符，'db.table' 极限 129，
-- 加 '#attempt' 后缀需 141+，统一 VARCHAR(192)。
CREATE TABLE ops_backup_drill_step (
  id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  drill_id    BIGINT UNSIGNED NOT NULL,
  layer       VARCHAR(8)   NOT NULL COMMENT 'AUTO=库级/表数量, ROW=行级',
  target      VARCHAR(192) NOT NULL COMMENT 'AUTO:汇总 / ROW:db.table',
  status      VARCHAR(8)   NOT NULL COMMENT 'pass/fail/warn/skip/running',
  summary     TEXT         NULL COMMENT 'JSON 汇总，如 {dbs:89,db_diff:0,table_count_diff:0}',
  detail      MEDIUMTEXT   NULL COMMENT 'JSON 明细（集合 diff、10 次尝试汇总）',
  error       TEXT         NULL,
  cost_ms     INT          NULL,
  created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_drill (drill_id, layer)
);

-- 对比明细表：库级 diff + 行级每次尝试
CREATE TABLE ops_backup_drill_diff (
  id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  drill_id    BIGINT UNSIGNED NOT NULL,
  step_id     BIGINT UNSIGNED NOT NULL,
  layer       VARCHAR(8)   NOT NULL COMMENT 'AUTO/ROW',
  item_type   VARCHAR(24)  NOT NULL COMMENT 'db_missing/db_extra/db_table_count/row_attempt',
  target      VARCHAR(192) NOT NULL COMMENT '库名 / db.table / db.table#attempt',
  attempt_no  INT          NULL COMMENT '行级尝试序号 1-10',
  status      VARCHAR(8)   NOT NULL COMMENT 'pass/fail/warn/skip',
  source_value TEXT        NULL COMMENT '源侧值（行级为脱敏摘要）',
  clone_value  TEXT        NULL COMMENT '克隆侧值（行级为脱敏摘要）',
  note        TEXT         NULL COMMENT '失败原因 / 差异说明',
  created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_drill (drill_id, layer, item_type)
);

-- ops_resource 增列（CloudDM 数据源关联；二期 preflight 回写用）。
-- 注意：cdm_ds_id 在 dmops-design.md v1 建库草稿中已存在，生产库通常已有该列，
-- 只补 cdm_ds_synced_at 与索引；执行前先确认（重复执行会报 Duplicate column）。
-- MySQL 8.0 无 ADD COLUMN IF NOT EXISTS，两段按现状择一执行：
--   SHOW COLUMNS FROM ops_resource LIKE 'cdm_ds%';
ALTER TABLE ops_resource
  ADD COLUMN cdm_ds_synced_at DATETIME NULL,
  ADD KEY idx_cdm_ds (cdm_ds_id);
```

## 6. API 设计（`/v1/`，均走 console 代理 + 签名校验）

| 方法 | 路径 | 说明 | 期次 |
|---|---|---|---|
| POST | `/v1/backup-drills` | 发起演练：instance + backup_id + 克隆参数补充输入（无选定表） | 一期 |
| GET | `/v1/backup-drills` | 列表（按实例/账号/状态过滤，分页；含"未下线"过滤） | 一期 |
| GET | `/v1/backup-drills/{id}` | 详情：主表信息 + 克隆时间线 + 待下线清单（一期）；步骤/diff 概览（二期扩展） | 一期 |
| POST | `/v1/backup-drills/{id}/cancel` | 取消（仅 pending；CloneDBInstance 发出后不可取消，见 §2.4） | 一期 |
| POST | `/v1/backup-drills/{id}/confirm-offline` | 确认下线：克隆实例与数据源已人工释放，置 offline_status=1 并记操作人 | 一期 |
| GET | `/v1/instances/{id}/drill-preflight` | 前置检查：克隆参数回填 + 4 项一期校验（数据源匹配二期加） | 一期 |
| GET | `/v1/backup-drills/{id}/steps` | 步骤明细（分 layer） | 二期 |
| GET | `/v1/backup-drills/{id}/diffs` | 对比明细（分页、按 layer 过滤） | 二期 |
| GET | `/v1/backup-drills/{id}/report` | 导出报告，`?format=md`，文件流下载 | 二期 |
| GET | `/v1/instances/{id}/drill-tables` | 选表辅助：候选表及主键/唯一索引/自动更新列情况 | 二期 |

发起请求体示例：

```json
{
  "account_id": 1,
  "region": "cn-hangzhou",
  "instance_id": "rm-xxx",
  "backup_id": "3222768592",
  "clone_input": { "dbinstance_description": "drill-DR20261103001-备份恢复演练" }
}
```

> `target_tables`（选定表）二期随行级校验加回；连接账号不传：克隆数据源整行复制源数据源（含密文口令），见 §3.3。

## 7. 报告设计 —— 二期

一期无报告（一期详情页即"恢复结果"）。md 渲染为纯字符串拼接、零依赖；
html/pdf 后续按需开。

### 7.1 报告结构（五段，按审计文档口径）

**一、背景**

固定文案，交代测试缘由与自动化程度，供审计留档：

> 本报告为数据库备份恢复演练测试记录。
>
> 按数据安全和审计要求，定期对核心业务的数据库进行恢复测试，
> 验证备份的可恢复性与数据一致性。本测试由 dmops 运维平台全自动化完成，
> 流程包括：基于指定备份集克隆恢复实例、库表信息校验、数据抽样校验。

**二、基础信息**

| 项 | 值 |
|---|---|
| 演练编号 | DR20261103001 |
| 原实例 | mydb-prod（rm-bp1xxxx）· MySQL 8.0 · cn-hangzhou |
| 克隆实例 | drill-DR20261103001-备份恢复演练（rm-bp1yyyy）· 按量付费 · 同规格 |
| 备份集 ID | 3222768592（全量备份 · 备份于 2026-11-02 03:13:54） |
| 执行时间 | 2026-11-03 10:00:00 ～ 2026-11-03 11:45:00（总耗时 105 分钟） |
| 责任人 | cong（发起人，取 X-DmOps-User） |

**三、操作时间线**

| 阶段 | 开始 | 结束 | 耗时 |
|---|---|---|---|
| 备份恢复（克隆实例创建） | 10:00:00 | 11:30:00 | 90 分钟 |
| 数据校验（库表 + 抽样） | 11:30:00 | 11:45:00 | 15 分钟 |

克隆阶段异常（超时/失败重试）在时间线行内标注；每阶段实际落库的时间戳直接渲染。

**四、数据校验结果**

先给汇总行（一眼看结论），再分两小节：

> 校验汇总：✓ 数据库校验通过（89/89 库一致） · ✓ 表数量校验通过 · ✓ 数据抽样校验通过（2/2 张表）

*4.1 库表信息校验*（自动，全量；只呈现差异，不判定终态，见 §4.1）：

| 数据库 | 原实例表数 | 克隆实例表数 | 校验结果 |
|---|---|---|---|
| app_db | 152 | 152 | ✓ 一致 |
| user_db | 37 | 37 | ✓ 一致 |
| …（仅差异库全列出并标注"可能为备份后变更"，全部一致时一句话带过） | | | |

*4.2 数据抽样校验*（选定表，逐表小节）：

每张选定表渲染：

- 表名与选定主键
- 抽样规则说明（一行："取备份完成后未再更新的数据行，按主键逐列比对"）
- 校验结果（✓ 通过 / ✗ 不一致 / ⚠ 跳过），通过的标注第几次尝试通过；
  不一致的列出差异列摘要（列名 + 源值/克隆值的脱敏摘要，不落明文）

**五、测试结论**

模板化生成，按状态取文案：

- **success**："本次备份恢复演练成功。指定备份集可正常恢复，抽样数据校验全部通过
  （N/N 张表），备份有效性验证通过。库表信息差异（如有）见第四节 4.1，
  其中部分可能为备份后的正常业务变更。"
- **partial**："本次备份恢复演练完成，但数据抽样校验未全部通过：{差异摘要——
  'table_x 十次尝试均不一致'，或零样本文案 '选定表均未完成校验（原因：…）'}。
  建议核查差异表数据或备份链路，详情见第四节 4.2。"
- **failed**："本次备份恢复演练失败：{失败原因}。备份链路可能存在异常，建议排查
  后重新演练。"

结论段之后固定追加**待办提醒**（不占章节号）：

> ⚠ 克隆实例（rm-bp1yyyy）与对应 CloudDM 数据源仍在运行并持续计费，
> 请运维人员完成下线：阿里云控制台释放实例 + CloudDM 删除数据源。

### 7.2 渲染实现

- 数据源：`ops_backup_drill` + `steps` + `diffs` 三表一次查出
- 渲染函数 `render_report_md(drill, steps, diffs) -> str`，纯字符串拼接
- 导出接口 `GET /v1/backup-drills/{id}/report?format=md`，
  `Content-Disposition: attachment; filename="drill-DR20261103001.md"`
- 前端按钮：行内「演练报告」点击直接下载 md
- 明细数据不落报告：十次尝试全记录、完整时间线（每次 API/SQL 耗时）留在演练
  详情页查看，报告保持"审计摘要"定位、控制在两页以内

## 8. 执行器与并发

- **部署形态（对照现网部署修订）**：dmops 容器 gunicorn 由 `-w 4` 改为
  **`-w 1`**（`-k gthread --threads 4` 保留）——dmops 是 IO 代理型负载
  （阿里云 API 长请求靠线程并发），单进程多线程足够；后台 worker 线程挂在
  `create_app()`（此时全进程仅一份），避免多进程重复扫描与"全局并发=1"的跨进程竞态。
  启动脚本 `package/docker/dmops.Dockerfile` CMD 同步修改
- **worker 为全新组件**（dmops 此前无任何后台任务先例）：单线程轮询循环 +
  DB 任务表，不引入工作流引擎：
  - 扫描 `status IN (pending, cloning, comparing)` 的记录，
    `SELECT ... FOR UPDATE SKIP LOCKED` 抢占
  - 每阶段完成后落库再进下一阶段；克隆轮询中每分钟落一次心跳（updated_at），
    心跳超时（10 分钟）的记录可被重新抢占——进程崩溃续跑靠这套心跳，
    不存在长时间卡死路径
- 全局并发演练数默认 **1**（可配）；同一实例存在未终态演练时禁止新发起
  （发起时校验，与心跳超时无关）
- 克隆超时默认 120 分钟（大库克隆耗时可达小时级，2026-11-04 确认够用）；
  对比阶段超时 60 分钟（二期）

**配置清单（env 前缀 `DMOPS_DRILL_`，进 `app/config.py` 新增 Drill 段）**：

| 配置 | 默认 | 说明 |
|---|---|---|
| `DMOPS_DRILL_MAX_CONCURRENCY` | 1 | 全局并发演练数 |
| `DMOPS_DRILL_MAX_TABLES` | 5 | 选定表数量上限（参数检测用） |
| `DMOPS_DRILL_CLONE_TIMEOUT_MIN` | 120 | 克隆阶段超时（分钟） |
| `DMOPS_DRILL_COMPARE_TIMEOUT_MIN` | 60 | 对比阶段超时（分钟） |
| `DMOPS_DRILL_ROW_ATTEMPTS` | 10 | 行级校验每表最大尝试次数 |
| `DMOPS_DRILL_ROW_RETRY_INTERVAL_SEC` | 30 | 行级重试间隔（秒） |
| `DMOPS_DRILL_QUERY_ROW_LIMIT` | 1000 | execute_query 结果行数截断 |
| `DMOPS_DRILL_SCAN_BATCH_ROWS` | 100 | 稳定行游标扫描批大小 |
| `DMOPS_DRILL_SCAN_MAX_BATCHES` | 50 | 稳定行游标扫描最大批数 |

## 9. 安全与成本护栏

- SQL 只读白名单：对比引擎无法执行写语句（模板固定 + queryForce=false 两层保险）
- **无凭据流转**：连接账号沿用源数据源（密文整行拷贝，dmops 侧全程不接触明文口令，
  见 §3.3）——发起弹窗不再有账号/口令输入项
- **克隆实例不做自动删除**（明确决策）：
  - 演练结束 = 演练流程结束，克隆实例保留（一期的克隆实例为阿里云侧独立资源，
    CloudDM 数据源二期注册时才产生）
  - 下线由运维同学人工执行：阿里云控制台释放实例（+ 二期起 CloudDM 删除数据源）
  - **待下线清单**：详情页固定展示克隆实例 ID（二期加数据源 ID）；列表页
    "未下线"过滤 + 逐条"确认下线"按钮（`confirm-offline` API，置
    offline_status=1 并记操作人/时间，便于跟踪遗漏）
  - **failed 演练同样跟踪**：克隆请求已发出（clone_instance_id 已落库）即进
    待下线清单——阿里云不会因演练判 failed 而停止创建，该实例可能稍后 Running
    并持续计费；只有 pending 被取消（canceled）不产生实例、不进清单
  - 按量计费实例保留期间持续计费——发起页明确提示，靠"未下线"标记防遗忘
- RAM 权限（已按 §2 克隆链路确定）：阿里云侧需 `rds:CloneDBInstance` +
  `rds:DescribeDBInstanceAttribute` + `rds:DescribeBackups`（后两个现有同步
  链路已在用，确认 AK 已含；仅 CloneDBInstance 通常需新增授权）
- **CloudDM 侧 AK 授权**（二期，随 syncQuery 一并准备）：dmops 的 CloudDM 专用 AK
  绑在具备数据源全局查询授权的账号上（§3.3 已核验的 checkDsAuth 链路决定），
  在 CloudDM 界面一次性配置
- **克隆实例网络白名单**（二期联调确认项）：克隆实例的 IP 白名单不保证继承源实例，
  一期无数据面访问不受影响；二期注册数据源前需确认 sidecar→克隆库连通，
  必要时在阿里云侧补白名单（运维人工操作，进下线前清单）
- 审计：发起/取消/确认下线（一期）；导出报告（二期）均记录操作人

## 10. 实施拆分

| 期 | 内容 | 交付 |
|---|---|---|
| 一期（备份恢复） | DDL（3 表 + offline 字段 + steps/diffs 空表一并预建）+ dmops/tests/ 测试基建 + drill repo + 克隆链路（参数组装→CloneDBInstance→轮询 Running→success/failed）+ 发起/列表/详情/取消/确认下线 API + worker + gunicorn -w 1 + 前端（入口按钮/弹窗/徽标轮询/详情页/历史列表/未下线跟踪） | 可发起备份恢复演练，克隆状态可见，下线闭环 |
| 二期（校验与报告） | 数据源匹配（dm_ds 直读）+ 复制式注册 + syncQuery 封装（签名/levels/cloudDM AK）+ 库级对比 + 行级校验引擎 + 选表器/steps/diffs 前端 + 报告导出（md） | 完整校验 + 演练报告 |

> v6 的 P1–P4 阶段划分由本分期取代：原 P3 前端按功能拆到一/二期（入口、弹窗、
> 徽标、详情骨架、列表在一期；选表器、diff 展示在二期），原 P2/P4 整体即二期。

## 11. 待补充 / 待确认

**开工前必须确认（一期硬前置）**：

1. DDL 执行方式：用户执行，或提供可连 cdmgr 库的通道
2. 阿里云 AK 授权：`rds:CloneDBInstance` 是否已含在 dmops AK
3. 联调环境：测试实例 + 备份集（一期末验证整链路，含 0-3）

**联调期待验证（不阻塞开发，一期末确认）**：

- 增量备份集（`BackupType=IncrementalBackup`）能否作为 CloneDBInstance 输入
  （§2.1-D5；不支持则前端对增量备份行禁用按钮）
- 克隆实例网络白名单是否继承源实例（§9，二期数据面前置）

已关闭的事项（v7 分期定稿，2026-11-04）：

- **分期**：一期备份恢复（发起 → 克隆 → Running → 下线跟踪）+ 前端全量；
  二期数据校验（注册 + 对比 + 行级）+ 报告。success 一期 = 克隆 Running
- 克隆接口（CloneDBInstance）与参数映射表（§2.1）；克隆超时 120 分钟确认够用
- 发起入口交互（备份集行内按钮 + 预览弹窗 + 参数检测，§2.3）；错误呈现为
  字段内联 + Alert 混合，取消仅限 pending
- 一期前端范围：砍选表器，详情页 = 基础信息 + 克隆时间线 + 待下线清单
  徽标成功态文案"克隆完成"；10s 轮询、历史列表、未下线跟踪全保留
- failed 且已提交克隆的演练进待下线清单（孤儿实例防遗忘，§9）；
  canceled 不进清单
- "未下线"跟踪落库设计：ops_backup_drill.offline_status / offline_confirmed_at /
  offline_confirmed_by + confirm-offline API（§5/§6）
- worker：gunicorn -w 1 + create_app() 后台线程，配置走 `DMOPS_DRILL_` 前缀
  （§8）；测试基建（dmops/tests/ + pytest）随一期建
- 二期（v6 review 已核验，届时直接开工）：dm_ds 直读匹配、复制式注册
  （dm_ds 18 列 + kv，驼峰 config_name，密文直拷可行）、syncQuery 签名与
  levels 三元素、checkDsAuth 与 AK 绑全局授权号、AUTO diff 不判终态、
  稳定行 BackupStartTime + 时区探测、每表 1 行、零样本 partial
- 报告格式：二期 md（html/pdf 后续按需开）
