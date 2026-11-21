# 01 公益上线条款与举报

Status: done

见[规格](../spec.md)。

- [x] `/terms`、`/privacy` 和页脚与公益 BYOK 服务相符，能找到开源源码和举报入口。
- [x] `/report` 对访客和登录用户开放，有配置时显示联系方式。公开接口限制字段长度、请求体大小和提交频率。
- [x] 管理者能查看和筛选举报、保存状态和备注，从举报页进入用户管理。其他用户访问管理接口返回 404。
- [x] SQLite 和 PostgreSQL 都覆盖立即退出登录、挂断通话、解封及删除账号和关联数据。
- [x] 串行通过本票的后端、前端、受影响测试和本地构建版浏览器流程，完成两路代码审查。

## Comments

### 实现说明（票 01）

- 访客和用户都可以通过 `POST /api/reports` 提交并取得编号。`reports` 和 `report_rate_limits` 随数据库启动建表，独立于账号。每个来源地址在一个十分钟时段最多提交五条。Caddy 直接转发这条公开接口，普通和生产 Compose 都保留来源地址。
- 后台在 `/admin/reports` 读取 `GET /api/admin/reports`，按状态分页，通过 `PATCH /api/admin/reports/{id}` 保存状态和备注。举报中的链接按文本显示。封禁、解封及删除从现有用户管理执行，后台封禁会主动结束正在进行的通话。
- 条款、隐私政策和页脚提供举报入口。报告页和条款页读取 `EIDOLON_CONTACT`。`NEXT_PUBLIC_EIDOLON_SOURCE_URL` 可在前端构建时指定对应的开源源码，未配置时链接到 fork 的 `saas/main`。
- 规范审查没有发现问题。按票审查发现普通 Compose 下访客共用提交频率，以及 PostgreSQL 删除测试遗漏对话、记忆、档案和其他设备会话，已补齐。
- 后端相关测试 77 项、前端全量测试 788 项通过。Ruff、Pyright、前端类型检查、shadcn 规则和生产构建均通过。`affected-tests.sh 60ee116b` 中后端 140 项、前端 563 项通过。Playwright 走通公开页面提交、后台处理和用户管理跳转。本机 Caddy 进程跑通两种入口配置。当前帐号无法访问 Docker 守护进程，Compose 校验到配置展开。
