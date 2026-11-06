# dmops 备份恢复演练（一期）

## Purpose

验证运维控制台的备份恢复演练链路：从备份集列表行内发起演练、克隆状态徽标轮询、
演练详情（克隆时间线 + 待下线清单 + 确认下线）、演练历史列表过滤。重点防止：
克隆重复提交（并发绕过）、不可用备份集可发起、pending 之外的演练可取消、
下线确认未校验终态与克隆实例存在性、轮询未清理（切页后仍轮询）这几类回归。

## Scope

- 页面与路由：
  - 实例详情备份 Tab `/dmops/instance/:instanceId`（备份集子 Tab 行内入口与状态徽标）
  - 演练列表 `/dmops/drill`、演练详情 `/dmops/drill/:drillId`
- 入口：实例详情 → 备份详情 → 备份集子 Tab → 行内「备份恢复」按钮；
  侧边栏「演练列表」菜单项
- 关联接口与状态：`POST /api/dmops/v1/backup-drills`（发起）、
  `GET /v1/backup-drills`（列表，`offline=1` 只看待下线）、
  `GET /v1/backup-drills/{id}`（详情）、`POST /v1/backup-drills/{id}/cancel`
  （仅 pending）、`POST /v1/backup-drills/{id}/confirm-offline`、
  `GET /v1/instances/{id}/drill-preflight`（参数检测 + 克隆参数预览）
- 状态机（一期）：pending → cloning → success | failed；canceled 仅 pending 可达；
  comparing/partial 二期引入
- 关联源码：
    - 前端：`frontend/src/views/dmops/InstanceDetail.vue`、`DrillList.vue`、
      `DrillDetail.vue`、`components/BackupRestoreModal.vue`、`utils/drill.js`、
      `services/http/dmops.js`
    - 后端：`dmops/app/api/v1/backup_drill.py`、`app/service/backup_drill_service.py`、
      `app/infra/backup_drill_repository.py`、`app/worker/backup_drill_worker.py`
- 不覆盖：阿里云 CloneDBInstance 真实行为（联调用真实测试实例单独验证）、
  数据校验与报告（二期）、console 代理与签名本身

## Preconditions

