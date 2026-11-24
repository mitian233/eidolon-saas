# 上线前加固

## 01 PostgreSQL 断线重连和 jobs 保留期

PostgreSQL 重启、网络断开或服务端关闭空闲连接后，后端仍持有原来的连接，后续请求会持续失败。正常结束、失败或取消的回合后任务也会永久留在 jobs 表中。

### PostgreSQL 连接

- 在数据库工作线程上重建已断开的连接。新读连接恢复只读设置，新写连接重新安装已通过 `Database.function()` 注册的 SQL 函数。
- 连接在 `BEGIN` 时断开，且业务 SQL 尚未执行，可以重新开始事务。只读事务执行期间断线，可以从头重试一次。
- 写事务开始执行业务后断线，当次操作报错，下一次操作换用新连接。即使无法确定 `COMMIT` 是否成功，也不重放写事务。
- 保留 ADR-0028 的单写线程和读线程池，SQLite 照常使用 WAL 和 checkpoint。`/api/health` 继续使用独立读连接，数据库不可读时返回 503，可读后返回 200。

### jobs 保留期

- 和 activity 一样保留 90 天。以 `updated_at` 为准，只删除早于截止时间的 `succeeded`、`failed` 和 `cancelled` 行。
- 用 `housekeeping.in_batches` 分批删除。后端启动时清理，之后随现有 `keep_tidy` 每 10 分钟运行。

## Testing Decisions

- 用 pgserver 启动真实 PostgreSQL，通过 `pg_terminate_backend` 断开空闲连接和进行中的事务。测试读写恢复、写回调只执行一次、SQL 函数和只读设置恢复，以及 `/api/health` 从 503 恢复到 200。
- 在 SQLite 和 PostgreSQL 上测试 jobs 清理。每批提交后读取剩余行，确保已过期的终态任务分批删除，未过期和未完成的任务保留。
- 串行运行相关测试、Ruff、Pyright 和 `sh scripts/affected-tests.sh 65fd21b1`。按仓库约定做两路代码审查，清理测试启动的 PostgreSQL 和临时目录。
