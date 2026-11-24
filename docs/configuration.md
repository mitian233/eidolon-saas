# 配置

Eidolon-SaaS 使用用户自带的模型、语音和向量化密钥（BYOK）。公益部署把部署者的模型和语音密钥留空即可。可选的对话和语音兜底由部署者在 `.env` 显式配置，使用时费用由部署者承担。配置清单见 [`.env.example`](../.env.example)，从本仓库构建和部署的步骤见 [部署](deploy.md)。

有后台时（设了 `EIDOLON_ADMINS`，或开着开发登录），可在 `/admin` 修改限额、玩法开关和注册方式。后台不再展示或接受平台模型、语音、向量、重排、判断及天气服务的凭据；用户自己的 key 只在用户浏览器里填写。后台改过的运营设置优先于 `.env`，要重新使用 `.env` 的值可在后台恢复。

## 数据库

单进程可以用 SQLite 或 PostgreSQL。使用 PostgreSQL 时，填已有数据库的连接地址；多个 API 或通话进程使用同一个地址：

```env
DATABASE_URL=postgresql://<用户>:<密码>@<数据库主机>:5432/<数据库名>
```

地址支持 `postgresql://` 和 `postgres://`；可在地址里加 `sslmode=require` 等 Postgres 参数。程序使用 psycopg 3，保留原有 `Store` 接口；读操作在只读、REPEATABLE READ 事务中完成。写操作仍按原有规则串行提交，数据库事务锁让不同 API 进程里的「先读再写」也不会互相覆盖。每个进程默认开 1 个写连接、4 个读连接。

没设 `DATABASE_URL` 时，继续使用 `EIDOLON_DATABASE_PATH` 指向的 SQLite 文件，默认 `data/eidolon.db`。`DATABASE_URL` 优先于本地文件路径；代码直接传入的 Postgres URL 优先于环境变量。Postgres 地址不通时启动失败，不会改用本地文件。

切换地址不会自动搬运 SQLite 里的旧数据。Postgres 的导出与导入请使用 `pg_dump` / `pg_restore`；现有 `eidolon backup` / `eidolon restore` 和 `deploy/db-*.sh` 面向 SQLite 文件，不能用于 Postgres。Postgres 删除账号后，旧行版本、WAL 和导出文件保留多久由数据库的运维设置决定，不承诺 SQLite 的文件覆写行为。

后端测试用 `pgserver` 在 Linux/macOS 启动临时 Postgres，不需要 Docker 或管理员身份；`test_database.py` 的存取、事务、API 对话和统计测试同时覆盖 `[sqlite]`、`[postgres]`。数据库和服务随测试结束关闭。

## 角色

登录后在角色目录创建或管理角色，在角色编辑页的「资料」区粘贴文本或上传文本文件。角色也可通过以下 API 操作，需要登录会话：

| 接口 | 作用 |
|---|---|
| `POST /api/characters` | 建角色（201） |
| `GET /api/characters` | 列出自己的角色 |
| `GET /api/characters/{id}` | 读一个角色 |
| `PUT /api/characters/{id}` | 改角色 |
| `DELETE /api/characters/{id}` | 删角色（204，先结束与该角色进行中或正在建立的通话） |

请求体字段（`POST`/`PUT` 相同，多余字段会被拒绝）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `name` | 字符串，必填 | 角色名，1–100 字 |
| `sheet` | 字符串，必填 | 人设文本，1–100000 字，自由分节（Markdown） |
| `intro` | 字符串 | 一句话介绍，≤2000 字 |
| `avatar_url` | http/https URL 或 null | 头像外链；平台不托管素材文件 |
| `greeting` | 字符串 | 问候语，≤10000 字 |
| `voice_id` | 字符串 | 用户自己的 Fish Audio 音色 ID（通话用） |
| `color` | `#rrggbb` | 印象色，默认 `#64748b` |
| `user_address` | 字符串 | 角色怎么称呼用户，默认「你」，1–80 字 |
| `language_mode` | `single` / `bilingual` | 输出语言：单语言（默认）或 `<ja><zh>` 双语 |
| `birthday` | `{"month": M, "day": D}` 或 null | 生日 |
| `age` | 整数或 null | 年龄，0–10000 |

角色私有：只有创建者自己可见，无分享、无发现。记忆归属用户，跨该用户自己的角色共享（其他角色以转述口吻提起）。

每个账号最多创建 50 个角色。每个角色最多保存 50 份文档、2000 个段落。新增会超出上限时，API 返回 409。满额后仍可重新导入相同文本，拿到原来的文档 ID 并重试尚未完成的向量化。

