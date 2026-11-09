"""备份恢复演练 worker（一期：克隆阶段）。

单进程后台线程（gunicorn -w 1，见 docs/backup-drill-design.md §8）：
- 扫描 pending 记录 → 抢占（pending→cloning）→ 提交克隆 → 轮询 Running。
- 心跳超时的 cloning 记录重新接管（进程崩溃续跑）；clone_instance_id 已落库时
  幂等跳过提交，仅续轮询。

全局并发=1 的串行由线程内逐条执行保证：同一时刻 worker 只处理一条活动记录。
"""
