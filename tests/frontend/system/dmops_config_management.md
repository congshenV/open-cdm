# dmops 配置管理

## Purpose

验证运维控制台的配置管理页（`/dmops/config`）可以完成平台级键值配置的增删改查；重点防止
加密配置脱敏泄漏、类型校验失效、`(scope, key)` 唯一约束失效这三类回归。

## Scope

- 页面与路由：`/dmops/config`（运维控制台 → 配置管理）
- 入口：左侧导航「配置管理」菜单项（`frontend/src/views/dmops/index.vue` 的 `navItems`）
- 关联接口与状态：`/api/dmops/v1/configs`（列表/新建）、`/api/dmops/v1/configs/{id}`
  （详情/修改/删除）；列表全量加载无分页；加密项列表返回 `******`，详情返回明文
- 关联源码：
    - 前端：`frontend/src/views/dmops/ConfigManage.vue`、
      `frontend/src/views/dmops/components/ConfigFormModal.vue`、
      `frontend/src/services/http/dmops.js`
    - 后端：`dmops/app/api/v1/config_manage.py`、`dmops/app/service/config_service.py`、
      `dmops/app/infra/config_repository.py`
- 不覆盖：console 的 `/api/dmops/**` 代理转发本身、签名校验、dmops 服务的部署

## Preconditions

- 浏览器：使用 [@Browser](plugin://browser@openai-bundled) 内置浏览器，并确认其中已登录测试账号。
- 服务地址与依赖服务：console（已启用 `dmops.proxy.enabled=true`）、dmops 服务、
  `ops_config` 表已由 DBA 建好、`DMOPS_CONFIG_ENCRYPT_SECRET` 已配置（32 字节）
- 所需账号角色与权限：能访问运维控制台的登录账号（当前接口未做管理员白名单，登录即可）
- 稳定初始状态：配置列表页可正常打开
- 允许的数据写入范围：`ops_config` 表中 `codex_config_` 前缀的测试配置项

## Test Data

| 编号 | 数据说明 | 构造方式 | 唯一标识 | 清理方式 |
|-----|------|------|---------------------|------|
| D01 | 标准 str 配置（不加密） | 新建：scope=base、类型=str、key=`codex_config_smoke_<uid>` | `codex_config_smoke_<uid>` | 页面删除 |
| D02 | 加密配置 | 新建：scope=rds、类型=str、勾选加密、key=`codex_config_enc_<uid>` | `codex_config_enc_<uid>` | 页面删除 |
| D03 | 各类型合法值样本 | int/float/bool/json/json_list 各建一条，key=`codex_config_<type>_<uid>` | `codex_config_<type>_<uid>` | 页面删除 |

## Suites

### CONFIG-SMOKE-01 列表入口与主要控件

- 风险/目的：P0，页面可达、表格与工具栏可见
- 初始路由与状态：已登录，进入 `/dmops/config`
- 测试数据：无需写入
- @Browser 操作：
    1. 打开 `/dmops/config`
- 预期结果：
    1. 页面标题为「配置管理」，可见关键词输入框、模块筛选（全部模块 + base/rds/redis）、
       查询按钮、新建配置项按钮
    2. 表格列包含：配置名、模块、配置键、数据类型、配置值、是否加密、创建人、描述、更新时间、操作
    3. 无相关 Console 报错

### CONFIG-MAIN-02 新建配置项（不加密）

- 风险/目的：P0，标准写入流程
- 初始路由与状态：`/dmops/config`
- 测试数据：D01
- @Browser 操作：
    1. 点击「新建配置项」，弹窗打开
    2. 依次选择模块 base、填写配置名、类型 str、配置键、配置值，保存
- 预期结果：
    1. 提示操作成功、弹窗关闭、列表自动刷新，新行出现在表格中
    2. 值按明文展示；描述为空

### CONFIG-MAIN-03 新建加密配置与列表脱敏

- 风险/目的：P0，加密项脱敏展示
- 初始路由与状态：`/dmops/config`
- 测试数据：D02
- @Browser 操作：
    1. 新建配置项：模块 rds、类型 str、勾选「是否加密」、填写值，保存
    2. 观察列表中该行
- 预期结果：
    1. 列表中该行「配置值」显示 `******`，不出现明文
    2. 「是否加密」列显示「是」

### CONFIG-MAIN-04 编辑回填明文

- 风险/目的：P0，编辑加密项时详情接口返回明文回填表单
- 初始路由与状态：`/dmops/config`，存在 D02
- 测试数据：D02
- @Browser 操作：
    1. 点击 D02 行的「编辑」
    2. 等弹窗表单回填完成
- 预期结果：
    1. 表单各字段回填正确；配置值处显示原明文（不是 `******`）
    2. 配置键输入框处于禁用状态（编辑不允许改 key）
    3. 修改描述后保存，列表刷新成功

### CONFIG-BOUNDARY-05 类型校验

- 风险/目的：P1，非法值被后端拒绝
- 初始路由与状态：`/dmops/config`
- 测试数据：D03（合法样本各建一条），另尝试非法值
- @Browser 操作：
    1. 新建：类型 int、值 `abc`，保存 → 应报「配置值不符合类型 int 的格式」
    2. 新建：类型 json、值 `[1,2]`（数组，json 类型不允许），保存 → 应被拒绝
    3. 新建：类型 int_list、值 `["a"]`，保存 → 应被拒绝
    4. 合法样本：int=`42`、float=`3.14`、bool=`yes`、json=`{"a":1}`、json_list=`[1,{"b":2}]` 逐条保存
- 预期结果：
    1. 非法值均保存失败且给出可读错误提示，弹窗不关闭
    2. 合法样本全部保存成功

### CONFIG-REPEAT-06 重复 key 冲突

- 风险/目的：P1，`(scope, key)` 唯一约束
- 初始路由与状态：`/dmops/config`，存在 D01（base 模块）
- 测试数据：复用 D01
- @Browser 操作：
    1. 再新建一条：模块 base、配置键与 D01 相同，保存
- 预期结果：
    1. 提示「该模块下配置键已存在」（409），不产生重复行
    2. 换成模块 redis 用相同 key 保存 → 成功（不同 scope 不冲突）

### CONFIG-FILTER-07 筛选与搜索

- 风险/目的：P1，工具栏过滤
- 初始路由与状态：`/dmops/config`，存在 D01（base）与 D02（rds）
- 测试数据：复用 D01/D02
- @Browser 操作：
    1. 模块筛选选 base，点击查询
    2. 恢复「全部模块」，关键词输入 `codex_config_enc`，点击查询
- 预期结果：
    1. 步骤 1 后仅显示 base 模块的行
    2. 步骤 2 后仅显示 key 或配置名匹配的行

### CONFIG-LIFECYCLE-08 删除与刷新

- 风险/目的：P1，删除确认与列表刷新
- 初始路由与状态：`/dmops/config`，存在 D03
- 测试数据：D03
- @Browser 操作：
    1. 点击某行「删除」，确认弹层出现后确认
    2. 刷新浏览器页面
- 预期结果：
    1. 提示操作成功，行消失
    2. 刷新后列表与服务端一致，已删项不再出现

## Cleanup

1. 删除所有 `codex_config_` 前缀的测试配置项，确认列表不再包含它们。