每个账号每分钟最多发起 20 次角色创建、每小时 100 次。资料导入每分钟最多 60 次、每小时 240 次，同一账号的所有角色共用这两项导入次数。每个后端进程最多同时处理 20 次创建和 20 次导入。请求过多时返回 429，`Retry-After` 给出等待秒数。请求次数按后端进程分别计算，进程重启后重新计数。

## 自带密钥（BYOK）

用户在设置页「自带密钥」填自己的 key，目前覆盖：

| 服务 | 用途 | 服务商 |
|---|---|---|
| LLM | 对话、记忆提炼、起标题 | 任何 OpenAI 兼容 / Responses / Anthropic 接口的服务 |
| TTS | 语音合成 | Fish Audio |
| STT | 语音识别 | Soniox 或阿里云百炼 |
| 生图 | 密钥设置保留，当前版本关闭照片玩法 | NovelAI 或 OpenAI 图像格式 |
| 向量化 | 长期记忆、资料召回 | 任何 OpenAI 兼容 `/embeddings` 端点 |
| 重排 | 对召回的资料与记忆排序（可不填） | SiliconFlow `/rerank` 格式端点 |

key 只存在浏览器里，回合/通话期间随请求带给后端、在进程内存里用完即弃：不落库、不进日志、后台看不到（ADR-0017）。回合结束后的记忆提炼、起标题在本进程内用同一把 key 继续做。

用自带 LLM 的文字回合不计入限额；通话带齐了免限额密钥（`EIDOLON_EXEMPTING_LLM`/`_TTS`/`_STT`，默认三项都选）也不计入。

## 回合后的任务

记忆提炼和对话起标题在接下本回合的 API 进程里执行，不等它们结束就返回回复。失败后用同一个仍留在内存里的模型和 key 立即再试一次，最多共两次；服务关闭时取消的任务不重试。不启动独立 worker，也不从数据库取出旧任务补跑。

`jobs` 表只保存 `id`、`turn_id`、`type`（`memory` / `title`）、`status`（`pending` / `running` / `succeeded` / `failed` / `cancelled`）、`attempts`、`error`、`created_at` 和 `updated_at`。`turn_id` 指向角色已保存的回复 ID；同一条回复每种任务只记录一次。`error` 只写错误类型（例如 `LLMError`、`ValueError`、`CancelledError`），不保存服务商返回的错误文本、对话内容、端点或 key；成功后清空。提炼结果不是要求的 JSON、标题为空时，也记为失败并重试。服务正常关闭时，等待写数据库或执行动作期间被取消的任务记为 `cancelled` / `CancelledError`，等待已提交的写入完成后收尾，不重试；按状态统计可与执行出错的 `failed` 分开。记忆已写入而向量化失败时仍保留记忆，沿用下次读取时补算向量的做法。

可用 `SELECT id, turn_id, type, status, attempts, error, created_at, updated_at FROM jobs WHERE status = 'failed' ORDER BY updated_at DESC;` 查看失败记录，或按 `type`、`status` 分组计数。`Store.get_job(id)` / `Store.jobs_for_turn(turn_id)` 供进程内读取。删除对话或账号时一起删除这些记录；其余记录暂不自动清理。进程被强制终止时可能留下 `pending` / `running`，因为 key 已丢失，重启后不会自动重试它们。


## 登录、用户与限额

- 登录：GitHub 或 Google OAuth，至少配一家（`GITHUB_CLIENT_*`、`GOOGLE_CLIENT_*`，见 deploy.md）。本地开发用 `EIDOLON_DEV_LOGIN=1` 按名字登录。
- `EIDOLON_ADMINS`：管理者名单，逗号分隔的 `provider:subject`（`eidolon user list` 查）。设置后可在设置页进入后台。仅在本地开启开发登录且名单为空时，所有用户都是管理者。
- `EIDOLON_REGISTRATION`：`open`（默认）或 `invite`。新站建议从 `invite` 起步。管理者在后台「配置 → 注册」生成或删除邀请，已注册用户照常登录；管理者初次登录可直接注册。空数据库没设管理者时，允许首位用户暂时登录以取得自己的身份标识。对外开放前先把管理者填入名单。
- `EIDOLON_CONTACT`：公开联系信息，显示于举报页和站点条款，登录被封禁或需要邀请时也会显示。
- `NEXT_PUBLIC_EIDOLON_SOURCE_URL`：前端构建时指定运行版本对应的公开源码地址，默认链接到本项目的 `saas/main`。部署修改版时填修改版的源码地址，再构建前端。
- 限额（都可选，0 为不限）：`EIDOLON_TURNS_PER_HOUR`（默认 60）、`EIDOLON_CALLS_PER_HOUR`（默认 5）、`EIDOLON_CALL_MINUTES`（默认 10）、`EIDOLON_TURNS_PER_CALL`（默认 40）、`EIDOLON_CONCURRENT_CALLS`（默认 10）。后台可以按用户单独设。
- `EIDOLON_HISTORY_TURNS`：每回合带给模型的历史回合数下限（默认 20，0 为整段对话）。
- `EIDOLON_SECRET_KEY`：部署密钥，用于封禁名单等操作。用 `openssl rand -hex 32` 生成，填好后保持固定。

