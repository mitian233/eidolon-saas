# 部署

Eidolon-SaaS 是公益 BYOK 服务：平台零凭据也能启动和服务，模型费用由用户自带 key 承担。
配置项的完整说明见 [configuration.md](configuration.md) 和仓库根目录的 [`.env.example`](../.env.example)。

## 准备

- 一台 Linux 服务器（有公网 IPv4）和一个域名（A 记录指向服务器）。国内服务器要求域名已备案，否则 80、443 会被拦截。
- Docker 和 Docker Compose。镜像只有 linux/amd64；arm64 服务器用 `--build` 在本机构建。
- 防火墙放行：80、443（TCP，Caddy），3478（TCP+UDP，coturn），49160–49259（UDP，coturn 中继，可用 `EIDOLON_TURN_MIN_PORT`/`EIDOLON_TURN_MAX_PORT` 改）。
- 本 fork 的镜像尚未发布到 GHCR（M4 做）：`docker-compose.prod.yml` 里的镜像名仍是上游的，**部署本 fork 要用 `up -d --build` 在本机构建**，不要 `pull` 上游镜像。

## 本地开发

不用 Docker：

```sh
cp .env.example .env     # 默认 EIDOLON_DEV_LOGIN=1，第三方 key 都不用填
cd backend && uv sync
uv run --env-file=../.env eidolon serve        # :8000
cd frontend && npm ci
BACKEND_URL=http://localhost:8000 npm run dev  # :3000
```

用 Docker：`cp .env.example .env && docker compose up -d --build`，打开 http://localhost:3000。
开发登录按名字直接登录；配了 `EIDOLON_DOMAIN` 时开发登录会被拒绝启动（它让任何人冒充任何用户）。

## 公网部署

```sh
cp .env.example .env
nano .env    # 至少填下面这几项
docker compose -f docker-compose.prod.yml up -d --build
```

`.env` 必填：

| 变量 | 说明 |
|---|---|
| `EIDOLON_DOMAIN` | 域名，Caddy 用它自动申请 HTTPS 证书；后端据此拼 OAuth 回调、只接受这个网站的请求 |
| `EIDOLON_PUBLIC_IP` | 服务器公网 IPv4，coturn 只把语音中继到这台服务器 |
| `EIDOLON_TURN_SECRET` | `openssl rand -hex 32`，后端和 coturn 共用，给浏览器签发会过期的 TURN 凭据 |
| `EIDOLON_SECRET_KEY` | `openssl rand -hex 32`，加密后台保存的 key。**填了之后不要更换** |
| GitHub 或 Google 的 OAuth | 至少一家，见下节 |

可选：`EIDOLON_PRIVATE_IP`（公网地址不在网卡上的 1:1 NAT 云主机）、`EIDOLON_ADMINS`（管理者名单）、`EIDOLON_CONTACT`、`EIDOLON_REGISTRATION=invite`（只让受邀的人注册，M4 起步推荐）。

四个服务都用 host 网络：前端和后端只监听 127.0.0.1，公网只开 Caddy 和 coturn。第一次启动 Caddy 申请证书要稍等；后端启动失败时 `docker compose -f docker-compose.prod.yml logs backend` 看原因。

### 配置 OAuth 应用

登录走后端：FastAPI 处理回调，会话存数据库，httpOnly cookie 保持登录，前端只是同源代理。

- GitHub：Settings → Developer settings → OAuth Apps → New OAuth App。回调地址 `https://<域名>/api/auth/github/callback`。
- Google：Cloud Console → APIs & Services → Credentials → OAuth client ID（Web application）。回调地址 `https://<域名>/api/auth/google/callback`。

把 client id/secret 填进 `.env` 的 `GITHUB_CLIENT_ID`/`GITHUB_CLIENT_SECRET` 或 `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET`。也可以用交互式脚本 `sh scripts/setup-oauth.sh` 引导填写。

### 管理者

先在网站上登录一次，再在服务器上查自己的身份标识：

```sh
docker compose -f docker-compose.prod.yml exec backend eidolon user list
```

每个登录方式后面括号里的 `provider:subject` 就是。填进 `.env` 的 `EIDOLON_ADMINS`（逗号分隔），重启后端。管理者从设置页进 `/admin` 后台：看板、配置、用户管理（封禁/解封）。后台改过的配置优先于 `.env`；启动日志会列出哪些项被后台覆盖。命令行同样能管理用户：`eidolon user list/ban/unban/usage`。

