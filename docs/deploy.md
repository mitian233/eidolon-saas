# 部署

Eidolon-SaaS 是公益 BYOK 服务。用户在设置页自带模型、语音和向量化密钥。部署者提供主机、数据库、通话网络和网站的 OAuth 登录。
配置项的完整说明见 [configuration.md](configuration.md) 和仓库根目录的 [`.env.example`](../.env.example)。

## 准备

- 一台 Linux 服务器（有公网 IPv4）和一个域名（A 记录指向服务器）。国内服务器要求域名已备案，否则 80、443 会被拦截。
- Docker 和 Docker Compose 插件。在部署机上从本仓库构建前后端，Caddy 和 coturn 使用各自的公开镜像。
- 防火墙放行：80、443（TCP，Caddy），3478（TCP+UDP，coturn），49160–49259（UDP，coturn 中继，可用 `EIDOLON_TURN_MIN_PORT`/`EIDOLON_TURN_MAX_PORT` 改）。
- 取本仓库的 `saas/main` 或本次部署选定的提交。两份生产 Compose 均可从这份代码构建。

## 本地开发

不用 Docker：

```sh
cp .env.example .env     # 默认 EIDOLON_DEV_LOGIN=1，第三方 key 都不用填
# 终端一，从仓库根目录启动后端（:8000）
cd backend && uv sync
uv run --env-file=../.env eidolon serve
# 终端二，从仓库根目录启动前端（:3000）
cd frontend && npm ci
BACKEND_URL=http://localhost:8000 npm run dev
```

用 Docker：`cp .env.example .env && docker compose up -d --build`，打开 http://localhost:3000。这里的 Caddy 使用 HTTP，把公开举报和其他页面分别转给后端和前端。
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
| `EIDOLON_DEV_LOGIN` | 新建 `.env` 后改为 `0` |
| `EIDOLON_DOMAIN` | 域名，Caddy 用它自动申请 HTTPS 证书；后端据此拼 OAuth 回调、只接受这个网站的请求 |
| `EIDOLON_PUBLIC_IP` | 服务器公网 IPv4，coturn 只把语音中继到这台服务器 |
| `EIDOLON_TURN_SECRET` | `openssl rand -hex 32`，后端和 coturn 共用，给浏览器签发会过期的 TURN 凭据 |
| `EIDOLON_SECRET_KEY` | 用 `openssl rand -hex 32` 生成，用于封禁名单等操作。填好后保持固定 |
| GitHub 或 Google 的 OAuth | 至少一家，见下节 |

**公开服务建议填写** `EIDOLON_REGISTRATION=invite`、`EIDOLON_ADMINS` 和 `EIDOLON_CONTACT`。联系信息显示在举报页、条款页和部分登录失败提示中。`NEXT_PUBLIC_EIDOLON_SOURCE_URL` 指定页脚所链接的公开源码，应指向运行版本对应的源码。修改此地址后重新构建前端。公网地址不在本机网卡上的 1:1 NAT 云主机可填 `EIDOLON_PRIVATE_IP`。

四个服务都用 host 网络：前端和后端只监听 127.0.0.1，公网只开 Caddy 和 coturn。第一次启动 Caddy 申请证书要稍等；后端启动失败时 `docker compose -f docker-compose.prod.yml logs backend` 看原因。

公开举报的 `POST /api/reports` 由 Caddy 直接转给后端，后端按 Caddy 提供的客户端地址限频。更换入口代理时，保留这条转发，让后端只信任已知代理提供的客户端地址。

### 配置 OAuth 应用

登录走后端：FastAPI 处理回调，会话存数据库，httpOnly cookie 保持登录，前端只是同源代理。

- GitHub：Settings → Developer settings → OAuth Apps → New OAuth App。回调地址 `https://<域名>/api/auth/github/callback`。
- Google：Cloud Console → APIs & Services → Credentials → OAuth client ID（Web application）。回调地址 `https://<域名>/api/auth/google/callback`。

把 client id/secret 填进 `.env` 的 `GITHUB_CLIENT_ID`/`GITHUB_CLIENT_SECRET` 或 `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET`。也可以用交互式脚本 `sh scripts/setup-oauth.sh` 引导填写。

### 管理者与邀请注册

已知管理者的 OAuth 标识时，直接填 `EIDOLON_ADMINS`（逗号分隔的 `provider:subject`，如 `github:12345`）。在 `invite` 模式下，名单中的身份可以直接注册，已注册的用户照常登录。

如果还不知道自己的标识，先限制测试站的访问范围。空库未设名单时，允许第一位用户登录取得标识。用自己的 OAuth 登录一次，再在服务器上运行：

```sh
docker compose -f docker-compose.prod.yml exec backend eidolon user list
```

把登录方式后面括号里的 `provider:subject` 填进 `EIDOLON_ADMINS`。执行 `docker compose -f docker-compose.prod.yml up -d` 让容器重新读取 `.env`。拆分部署时沿用启动时的两个 `-f` 参数。确认管理者能从设置页进后台后，再开放站点访问。