后台配置页仅提供限额、玩法开关和注册设置。模型、语音、向量化、重排、天气等平台凭据不会出现在 `/api/admin/config` 响应中，也不能通过后台配置接口保存；旧的模型和网络配置标签已移除。

访客和登录用户都可以从页脚提交内容举报。管理者在后台「举报」查看、更新处理状态和记录理由，并在「用户」页操作封禁、解封或删除。

## 部署者的模型（可选兜底）

对话模型 `CHAT_LLM_BASE_URL`/`API_KEY`/`MODEL` 三项要么都填、要么都不填；配了就要支持流式输出和工具调用（启动时检查）。`CHAT_LLM_PROTOCOL` 三选一：`chat-completions`（默认）、`responses`、`anthropic`。可选 `CHAT_LLM_MAX_TOKENS`、`CHAT_LLM_REASONING_EFFORT`、`CHAT_LLM_CALL_REASONING_EFFORT`、`CHAT_LLM_EXTRA_BODY`。

后台模型 `BACKGROUND_LLM_*`：回合结束后提炼记忆、起标题用；不填沿用对话模型的设置。

## 向量化、重排与判断（可选）

用户在设置页填写自己的向量与重排端点；地址、模型、维度和 key 只留在当前浏览器，每次文字回合和通话随请求带来，回合后的记忆提炼仍由同一进程使用这次带来的模型完成。服务器不保存这些设置或 key，也不为缺少的用户端点补平台凭据。

部署设置了 `EIDOLON_DOMAIN` 时，自带向量化和重排端点须使用 HTTPS。未设置域名的本地部署仍可使用 HTTP。

- 向量化统一 `POST {base_url}/embeddings`，支持 OpenRouter 等 OpenAI 兼容端点。填写 base_url、模型、维度和 key。更换端点、模型或维度会重新计算记忆向量和当前角色已有资料的向量，旧向量不会参与当前模型的召回。内部标识使用地址的不可逆摘要加 `model@dimensions`，不保存原始端点；各模型的资料向量分别保存，不覆盖彼此。没有向量端点时，资料召回与记忆提炼关闭。
- 重排可不填：按向量相似度取前几条。填写时用支持 SiliconFlow `/rerank` 格式的端点，输入 `{model, query, documents, top_n}`，输出 `results[].index/relevance_score`。OpenRouter 没有此接口。已校准模型继续使用原来的资料/记忆阈值，未知模型沿用 Qwen3-Reranker-4B 的 `0.7 / 0.005`。
- 判断功能默认关闭。在设置页开启后，用用户对话 LLM 的同一模型与 key，以 `reasoning_effort=low` 发一次小请求，沿用召回的三个是非题与阈值；通话逐段表情也使用此模型。关闭或未配 LLM 时好感度不再更新、通话表情使用默认值，有向量端点时仍提供 `recall_story` 工具。已保存的好感度仍显示，既有冷却继续阻止新回合，不能通过关闭判断功能绕过。设置页会明确显示是否关闭及调用费用由用户承担。

通话的判断阈值与最长等待时间继续用 `JUDGE_EMOTION_MIN_PROBABILITY`、`JUDGE_EMOTION_TIMEOUT`（默认 1.5 秒）调整。显式设置的情绪阈值优先；未设置才使用模型阈值，未知模型沿用默认阈值。旧的 `JEV_EMOTION_MIN_PROBABILITY`、`JEV_EMOTION_TIMEOUT` 已废弃，可删除，残留值会被忽略。

