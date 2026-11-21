# Eidolon-SaaS

Eidolon-SaaS 是公益免费的角色托管服务。你可以创建私有角色，导入背景资料，和角色文字对话或实时语音通话。角色和资料只有创建者能访问，头像使用你提供的网址。

模型和语音费用由用户自带密钥承担（BYOK）。公益部署只需提供主机、数据库和通话网络。项目源自 [Eidolon-SC](https://github.com/Sallyn0225/eidolon-sc)，本分支随应用交付的是通用引擎与界面，角色由用户创建。引擎级修复按需从上游引入。

## 已实现的功能

| 里程碑 | 已实现 |
|---|---|
| M0 | 角色入库，默认单语言输出，可选日中双语。后端可在平台没有模型和语音密钥时启动。 |
| M1 | SQLite 和 PostgreSQL、自带向量化与可选重排、用自带语言模型判断，回合结束后在同一进程提炼记忆和起标题。 |
| M2 | 角色管理与编辑，在资料区粘贴文本或上传文本文件，按角色查找已导入资料。 |
| M3 | 用户自带音色与识别密钥的 WebRTC 通话，记录通话分钟。默认一个后端进程，可选同机拆分 API 与通话进程。 |
| M4 | 使用条款与隐私政策、内容举报与后台处置、数据包和自助删除、邀请注册与本地构建部署。 |

在[设计文档](docs/ryugi/specs/2026-11-12-saas-byok-design.md)查看各阶段设计和仍需在真实服务上试用的项目。

## 本地开发

需要 [uv](https://docs.astral.sh/uv/) 和 Node.js 22。

```sh
cp .env.example .env        # 默认开着开发登录（EIDOLON_DEV_LOGIN=1），第三方 key 一个都不用填

# 终端一，从仓库根目录启动后端（:8000）
cd backend && uv sync
uv run --env-file=../.env eidolon serve

# 终端二，从仓库根目录启动前端（:3000）
cd frontend && npm ci
BACKEND_URL=http://localhost:8000 npm run dev
```

打开 http://localhost:3000，用「开发登录」按名字登录（用户不存在就创建）。开着开发登录又没设 `EIDOLON_ADMINS` 时所有人都是管理者，能进 `/admin` 后台。开发登录只能在本地用：配了 `EIDOLON_DOMAIN` 的公开部署会拒绝启动。

也可以用 Docker：`docker compose up -d --build`（同样先 `cp .env.example .env`）。

## 角色和资料

登录后在角色目录创建、编辑或删除角色。可填写人设、问候语、头像网址、输出语言和自己的 Fish Audio 音色 ID。在角色编辑页的「资料」区粘贴文本或上传文本文件，使用自己的向量化服务处理资料。对话时，角色可以查找你为它导入的背景资料。长期记忆归属用户，可以在自己的角色之间使用。

接口和字段见[配置说明](docs/configuration.md#角色)。

## 自带密钥（BYOK）

在设置页「自带密钥」填写语言模型、Fish Audio、Soniox 或阿里云百炼、OpenAI 兼容向量化，以及可选的 SiliconFlow 格式重排。判断功能可单独开启，使用自己的语言模型。密钥留在浏览器，相关请求发出后，只在本次回合、通话及回合后任务的进程内存中使用。生图密钥配置仍在，当前版本未开放照片玩法。

## 部署

按[部署说明](docs/deploy.md)在 Linux 主机上用 Docker Compose 从本仓库构建。Caddy 提供 HTTPS，coturn 转发通话媒体。默认一个后端进程，可选 SQLite 或 PostgreSQL。拆分通话时，API 与通话进程共用 PostgreSQL。

公开服务建议从 `EIDOLON_REGISTRATION=invite` 起步。配置管理者后，在后台生成邀请链接。模型和语音凭据留空即可按公益方式运行。域名、OAuth、公开联系信息和源码链接的配置见[配置说明](docs/configuration.md)。

## 举报和个人数据

访客和登录用户都可以通过页脚举报。管理者在后台「举报」查看和记录处理结果，在「用户」封禁、解封或删除用户。

设置页「数据包」支持导出和导入对话、记忆与档案。通过「删除我的全部数据」可删除服务上的角色、导入资料、对话等关联数据，并让所有设备退出登录。删除成功后会清除当前浏览器中的自带密钥。

## 开发规矩

- 后端测试：`cd backend && uv run pytest`；类型检查 `uv run pyright`；lint `uv run ruff check`。
- 前端测试：`cd frontend && npm test`；类型检查 `npm run typecheck`；shadcn 纪律 `sh scripts/check-discipline.sh`。
- 给 agent 的规矩见 [`AGENTS.md`](AGENTS.md)，实现票见 [`docs/agents/implementing.md`](docs/agents/implementing.md)。

## 许可证

[AGPL-3.0-or-later](LICENSE)。修改后通过网络提供服务时，应向用户提供运行版本对应的源码，站点页脚提供入口。第三方许可与上游的许可声明见 [LICENSING.md](LICENSING.md)。