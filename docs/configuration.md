# 配置

Eidolon-SaaS 是公益 BYOK 服务：**平台零凭据也能启动和服务**。所有第三方 key 都可选——不配时每个回合用用户自带的 key；配了部署者的 key 就作兜底（用户没带时用部署者的）。环境变量的完整清单和写法见仓库根目录 [`.env.example`](../.env.example)，部署步骤见 [deploy.md](deploy.md)。

有后台时（设了 `EIDOLON_ADMINS`，或开着开发登录），模型、key、限额等很多项也可以在 `/admin` 后台改：后台改过的项优先于 `.env`，之后再改 `.env` 的同一项不生效，要先在后台恢复。启动日志列出被后台覆盖的项。

## 角色

角色存在数据库里，通过 API 创建和管理（M0 没有编辑界面，通用壳在 M2）。登录拿到会话 cookie 后：

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
| `voice_id` | 字符串 | 用户自己的 Fish Audio 音色 ID（通话用，M3） |
| `color` | `#rrggbb` | 印象色，默认 `#64748b` |
| `user_address` | 字符串 | 角色怎么称呼用户，默认「你」，1–80 字 |
| `language_mode` | `single` / `bilingual` | 输出语言：单语言（默认）或 `<ja><zh>` 双语 |
| `birthday` | `{"month": M, "day": D}` 或 null | 生日 |
| `age` | 整数或 null | 年龄，0–10000 |

角色私有：只有创建者自己可见，无分享、无发现。记忆归属用户，跨该用户自己的角色共享（其他角色以转述口吻提起）。

## 自带密钥（BYOK）

用户在设置页「自带密钥」填自己的 key，目前覆盖：

| 服务 | 用途 | 服务商 |
|---|---|---|
| LLM | 对话、记忆提炼、起标题 | 任何 OpenAI 兼容 / Responses / Anthropic 接口的服务 |
| TTS | 语音合成 | Fish Audio |
| STT | 语音识别 | Soniox 或阿里云百炼 |
| 生图 | 照片（玩法待后续里程碑） | NovelAI 或 OpenAI 图像格式 |

key 只存在浏览器里，回合/通话期间随请求带给后端、在进程内存里用完即弃：不落库、不进日志、后台看不到（ADR-0017）。回合结束后的记忆提炼、起标题在本进程内用同一把 key 继续做。embedding/rerank 的 BYOK 扩展在 M1。

用自带 LLM 的文字回合不计入限额；通话带齐了免限额密钥（`EIDOLON_EXEMPTING_LLM`/`_TTS`/`_STT`，默认三项都选）也不计入。

## 登录、用户与限额

- 登录：GitHub 或 Google OAuth，至少配一家（`GITHUB_CLIENT_*`、`GOOGLE_CLIENT_*`，见 deploy.md）。本地开发用 `EIDOLON_DEV_LOGIN=1` 按名字登录。
- `EIDOLON_ADMINS`：管理者名单，逗号分隔的 `provider:subject`（`eidolon user list` 查）。不填时后台不存在（开发登录除外）。
- `EIDOLON_REGISTRATION`：`open`（默认）或 `invite`（只让受邀的人注册，邀请链接在后台「注册」里生成）。
- `EIDOLON_CONTACT`：被封禁的用户、没有邀请链接被挡下的人看到的联系方式。
- 限额（都可选，0 为不限）：`EIDOLON_TURNS_PER_HOUR`（默认 60）、`EIDOLON_CALLS_PER_HOUR`（默认 5）、`EIDOLON_CALL_MINUTES`（默认 10）、`EIDOLON_TURNS_PER_CALL`（默认 40）、`EIDOLON_CONCURRENT_CALLS`（默认 10）。后台可以按用户单独设。
- `EIDOLON_HISTORY_TURNS`：每回合带给模型的历史回合数下限（默认 20，0 为整段对话）。
- `EIDOLON_SECRET_KEY`：加密后台保存的 key、给封禁名单做哈希；`openssl rand -hex 32`，填了不要换。用户的自带密钥跟它无关。

## 部署者的模型（可选兜底）

对话模型 `CHAT_LLM_BASE_URL`/`API_KEY`/`MODEL` 三项要么都填、要么都不填；配了就要支持流式输出和工具调用（启动时检查）。`CHAT_LLM_PROTOCOL` 三选一：`chat-completions`（默认）、`responses`、`anthropic`。可选 `CHAT_LLM_MAX_TOKENS`、`CHAT_LLM_REASONING_EFFORT`、`CHAT_LLM_CALL_REASONING_EFFORT`、`CHAT_LLM_EXTRA_BODY`。

后台模型 `BACKGROUND_LLM_*`：回合结束后提炼记忆、起标题用；不填沿用对话模型的设置。

## 向量化、重排与判断（可选）

配了才有主动资料召回和记忆；没配时角色只凭人设回复，召回退到模型自己发起的 `recall_story` 工具（需要向量化），记忆关闭。

- 向量化 `EMBEDDING_PROVIDER`：`siliconflow`（默认，`SILICONFLOW_API_KEY`）或 `gemini`（`GEMINI_API_KEY`，不对中国大陆开放；免费层内容会被 Google 用于改进产品，公开部署介意就开通计费并填 `GEMINI_BILLING_ENABLED=1`）。模型/维度：`EMBEDDING_MODEL`、`EMBEDDING_DIMENSIONS`。
- 重排固定在硅基流动：`SILICONFLOW_API_KEY`、`RERANK_MODEL`（默认 Qwen3-Reranker-0.6B）、阈值 `RERANK_MIN_RELEVANCE`/`RERANK_MEMORY_MIN_RELEVANCE`。
- 判断模型 `JUDGE_PROVIDER`：`jev`（默认，`JEV_API_KEY`，经 OpenRouter）、`cloudflare`（`CLOUDFLARE_API_TOKEN`/`CLOUDFLARE_ACCOUNT_ID`，Workers AI 上的 Clef）、`bailian`（`BAILIAN_JUDGE_API_KEY`/`BAILIAN_JUDGE_WORKSPACE_ID`）。没配时不主动检索、好感度关闭、通话表情走默认值。

## 语音（可选兜底）

通话主要走用户自带的 key。部署者的兜底：`STT_PROVIDER`（`soniox` 默认，用 `SONIOX_API_KEY`；`bailian` 用 `DASHSCOPE_API_KEY`）、`FISH_AUDIO_API_KEY`、`FISH_AUDIO_MODEL`（默认 `s2.1-pro-free` 不耗额度）。

WebRTC：`EIDOLON_ICE_SERVERS`（默认 Google 公共 STUN）、`EIDOLON_TURN_URLS`/`EIDOLON_TURN_SECRET`（生产用 compose 自带的 coturn，只需要填密钥）。

## 玩法状态

| 玩法 | 状态 |
|---|---|
| 文字对话、通话、长期记忆、资料召回、好感度 | 保留（记忆/召回/好感度按上面的配置降级） |
| 礼物、照片、主动搭话、生理期、酒吧、朋友圈、信、日程、天气、朗读、抽奖/重置卡 | 关闭，留待 M4 之后按需改造（依赖部署者凭据或原作目录） |

`EIDOLON_AFFINITY_AND_GIFTS`（默认 1）控制好感度；需要判断模型。其余关闭玩法的开关变量不再在 `.env.example` 里列出。

## 网络代理与服务状态

见 [deploy.md「网络和代理」](deploy.md#网络和代理)。`EIDOLON_PROXY_URL` + `EIDOLON_PROXY_SERVICES`；后台「网络」标签可改。

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