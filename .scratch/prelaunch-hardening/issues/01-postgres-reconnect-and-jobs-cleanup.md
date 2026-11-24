# 01 PostgreSQL 断线重连和 jobs 清理

Status: done

上线前高优先级可用性修复。规格见 [spec.md](../spec.md)。

## 验收项

- [x] PostgreSQL 的读写连接断开后自动重建，恢复读连接的只读设置和 `Database.function()` 注册的 SQL 函数。
- [x] `BEGIN` 阶段和只读事务断线可重试，写事务中断后报告错误，后续写入恢复，断线的写事务不重放。
- [x] 用真实临时 PostgreSQL 测试读写及 `/api/health` 恢复，SQLite 的单写线程、WAL 和 checkpoint 行为继续通过现有测试。
- [x] `keep_tidy` 分批清理超过 90 天的终态 jobs，在 SQLite 和 PostgreSQL 上保留未过期及未完成的任务。
- [x] 串行运行相关测试、Ruff、Pyright 和 `sh scripts/affected-tests.sh 65fd21b1`，完成双路代码审查和所需复验，清理临时进程及目录。

## Comments

### 实现说明（票 01）

- `data_access.py` 在读任务或写事务的 `BEGIN IMMEDIATE` 阶段允许重连后重试一次。`database.py` 重建 PostgreSQL 会话时恢复只读设置或重新安装登记过的 SQL 函数。写回调和 `COMMIT` 断线时，当次请求报错，下一次写入重连。
- `Store.forget_old_jobs(now)` 使用 `housekeeping.RECORDS_KEPT`，与 `activity.KEPT` 共用 90 天。按 `updated_at` 和终态筛选，每批单独提交。新的索引按清理条件建立，替换原来按 `created_at` 排序的索引。`assembly.py` 从现有 `keep_tidy` 调用它。
- 相关测试 79 项通过，包含 SQLite 和临时 PostgreSQL。`sh scripts/affected-tests.sh 65fd21b1` 运行的 363 项测试通过，Ruff 和 Pyright 通过。按仓库规范和规格做的两路审查均未提出需修改的问题。临时 PostgreSQL 已退出，临时目录已删除。
