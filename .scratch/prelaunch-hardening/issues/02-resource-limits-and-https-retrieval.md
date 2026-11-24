# 02 角色和资料上限、自带向量服务 HTTPS

Status: done

上线前防止资源被大量请求占满，并避免用户自带密钥通过明文 HTTP 发出。见 [规格](../spec.md#02-角色和资料上限自带向量服务-https)。

## 验收项

- [x] 单用户最多 50 个角色。单角色最多 50 份文档及 2000 个段落。并发写入无法超过上限，超额时返回 409 和中文说明，文档与段落均无残留。
- [x] 文档或段落满额时，同一文档仍可重复导入，返回原 ID，并重试未完成的向量化。
- [x] 创建角色和导入资料分别按用户限流，超频返回 429 和 `Retry-After`。角色表单和资料区显示后端错误详情，配置文档说明这些限制。
- [x] 公网部署的自带向量化和重排拒绝 HTTP、允许 HTTPS。本地部署仍允许 HTTP。
- [x] 串行运行 SQLite、PostgreSQL、Ruff、Pyright 与 `sh scripts/affected-tests.sh 2bb7cbd3`。如修改前端，运行前端测试、类型、shadcn 纪律和生产构建。完成两路代码审查并清理临时资源。

## Comments

### 实现说明（票 02）

- `CharacterRepository.create` 和 `Documents.import_text` 在各自的 `Database.write` 事务里先计数再插入。SQLite 用 `BEGIN IMMEDIATE`，PostgreSQL 用现有写事务锁。重复资料在计数前返回原 ID，随后照常补齐缺失的向量。按文档 ID 为段落建立索引，便于统计单个角色的段落。
- 两个 POST 接口各用一个 `Throttle`。每个账号每分钟可发起 20 次创建、60 次导入，每小时分别为 100 次和 240 次。每个后端进程分别计数，创建、导入各最多同时处理 20 次。满额返回 409，超频返回 429 和 `Retry-After`。前端用 `rate_limited` 区分这类 429，直接显示后端的等待说明。
- `OwnRetrievalService` 的两个客户端在公网部署时都要求 HTTPS，拒绝发生在直连或交给代理之前。未启用公网模式的客户端仍可使用 HTTP。
- 规格审查通过。按规范审查的建议，并发测试让两个请求在独立数据库连接上同时到达写入，再让第二笔写入排队，之后才允许第一笔继续。SQLite 和 PostgreSQL 上的六个并发用例通过。
- 在 Chromium 中提交生产构建的创建角色与资料导入表单，两个页面都显示了 409、422、429 的后端详情。前端 788 项测试、类型、shadcn 规则和生产构建通过。构建提示缺少 `LINE Seed JP` 的备用字体度量。
- `sh scripts/affected-tests.sh 2bb7cbd3` 在并发测试调整后再次通过，其中后端 289 项、前端 407 项。Ruff 与 Pyright 通过。已停止临时服务和 PostgreSQL，已删除临时目录。