## 零凭据语义

平台不配任何第三方 key 也能启动：每个回合用用户自带的 LLM key；用户没带 key 时，文字回合被拒绝并提示去设置里填。部署者也可以在 `.env` 或后台配自己的 key 作兜底（用户没带时用部署者的，费用部署者出）。向量化/重排/判断模型配了才有主动资料召回和记忆；没配时角色只凭人设回复，召回退到模型自己发起的 `recall_story` 工具。

## 备份

数据库每天备份到私有的 S3 兼容存储桶（推荐 Cloudflare R2），压缩、用 age 公钥加密（ADR-0012）。

1. 建一个**私有**存储桶，配好 `EIDOLON_BACKUP_S3_*`（写法见 `.env.example`）。
2. 本机 `age-keygen` 生成密钥对：公钥（`age1…`）填 `EIDOLON_BACKUP_AGE_RECIPIENT`，私钥离线保存——丢了所有备份都解不开。
3. 手动跑一次 `deploy/db-backup.sh`，看 `logs/db-backup.log` 最后一行「结束：退出码 0」。
4. 装 cron（root 或仓库所属用户）：

```cron
20 3 * * * /path/to/repo/deploy/db-backup.sh --cron
```

保留期默认 30 天（`EIDOLON_BACKUP_KEEP_DAYS`，只能调短——隐私政策承诺删除的数据最多 30 天后从备份消失）。可选 `EIDOLON_BACKUP_PING_URL`（healthchecks.io 心跳）、`EIDOLON_BACKUP_WARN_GB`（空间提醒）。后台看板也能发起备份、看备份记录。

### 从备份恢复

在自己电脑上用 age 私钥解密备份（`age -d -i key.txt eidolon-<时间>.db.gz > eidolon.db`），传到服务器，然后：

```sh
deploy/db-restore.sh eidolon.db
```

脚本先检查备份（完整性、是不是本项目的库），不通过什么都不动；通过后先备份现在的库，再停后端、替换数据卷里的库、启动后端。新服务器上恢复加 `--no-backup`（库是空的，备份可能还没配）。

### 换服务器

新服务器装好 Docker、克隆仓库、填好 `.env`（存储桶和 age 公钥照旧），`up -d --build` 起一次空库，再 `deploy/db-restore.sh <解密后的备份> --no-backup`。域名 A 记录切到新服务器，Caddy 自动申请新证书。

## 网络和代理

服务器连不上某些服务商（OpenAI、Soniox 等）时，让这些服务经代理连，其余直连：

```env
EIDOLON_PROXY_URL=http://127.0.0.1:7890
EIDOLON_PROXY_SERVICES=chat_llm,judge,tts,stt
```

可走代理的服务：`chat_llm`、`memory_llm`、`judge`、`embedding`、`rerank`、`tts`、`stt`、`image`、`gpt_image`，用户自带的 `own_llm`、`own_tts`、`own_stt`、`own_image`，或 `all`。自带 LLM 只在地址属于已知服务商时才走代理。`HTTPS_PROXY` 等环境变量对后端的服务调用不起作用。生产用 host 网络，宿主机上的代理直接写 `127.0.0.1`。后台「网络」标签也能改。

## 升级

```sh
git pull
docker compose -f docker-compose.prod.yml up -d --build
```

数据库迁移在启动时自动做。数据都在 `eidolon-data` 卷里，重建容器不丢。升级出问题：先 `deploy/db-backup.sh` 备份，再按「从备份恢复」回到旧库；镜像版本可用 `EIDOLON_IMAGE_TAG` 固定（fork 镜像发布后适用）。

## 排障

```sh
docker compose -f docker-compose.prod.yml exec backend eidolon doctor
```

按 `.env` 逐项试一次各服务（经代理和直连），说明哪里不对、该怎么改；`--json` 给 agent 读。后端不用停。常见：

- 后端起不来：`logs backend` 看第一行错误。缺必填变量、key 调不通、模型不支持流式/工具调用都会写明。
- 通话接通没声音：Fish Audio 直连不通时给 `tts` 配代理（见「网络和代理」）。
- 用户回合被拒「没有配置对话模型」：平台零凭据且用户没带 LLM key——让用户在设置页填自己的 key。