在后台「配置 → 注册」生成、查看或删除邀请链接。过期、用尽或删除的链接不能用于新注册。后台修改的注册方式等运营设置优先于 `.env`，可在后台恢复为 `.env` 的值。`eidolon doctor` 会提示 `.env` 中设置了 `invite` 却缺少管理者。

### 举报和处置

页脚的举报表单向访客和登录用户开放。管理者在「举报」列表查看、处理并记录结果，如需封禁、解封或删除账号，使用「用户」页。命令行也可列出用户、封禁、解封及查看用量（`eidolon user list/ban/unban/usage`）。

### 选择数据库

默认用数据卷中的 SQLite。单进程也可以使用 PostgreSQL。在 `.env` 设置 `DATABASE_URL=postgresql://…` 连接已运行的 PostgreSQL。生产容器使用 host 网络，同机 PostgreSQL 用宿主机可达的地址。切换连接地址时需要另行搬运旧数据。

从旧 `.env.example` 复制过配置的部署，如果仍有空的 `EIDOLON_DATABASE_PATH=`，请删除这一行，让容器使用数据卷中的默认路径。

## 可选：同机拆分通话节点

默认 `EIDOLON_ROLE=all`，一个后端进程处理文字与通话。需要独立通话进程时，先准备 PostgreSQL，在 `.env` 的 `DATABASE_URL` 填共享地址，然后运行：

```sh
docker compose -f docker-compose.prod.yml -f docker-compose.calls.yml up -d --build
```

这个示例让 `backend` 作为 api（127.0.0.1:8000），两个通话进程监听 8101、8102。前端与后端使用文件内相同的固定节点表。所有进程读取同一个 PostgreSQL；不要给它们各配一个 SQLite 文件。切换数据库不会搬运已有 SQLite 数据，搬运需单独处理。

调用准备接口时会选出有效且较空的通话节点；浏览器把 offer、重协商和候选地址发往本站的该节点路径，前端只向配置表里的地址转发。节点标记不能替代登录：每次仍按共享会话和连接所属用户判断。节点不可达时本次拨号失败，不会把携带 key 的请求重发给另一个节点。

每个通话进程使用不同的 `EIDOLON_CALL_NODE_ID`。数据库登记有效期为 15 秒，正常运行约每 0.5 秒续期。重复运行同一个有效 ID 会启动失败。节点失联后停止接新通话，浏览器显示连接中断。进程失去登记或无法访问数据库时会结束本机通话。

新通话替换旧通话、删除角色或账号时，会等原节点确认结束。等待超时会返回失败并保留业务数据。仅登记到期时，旧通话不再占并发名额，但仍需确认结束。进程被强制终止后，先确认旧进程已退出，再用相同节点 ID 启动一次。新进程在登记时清掉这个 ID 遗留的通话记录，相关用户即可重拨。

前端、API 和通话进程的节点表应同时更新，并使用相同的站点域名、会话数据库与运营设置。后台改过的设置会在拆分进程处理下一次请求前读取。退出登录沿用前端挂断、服务端撤销会话；这不新增服务端立即强制挂断的承诺。

示例适用于同一台 Linux 主机，沿用生产 Compose 的 host 网络及 coturn 的同机地址限制。跨机部署需要另行配置防火墙、TURN 中继允许的地址和 ICE 公网地址。用户的模型和语音密钥随首次 offer 到所选节点内存，节点重启后需要重新拨号。

## 零凭据语义

公益部署把部署者的模型、语音等可选密钥留空，文字和语音按用户填写的密钥调用。没填语言模型密钥的用户会收到去设置页填写的提示。记忆提炼和资料召回需要用户填写向量化端点。重排可选，判断功能开启后使用用户自己的语言模型。部署者也可显式在 `.env` 配置对话和语音兜底，费用由部署者承担。

## 备份

内置备份与恢复仅适用于 SQLite；PostgreSQL 请使用 `pg_dump` 与 age 加密备份。

### SQLite

SQLite 可以每天备份到私有 S3 兼容存储桶，压缩并用 age 公钥加密（ADR-0012）。

1. 建一个**私有**存储桶，配好 `EIDOLON_BACKUP_S3_*`（写法见 `.env.example`）。
2. 本机 `age-keygen` 生成密钥对：公钥（`age1…`）填 `EIDOLON_BACKUP_AGE_RECIPIENT`，私钥离线保存——丢了所有备份都解不开。
3. 手动跑一次 `deploy/db-backup.sh`，看 `logs/db-backup.log` 最后一行「结束：退出码 0」。
4. 装 cron（root 或仓库所属用户）：

```cron
20 3 * * * /path/to/repo/deploy/db-backup.sh --cron
```

保留期默认 30 天（`EIDOLON_BACKUP_KEEP_DAYS`，只能调短——隐私政策承诺删除的数据最多 30 天后从备份消失）。可选 `EIDOLON_BACKUP_PING_URL`（healthchecks.io 心跳）、`EIDOLON_BACKUP_WARN_GB`（空间提醒）。后台看板也能发起备份、看备份记录。

#### 从备份恢复

