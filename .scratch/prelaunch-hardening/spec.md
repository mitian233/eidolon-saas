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

## 02 角色和资料上限、自带向量服务 HTTPS

- 每个用户最多创建 50 个角色。每个角色最多导入 50 份文档、保存 2000 个段落。计数和插入在同一个数据库写事务中，超出上限时返回 409 和中文说明，整份文档均不写入。
- 同角色中已导入的相同文本直接返回原来的文档 ID，即使已满额也可重试尚未生成的向量。
- 创建角色和导入资料分别按用户限制请求频率。超频返回 429、`Retry-After` 和中文等待提示。角色表单和资料区展示后端提供的说明。
- 设置 `EIDOLON_DOMAIN` 时，用户自带的向量化和重排服务只接受 HTTPS。未设置时本地开发仍可使用 HTTP。

### Testing Decisions

- 在 SQLite 和真实 PostgreSQL 上分别走创建、导入 API，测试满额、并发写入、失败后无残留、重复导入重试向量，以及 429 和等待时间。并发写入使用同一数据库上的独立连接。
- 测试公网拒绝 HTTP、允许 HTTPS，以及本地允许 HTTP。串行运行相关测试、Ruff、Pyright 和 `sh scripts/affected-tests.sh 2bb7cbd3`，按仓库规范做两路代码审查。

## 03 多实例角色读取、PostgreSQL 备份提示和数据包说明

- 后端启动不读入全站角色。创建、编辑和删除角色以数据库为准，新的请求与回合经 `Database.read/write` 在工作线程读取当前账号的角色。对话、通话、记忆和其余使用角色信息的路径一并迁移。后台汇总只查询记录里用到的角色名。
- 检测到 PostgreSQL 时，内置备份与恢复命令拒绝运行，后台备份看板以普通说明显示「内置备份与恢复仅适用于 SQLite；PostgreSQL 请使用 pg_dump 与 age 加密备份」。SQLite 仍沿用现有流程。
- 部署文档说明如何用 `pg_dump`、gzip、age 备份 PostgreSQL，如何保留 30 天以及如何恢复。
- 设置页和数据包格式文档说明第 5 版包含对话、记忆和档案，不含角色人设与背景资料。导入对话时当前账号要有同一角色编号；删除角色、删号重来或迁往其他部署后，编号不同的对话会跳过，记忆和档案照常导入。

### Testing Decisions

- 两个独立后端连接同一临时 PostgreSQL。一个经 API 创建、编辑和删除角色，另一个经 API 开始对话、完成回合、读取新版角色设置并在删除后收到 404。LLM 使用已有测试替身。
- 覆盖 PostgreSQL 下 `Backups`、后台的 GET/POST 及 `eidolon backup/restore`，保留 SQLite 用例。
- 串行运行相关后端测试、Ruff、Pyright、前端测试和构建，以及 `sh scripts/affected-tests.sh 4cf28e2f`。按仓库规范做两路代码审查，清理临时资源。
