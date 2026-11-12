# Eidolon-SaaS（工作名）

通用角色托管服务：任何人自建角色人设、导入背景资料，和角色文字对话、语音通话。
运行模式是**公益免费 + BYOK**（Bring Your Own Key）：

- 平台不出一分第三方 API 费——模型、语音、向量化凭据全部由用户自带，key 只留在浏览器和回合期间的进程内存里，平台不保存。
- 平台不碰素材版权——角色内容与素材全部来自用户，平台只存外链地址。
- 平台只提供主机、数据库和通话媒体面（WebRTC + TURN）。

本仓库是 [Sallyn0225/eidolon-sc](https://github.com/Sallyn0225/eidolon-sc) 的 fork，与上游分道：上游的 283 版照常独立发展，本 fork 不携带任何原作内容（人设包、剧情库、立绘包、音色、酒吧素材一律不进仓库），也不再 merge 上游 main，引擎级修复按需 cherry-pick。设计见 [`docs/ryugi/specs/2026-11-12-saas-byok-design.md`](docs/ryugi/specs/2026-11-12-saas-byok-design.md)。

## 进度

| 里程碑 | 内容 | 状态 |
|---|---|---|
| M0 | 摘除领域绑定：清除 283 内容，角色入库（API 建角色），零平台凭据启动，单语言输出默认 | **当前** |
| M1 | 多租户：SQLite → Postgres，BYOK 扩到 embedding/rerank，后台零 key 形态 | 未做 |
| M2 | 角色编辑界面、通用壳、背景资料导入与召回 | 未做 |
| M3 | 通话：用户音色（Fish Audio）、用户 STT、通话分钟记录 | 未做 |
| M4 | 公益上线：条款与举报、数据导出删除、invite 注册、公开源码确认 | 未做 |

M0 可用：注册登录（OAuth 或开发登录）、通过 API 自建角色、用自带 LLM key 文字对话、长期记忆（部署配了向量化时）、好感度（配了判断模型时）。通话的 WebRTC 代码在，完整的 BYOK 通话流程在 M3 打磨。礼物、照片、酒吧、朋友圈、信、日程、天气、朗读等依赖部署者凭据或原作目录的玩法已关闭，留待 M4 之后按需改造。

## 本地开发

需要 [uv](https://docs.astral.sh/uv/) 和 Node.js 22。

```sh
cp .env.example .env        # 默认开着开发登录（EIDOLON_DEV_LOGIN=1），第三方 key 一个都不用填

cd backend && uv sync
uv run --env-file=../.env eidolon serve          # 后端 :8000

cd frontend && npm ci
BACKEND_URL=http://localhost:8000 npm run dev    # 前端 :3000
```

打开 http://localhost:3000，用「开发登录」按名字登录（用户不存在就创建）。开着开发登录又没设 `EIDOLON_ADMINS` 时所有人都是管理者，能进 `/admin` 后台。开发登录只能在本地用：配了 `EIDOLON_DOMAIN` 的公开部署会拒绝启动。

也可以用 Docker：`docker compose up -d --build`（同样先 `cp .env.example .env`）。

## 角色：API 优先

M0 没有角色编辑界面（通用壳在 M2），角色通过 API 创建和管理。登录拿到会话 cookie 后：

```sh
curl -X POST http://localhost:8000/api/characters \
  -H 'content-type: application/json' -H 'origin: http://localhost:3000' \
  -b '<会话 cookie>' \
  -d '{
    "name": "示例角色",
    "sheet": "# 人设\n你是……（分节的人设文本）",
    "intro": "一句话介绍",
    "greeting": "初次见面的问候",
    "user_address": "你",
    "language_mode": "single"
  }'
```

| 字段 | 说明 |
|---|---|
| `name` | 角色名（必填，≤100 字） |
| `sheet` | 人设文本（必填，≤100000 字，自由分节） |
| `intro` | 一句话介绍（≤2000 字） |
| `avatar_url` | 头像外链（http/https URL，平台不托管文件） |
| `greeting` | 问候语（≤10000 字） |
| `voice_id` | 用户自己的 Fish Audio 音色 ID（通话用，M3） |
| `color` | 印象色，`#rrggbb`（默认 `#64748b`） |
| `user_address` | 角色怎么称呼用户（默认「你」） |
| `language_mode` | `single`（默认，单语言）或 `bilingual`（`<ja><zh>` 双语） |
| `birthday` | `{"month": M, "day": D}` 或 `null` |
| `age` | 整数或 `null` |

`GET /api/characters` 列出自己的角色，`GET/PUT/DELETE /api/characters/{id}` 读、改、删。角色私有：只有创建者自己可见（无分享、无发现）。完整的接口和配置说明见 [`docs/configuration.md`](docs/configuration.md)。

## 自带密钥（BYOK）

用户在设置页填自己的 key：LLM（对话与记忆）、Fish Audio（语音合成）、Soniox 或阿里云百炼（语音识别）、生图。key 只存在浏览器里，回合/通话期间随请求带给后端、在进程内存里用完即弃，不落库、不进日志（ADR-0017）。部署者也可以在 `.env` 或后台配自己的 key 作兜底——不配就完全是零凭据平台。

## 部署

生产部署用 Docker Compose + Caddy + coturn（Linux，amd64），步骤见 [`docs/deploy.md`](docs/deploy.md)；配置项见 [`docs/configuration.md`](docs/configuration.md) 和 [`.env.example`](.env.example)。

## 开发规矩

- 后端测试：`cd backend && uv run pytest`；类型检查 `uv run pyright`；lint `uv run ruff check`。
- 前端测试：`cd frontend && npm test`；类型检查 `npm run typecheck`；shadcn 纪律 `sh scripts/check-discipline.sh`。
- 给 agent 的规矩见 [`AGENTS.md`](AGENTS.md)，实现票见 [`docs/agents/implementing.md`](docs/agents/implementing.md)。

## 许可证

[AGPL-3.0-or-later](LICENSE)。修改后通过网络提供服务必须向用户公开源码。
上游附带的第三方许可声明原样保留在 [`LICENSING.md`](LICENSING.md)；本 fork 已移除 Spine Runtimes 和原作素材。