部署者不需要配置向量化、重排或判断模型的 key。`EMBEDDING_PROVIDER` 和 Gemini 原生向量接口已移除。旧判断变量 `JUDGE_PROVIDER`、`JEV_API_KEY`、`JEV_MODEL`、`JEV_BASE_URL`、`AI_GATEWAY_API_KEY`、`AI_GATEWAY_BASE_URL`、`CLOUDFLARE_API_TOKEN`、`CLOUDFLARE_ACCOUNT_ID`、`CLOUDFLARE_JUDGE_MODEL`、`BAILIAN_JUDGE_API_KEY`、`BAILIAN_JUDGE_WORKSPACE_ID`、`BAILIAN_JUDGE_REGION`、`BAILIAN_JUDGE_MODEL` 已废弃，可从 `.env` 删除；残留值会被忽略，既不会导致启动失败，也不会产生平台判断调用。底层组件保留 `EMBEDDING_BASE_URL/MODEL/DIMENSIONS/API_KEY`、`RERANK_BASE_URL/MODEL/API_KEY` 读取入口，供本机直接使用；不会成为用户端点的兜底。

代理新增 `own_embedding` 与 `own_rerank` 两个开关，沿用已知服务商才经代理、其他用户端点直连的规则。走用户 key 的向量化、重排与判断请求记录为用户自带服务，不计平台限额。

## 语音（可选兜底）

通话主要走用户自带的 key。部署者的兜底：`STT_PROVIDER`（`soniox` 默认，用 `SONIOX_API_KEY`；`bailian` 用 `DASHSCOPE_API_KEY`）、`FISH_AUDIO_API_KEY`、`FISH_AUDIO_MODEL`（默认 `s2.1-pro-free` 不耗额度）。

WebRTC：`EIDOLON_ICE_SERVERS`（默认 Google 公共 STUN）、`EIDOLON_TURN_URLS`/`EIDOLON_TURN_SECRET`（生产用 compose 自带的 coturn，只需要填密钥）。

### 通话进程拆分

| 变量 | 作用 |
|---|---|
| `EIDOLON_ROLE` | `all` 默认单进程；`api` 处理普通接口并选择通话节点；`calls` 是可独立处理通话的完整后端 |
| `EIDOLON_CALL_NODES` | api、calls、前端共有的 JSON 节点表，如 `{"voice-a":"http://127.0.0.1:8101"}`；只接受 HTTP(S) 根地址，不接受账号密码、路径、query 或 fragment |
| `EIDOLON_CALL_NODE_ID` | calls 使用的节点 ID，必须在表中，1–64 个字母、数字、下划线或连字符；活着的进程不能共用同一个 ID |
| `DATABASE_URL` | 拆分时必须是同一个 PostgreSQL 地址；默认 all 可继续用 SQLite |

并发通话上限在所有节点间共用，用户带齐自带 key 也受此上限限制。通话分钟仍写 `calls` 表并计入现有统计，没有新增计费系统。节点登记和控制仅保存通话归属、状态、时间与结束原因，不保存用户 key 或模型请求。失联或重启的通话按连接中断处理，不迁移。单机 compose 用法见 [部署说明](deploy.md#可选同机拆分通话节点)。

## 玩法状态

| 玩法 | 状态 |
|---|---|
| 文字对话、通话、长期记忆、资料召回、好感度 | 保留（记忆/召回/好感度按上面的配置降级） |
| 礼物、照片、主动搭话、生理期、酒吧、朋友圈、信、日程、天气、朗读、抽奖/重置卡 | 当前版本关闭 |

`EIDOLON_AFFINITY_AND_GIFTS`（默认 1）控制平台是否启用好感度；产生新的好感度变化还需用户开启判断功能。其余关闭玩法的开关变量不再在 `.env.example` 里列出。

## 网络代理与服务状态

见 [deploy.md「网络和代理」](deploy.md#网络和代理)。`EIDOLON_PROXY_URL` + `EIDOLON_PROXY_SERVICES` 在服务器设置，后台不再提供「网络」标签。

服务状态（对话列表铃铛旁给用户看各项服务正不正常）：`EIDOLON_STATUS_SERVICES`（逗号分隔，`all`/`none`）、`EIDOLON_STATUS_WINDOW_MINUTES`（10/30/60，默认 30）。没配的服务自动不显示。

## 命令行

```text
eidolon serve              启动服务（默认）
eidolon user list          所有用户：ID、名字、登录方式、创建时间、是否封禁
eidolon user ban <id>      封禁（--note 备注），所有设备退出登录，通话几秒内挂断
eidolon user unban <id>    解封
eidolon user usage <id>    最近 24 小时按小时的用量
eidolon backup             备份数据库（deploy/db-backup.sh 包装它）
eidolon restore <file>     用解密好的备份替换数据库（deploy/db-restore.sh 包装它）
eidolon doctor             按 .env 逐项试各服务，说明哪里不对（--json 给 agent 读）
```

角色和素材不再有命令行入口：角色走 API，素材一律外链。