在自己电脑上用 age 私钥解密备份（`age -d -i key.txt eidolon-<时间>.db.gz.age > eidolon.db.gz`），把解密后的文件传到服务器，然后运行：

```sh
deploy/db-restore.sh eidolon.db.gz
```

脚本先检查备份（完整性、是不是本项目的库），不通过什么都不动；通过后先备份现在的库，再停后端、替换数据卷里的库、启动后端。新服务器上恢复加 `--no-backup`（库是空的，备份可能还没配）。

#### 换服务器

新服务器装好 Docker、克隆仓库、填好 `.env`（存储桶和 age 公钥照旧），`up -d --build` 起一次空库，再 `deploy/db-restore.sh <解密后的备份> --no-backup`。域名 A 记录切到新服务器，Caddy 自动申请新证书。

### PostgreSQL

在备份机安装 PostgreSQL 客户端、gzip 和 age。客户端版本至少与源库的主版本相同。在 `~/.pg_service.conf` 里设 `eidolon-backup`，填源库的 `host`、`port`、`dbname` 和 `user`，密码放在权限为 `0600` 的 `~/.pgpass`。用 `age-keygen` 生成密钥对，把公钥设为 `EIDOLON_BACKUP_AGE_RECIPIENT`，私钥离线保存。

把以下命令放进每天运行的 Bash 脚本，由 cron 或 systemd timer 调用。备份直接压缩加密，成功后才公布最终文件名。

```bash
set -euo pipefail
umask 077
: "${EIDOLON_BACKUP_AGE_RECIPIENT:?请设置 age 公钥}"
export PGSERVICE=eidolon-backup
backup_dir=/var/lib/eidolon/pg-backups
mkdir -p -- "$backup_dir"
archive="$backup_dir/eidolon-pg-$(date -u +%Y%m%dT%H%M%SZ).dump.gz.age"
temporary=$(mktemp "$backup_dir/.eidolon-pg-XXXXXXXX")
trap 'rm -f -- "$temporary"' EXIT
pg_dump --format=custom --compress=0 | gzip -c \
  | age -r "$EIDOLON_BACKUP_AGE_RECIPIENT" > "$temporary"
mv -- "$temporary" "$archive"
```

每份备份最多保留 30 天。定时清理单独运行，使备份当天失败时过期文件仍会删除。异地副本也应设同样的到期规则。

```sh
find /var/lib/eidolon/pg-backups -maxdepth 1 -type f \
  -name 'eidolon-pg-*.dump.gz.age' ! -newermt '30 days ago' -delete
```

恢复到一个新建的空库。下例中 `eidolon-admin` 是有建库权限的连接配置，`eidolon-restore` 指向新库 `eidolon_restored`，以库的所有者 `eidolon` 登录。用离线保存的 age 私钥解密后再导入。

```bash
set -euo pipefail
umask 077
temporary=$(mktemp -d)
trap 'rm -rf -- "$temporary"' EXIT
age -d -i /path/to/age-key.txt /path/to/eidolon-pg-YYYYMMDDTHHMMSSZ.dump.gz.age \
  | gzip -dc > "$temporary/eidolon.dump"
PGSERVICE=eidolon-admin createdb --owner=eidolon eidolon_restored
pg_restore --dbname='service=eidolon-restore' \
  --single-transaction --no-owner --no-privileges "$temporary/eidolon.dump"
```

确认新库可以运行后，停掉 API 和通话进程，将各进程的 `DATABASE_URL` 改为新库，再重新启动。

## 网络和代理

服务器连不上某些服务商（OpenAI、Soniox 等）时，让这些服务经代理连，其余直连：

```env
EIDOLON_PROXY_URL=http://127.0.0.1:7890
EIDOLON_PROXY_SERVICES=chat_llm,judge,tts,stt
```

可按服务指定代理；完整列表见 [`.env.example`](../.env.example)。自带 LLM 等端点只在地址属于已知服务商时才走代理。后端服务调用使用上述变量。生产使用 host 网络，宿主机上的代理可以写 `127.0.0.1`。

## 升级

```sh
git pull
docker compose -f docker-compose.prod.yml up -d --build
```

拆分部署时沿用启动时的两个 `-f` 参数。升级前先备份数据库。后端在启动时执行数据库迁移，容器重建会继续使用原来的数据卷或 PostgreSQL。需要回到旧版本时，用原部署提交重建，并按相应数据库的流程恢复升级前的备份。

## 排障

```sh
docker compose -f docker-compose.prod.yml exec backend eidolon doctor
```

按 `.env` 逐项试一次各服务（经代理和直连），说明哪里不对、该怎么改；`--json` 给 agent 读。后端不用停。常见：

- 后端起不来：`logs backend` 看第一行错误。缺必填变量、key 调不通、模型不支持流式/工具调用都会写明。
- 通话接通没声音：Fish Audio 直连不通时给 `tts` 配代理（见「网络和代理」）。
- 用户回合被拒「没有配置对话模型」：平台零凭据且用户没带 LLM key——让用户在设置页填自己的 key。