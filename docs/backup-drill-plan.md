# 备份恢复演练 · 执行计划（一期：备份恢复）

> 依据 `docs/backup-drill-design.md`（v7 分期定稿）制定。**一期只做备份恢复**：
> 发起 → 克隆 → Running 判成功 → 人工下线跟踪。数据校验与报告二期
> （对照 v6 review 已核验结论直接开工）。
> 按依赖顺序分三个阶段，每阶段结束有明确校验点。DDL 由 DBA 预建（用户执行），
> 其余由我完成。

## 前置（用户操作，开工前一次）

| # | 事项 | 说明 |
|---|---|---|
| 0-1 | 执行 DDL | 设计文档 §5：新表 `ops_backup_drill`（含 offline 三字段）/ `ops_backup_drill_step` / `ops_backup_drill_diff`（后两张二期才有数据，一并预建，避免二次 DDL）。**需要你把 DDL 在 cdmgr 库执行**（或提供可连库的环境） |
| 0-2 | 阿里云 AK 授权 | 确认 `rds:CloneDBInstance` 已含在 dmops AK（`rds:DescribeDBInstanceAttribute` / `rds:DescribeBackups` 现有同步链路已在用，一并确认） |
| 0-3 | 联调环境 | 一个测试实例 + 其备份集，一期末联调（含增量备份集能否克隆的验证） |

注：CloudDM 侧 AK / 数据源全局授权 / syncQuery 相关全部后移二期，一期不涉及。

## P1 后端：克隆链路（做到"状态可见 + 下线闭环"）

| # | 任务 | 产物 |
|---|---|---|
| 1-1 | `app/config.py` 增加 Drill 配置段（§8 一期子集：并发/超时/心跳，全部默认值） | config |
| 1-2 | **dmops/tests/ 测试基建**：conftest.py + pytest 进 requirements + Makefile test 目标激活；首批 mock 单测一起交 | 测试 |
| 1-3 | `app/infra/backup_drill_repository.py`：drill 表 CRUD（创建、drill_no 生成、状态推进、时间戳、心跳、列表、详情、offline 确认）；steps/diffs repo 空实现占位 | repo |
| 1-4 | `app/adapter/aliyun/rds.py`：`clone_db_instance`（§2.1 映射表组装参数，ClientToken=drill-{drill_no} 幂等）+ `describe_instance_attribute` 复用做轮询（宽容起点：硬错误连续 10 次判 failed） | SDK 封装 |
| 1-5 | `app/service/backup_drill_service.py`：`create_drill`（§2.3 一期 4 项参数检测、drill_no 生成、落 pending）、`cancel_drill`（仅 pending、CloneDBInstance 发出前）、`confirm_offline`；clone 阶段编排（提交→轮询 Running→落 clone_instance_id→success/failed） | service |
| 1-6 | worker：`create_app()` 启动后台线程轮询任务表（SKIP LOCKED 抢占、分钟级心跳、断点续跑），只跑 cloning 阶段；**dmops.Dockerfile CMD 改 gunicorn -w 1** | worker |
| 1-7 | `app/api/v1/backup_drill.py`：POST 发起 / GET 列表（含未下线过滤）/ GET 详情 / POST 取消 / POST confirm-offline / GET drill-preflight；`route.py` 注册 | API |

**P1 校验点**：`make lint` + `make test`（mock 单测：repo 状态机推进、drill_no 并发生成、参数检测分支、克隆轮询容错）。真实链路联调（发起→克隆→Running→详情，含 0-3 增量备份确认）由你执行，我提供 curl 命令清单。

## P2 前端（一期范围）

前置说明（对照现有代码的差距）：

- 10s 轮询是全新基建：dmops 前端无任务轮询先例（syncAccount 是同步阻塞），
  需 setInterval + 组件卸载清理 + 翻页/切 Tab 停轮询；InstanceDetail 的
  loadBackups 自带 loading 守卫，轮询刷新要走独立轻量接口或绕开守卫
- 内联校验是新模式：dmops 现有 3 个弹窗全部是 Toast 弹第一条错；本弹窗按
  §2.3 用字段内联（实例名称）+ Alert 区（备份集可用性/并发约束/Serverless）混合

| # | 任务 | 产物 |
|---|---|---|
| 2-1 | `services/http/dmops.js` 加 6 个 API 封装（发起/列表/详情/取消/confirm-offline/preflight）；i18n zh/en 词条（全 pinyin key） | 基础 |
| 2-2 | 备份集列表行内「备份恢复」按钮（IsAvail/进行中/增量待定禁用逻辑）+ 状态徽标（进行中 spinner / 克隆完成 ✓ / 失败 ✗）+ 10s 轮询 | 入口 |
| 2-3 | 发起弹窗：用途下拉（唯一项联动命名）、只读预览区、可编辑名称/描述、按量计费提示；参数检测错误展示（字段内联 + Alert 混合） | 弹窗 |
| 2-4 | 演练详情页：基础信息 + 克隆时间线（含失败原因）+ 待下线清单（克隆实例 ID）+ 确认下线按钮 | 详情 |
| 2-5 | 演练历史列表（按实例/状态过滤，含"未下线"过滤与确认按钮） | 列表 |

**P2 校验点**：eslint + `npm run build`（沙箱构建，部署用 `all_build.sh web`）；浏览器走查（发起→徽标轮询→详情→列表未下线闭环），走查流程按 `frontend/AGENTS.md` 维护进 `tests/frontend/`。

## 二期预告（不在本期计划内，占位备忘）

数据源匹配与复制式注册（§3.2/§3.3）、syncQuery 封装（签名/levels/AK 授权）、
库级对比 + 行级校验引擎（§4）、选表器/steps/diffs 前端、报告导出 md（§7）。
v6 review 已核验的技术结论见设计文档 §3/§4/§11，二期开工时无需重新调研。

## 执行约定

1. **顺序**：P1 → P2，阶段间不出并行；每阶段完成后停下来给你过一次（产物清单 +
   校验结果），你说"继续"再进下一阶段
2. **DDL/联调**：涉及真实库、阿里云的验证（P1 末）由你执行，我给操作步骤；
   沙箱内只做单测 + lint + build
3. **前端构建**：沙箱 `npm run build` 验证（临时 terser workaround 不入库），
   部署构建 `cd package && ./all_build.sh web` 在你 JDK17 环境跑
4. **改动范围**：`dmops/app/**`、`dmops/tests/**`（新建）、`dmops.Dockerfile`
   （CMD -w 1 一行）、`frontend/src/**`、两个文档；不改 console/backend，
   不碰 CloudDM 的表（dm_ds 相关整体二期）
5. 每阶段结束同步更新 `docs/backup-drill-design.md` 如有偏差（实现中发现设计
   问题时先报你决策，不擅自改设计）
6. **文档双份维护**：`backup-drill-design.md` 为唯一源，`backup-drill-design.html`
   由 `scripts/render_docs.js` 从 md 重新生成，不手改 html

## 你需要确认的点

1. 计划整体 OK？
2. P1 前置 0-1：DDL 你来执行？还是给我一个能连 cdmgr 库的通道？
3. 前置 0-2：需要你确认 AK 里 `rds:CloneDBInstance` 是否已授权