- 浏览器：使用 [@Browser](plugin://browser@openai-bundled) 内置浏览器，确认已登录测试账号
- 服务地址与依赖：console（dmops 代理开启）、dmops 服务、
  `ops_backup_drill` / `ops_backup_drill_step` / `ops_backup_drill_diff` 表已建、
  dmops AK 已含 `rds:CloneDBInstance`
- 所需账号角色与权限：能访问运维控制台的登录账号；一个可发起演练的测试 RDS 实例
  （非 Serverless）与至少一个 `IsAvail=1` 的备份集
- 稳定初始状态：该测试实例无进行中的演练（如有，等待终态或用另一实例）
- 允许的数据写入范围：`ops_backup_drill` 表中该测试实例的演练记录；
  阿里云侧会产生一个按量计费克隆实例（联调后释放）
- 成本护栏：克隆实例按量计费，每个演练结束后必须确认下线并释放实例

## Test Data

| 编号 | 数据说明 | 构造方式 | 唯一标识 | 清理方式 |
|-----|------|------|---------|------|
| D01 | 可用备份集 | 现网测试实例的 `IsAvail=1` 备份集（列表任选） | backup_id | 无需清理 |
| D02 | 不可用备份集 | `IsAvail≠1` 的备份集（若无，标记该场景 SKIP） | backup_id | 无需清理 |
| D03 | Serverless 实例 | 一个 category 以 Serverless 开头的实例（若无，SKIP） | instance_id | 无需清理 |
| D04 | 并发冲突 | 已有进行中演练的实例上再次发起 | drill_no | 等终态后确认下线 |

## Suites

### DRILL-SMOKE-01 演练列表入口

- 风险/目的：P0，导航与页面可达
- 初始路由与状态：已登录
- @Browser 操作：
    1. 打开 `/dmops/drill`
- 预期结果：
    1. 左侧导航「运维控制台」上组出现「演练列表」菜单项
    2. 页面可见账号/实例/状态筛选、「只看待下线」勾选、查询按钮与表格
    3. 无 Console 报错

### DRILL-SMOKE-02 备份集行内入口按钮状态

- 风险/目的：P0，入口可见性与禁用规则
- 初始路由与状态：`/dmops/instance/:instanceId` → 备份详情 Tab → 备份集子 Tab
- 测试数据：D01、D02
- @Browser 操作：
    1. 观察备份集各行最后一列
- 预期结果：
    1. 新增「操作」列，`IsAvail=1` 的行显示可点击的「备份恢复」按钮
    2. `IsAvail≠1` 的行按钮置灰，悬浮提示「该备份集不可用」

### DRILL-MAIN-03 发起弹窗与 preflight 回填

- 风险/目的：P0，弹窗交互与参数检测
- 初始路由与状态：同 SMOKE-02
- 测试数据：D01
- @Browser 操作：
    1. 点击「备份恢复」，等待弹窗加载
    2. 检查克隆实例预览区与实例描述输入框
- 预期结果：
    1. 用途下拉锁定为「备份恢复演练」
    2. 预览区显示源实例、地域/可用区、规格、存储、付费类型（按量付费）、所用备份集
    3. 实例描述 placeholder 为「{源实例名} 备份恢复演练 {backup_id}」
    4. 底部有按量计费警示条；「启动演练」按钮可点击

### DRILL-MAIN-04 发起成功与状态徽标轮询

- 风险/目的：P0，发起 → 徽标推进主流程
- 初始路由与状态：同上弹窗打开
- 测试数据：D01
- @Browser 操作：
    1. 点击「启动演练」
    2. 回到备份集列表观察该行；等待超过 10s 观察徽标
- 预期结果：
    1. Toast「演练已启动，编号 DR…」；弹窗关闭
    2. 「备份恢复」按钮位置变为状态徽标（克隆中，spinner 图标）
    3. 约 10s 后徽标自动刷新（Network 有备份集演练列表请求，无需手动刷新）
    4. 点击徽标跳转 `/dmops/drill/:id` 详情页，面包屑返回项为「返回实例详情」

### DRILL-MAIN-05 演练详情与时间线

- 风险/目的：P0，详情页信息完整性
- 初始路由与状态：`/dmops/drill/:id`（上一场景跳转）
- @Browser 操作：
    1. 观察详情页各区块
- 预期结果：
    1. 演练信息区：编号、状态 tag、发起人、源实例、地域、所用备份集、发起时间
    2. 克隆时间线三步：发起演练（已完成）→ 克隆提交（克隆提交后有完成时间）→
       克隆完成/失败（进行中显示「克隆中」）
    3. 未终态时页面每 10s 自动刷新（时间戳或状态变化）

### DRILL-MAIN-06 终态后的待下线清单与确认

- 风险/目的：P0，下线闭环
- 初始路由与状态：`/dmops/drill/:id`，演练已到 success 或 failed
  （克隆请求已发出的 failed 场景同样适用）
- @Browser 操作：
    1. 观察待下线清单区
    2. 先在阿里云控制台释放克隆实例（人工），再点击「确认下线」并确认
- 预期结果：
    1. 清单展示克隆实例 ID、下线状态「待下线」、按量计费警示
    2. 确认后状态变为「已确认下线」，操作列不再显示按钮
    3. 再次确认（如通过列表入口）时后端拒绝（重复确认提示）

### DRILL-MAIN-07 演练历史列表与过滤

- 风险/目的：P1，列表检索与下线跟踪
- 初始路由与状态：`/dmops/drill`
- @Browser 操作：
    1. 用实例 ID 筛选；勾选「只看待下线」
    2. 点击演练编号跳详情；返回后列表状态保持
- 预期结果：
    1. 表格列含编号（链接）、源实例、地域、备份 ID、状态、克隆实例、发起时间、
       下线状态、操作
    2. 「只看待下线」过滤后仅剩未确认下线且已产生克隆实例的记录
    3. 行内「确认下线」可用，确认后行消失（勾选过滤态下）

### DRILL-BOUND-08 描述校验（字段内联）

- 风险/目的：P1，字段级错误内联展示
- 初始路由与状态：发起弹窗打开
- @Browser 操作：
    1. 实例描述输入 `h` （1 字符）点击启动
    2. 清空后输入 `http://x` 点击启动
- 预期结果：
    1. 分别在描述输入框下方标红「描述最少 2 个字符」/「描述不能以 http 开头」，
       弹窗不关闭、不出现 Toast 弹错

### DRILL-BOUND-09 全局检测失败（Alert 区）

- 风险/目的：P1，全局条件类错误集中展示
- 初始路由与状态：测试数据 D03（Serverless）或 D04（并发占用）
- @Browser 操作：
    1. 打开发起弹窗观察 Alert 区
- 预期结果：
    1. 顶部 Alert 列出失败项（如「暂不支持 Serverless 实例」或
       「已存在进行中的演练…」）
    2. 「启动演练」按钮保持禁用

### DRILL-REPEAT-10 重复发起与取消边界

- 风险/目的：P0，并发约束前端表现（后端有二次校验，前端验证不绕过）
- 初始路由与状态：实例已有进行中的演练（D04）
- @Browser 操作：
    1. 重复打开发起弹窗；尝试双击「启动演练」
- 预期结果：
    1. 弹窗被 Alert 拦截（并发项失败）或提交后收到后端 409 错误提示，
       不产生第二条演练
    2. 刷新列表确认该实例仍只有一条进行中演练

### DRILL-FAIL-11 接口异常展示

- 风险/目的：P1，接口失败的兜底
- 初始路由与状态：任意（可由后端停服模拟）
- @Browser 操作：
    1. dmops 停止后打开 `/dmops/drill`；打开发起弹窗
- 预期结果：
    1. 列表页 Toast 提示接口失败，页面不白屏
    2. 弹窗 preflight 失败时显示错误提示，「启动演练」保持禁用

### DRILL-LIFE-12 轮询生命周期清理

- 风险/目的：P1，切页停轮询防泄漏
- 初始路由与状态：演练进行中，停留在 InstanceDetail 备份 Tab（徽标轮询中）
- @Browser 操作：
    1. 切到实例详情 Tab，再导航离开实例页面
    2. 回到实例页备份 Tab
- 预期结果：
    1. 切走后 Network 面板不再出现演练列表周期请求
    2. 回来后徽标恢复且轮询重新启动（存在进行中演练时）

## Cleanup

1. 所有演练到达终态后：阿里云控制台释放各克隆实例（真实资源！）
2. 页面上逐条「确认下线」
3. 测试产生的 `ops_backup_drill` 记录可保留（历史列表可过滤），无需删库

## Skip Conditions

- 无 `IsAvail≠1` 备份集（D02）：BOUNDS 中该断言跳过，改为后端单测覆盖说明
- 无 Serverless 实例（D03）：BOUND-09 用并发场景替代验证 Alert 展示
- 不便执行真实克隆的成本敏感环境：SMOKE-02/BOUND/REPEAT 可正常执行；
  MAIN-04~07 需要 CloneDBInstance 真实调用，标记 SKIP 并说明覆盖缺口
  （后端 mock 单测已覆盖状态推进，真实克隆行为留给联调）
