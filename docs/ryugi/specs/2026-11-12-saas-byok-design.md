# Eidolon-SaaS（工作名）公益 BYOK 版改造设计

日期：2026-11-12　状态：待确认（第二轮，含实现者检查修订）
代码位置：fork `mitian233/eidolon-saas`，本地 worktree `/home/leonid/myproj/eidolon-saas`，分支 `saas/main`（起点 `5875cdff`，与上游 main 一致）。

## 1. 意图与缘由

把 eidolon-sc 的对话引擎改造成一个**通用角色托管服务**：任何用户都能自建角色人设、导入背景资料、与角色文字对话并通话。运行模式是**公益免费**：

- 平台不出一分第三方 API 费——所有模型、语音、向量化凭据由用户自带（BYOK）。
- 平台不碰素材版权——角色内容与素材全部来自用户，平台只存地址。
- 平台只提供：主机、数据库、通话媒体面（WebRTC 节点 + TURN 流量）。

先试「免费路线能不能走通」，跑通后再设计基础设施计费（通话分钟、存储）。上游仓库（Sallyn0225/eidolon-sc）的 283 版照常独立发展，本 fork 与它分道。

## 2. 目标 / 非目标 / 反目标

### 目标

1. 注册用户自建角色：人设文本、头像外链、问候语、音色（用户自己的 Fish Audio `voice_id`）。
2. 用户向角色导入背景资料（粘贴或上传文本），角色回答严格扎根在资料里（沿用上游「不许编造」的提示词纪律）。
3. 文字对话 + 通话全流程可用，长期记忆、资料召回、好感度照常工作。
4. 平台零凭据：后端不配置任何第三方 key 也能启动、能服务。
5. 源码公开（AGPL 义务），fork 公开仓库承载。

### 非目标

- 不做收费与计费系统（只保留通话分钟记录，为将来计费留数）。
- 不做多人群聊（上游 Milimil fork 的方向，不在本期）。
- 不做角色分享/广场/发现（v1 角色仅创建者自己可见，见 D13）。
- 不携带任何 283 内容：人设包、剧情库、Spine 立绘包、音色、酒吧素材、活动名一律不进本仓库与本服务。
- 不重写为 FaaS/serverless 函数形态；不做移动客户端。

### 反目标（出现即失败）

- 平台垫付任何用户的 API 费。
- 仓库、文档、界面里出现素材获取渠道（同步脚本、镜像地址、教程链接）。
- 上游 283 数据进入本服务的数据库、镜像或默认内容。

## 3. 约束

1. **AGPL-3.0-or-later**：修改后通过网络提供服务必须向用户公开源码；`LICENSE`、`LICENSING.md` 原样保留（含 Spine Runtimes 与 VA-11 HALL-A 的豁免声明文字，虽然酒吧不进本版）。
2. **素材三规矩**：不诱导（不提供获取渠道）；通知-删除（举报入口 + 后台能删能封）；外链优先（平台只存 URL，不托管素材文件）。
3. **BYOK 范围**：上游自带密钥覆盖 `llm/tts/stt/image`（`config.py:43`，ADR-0017，key 浏览器持有、回合期间内存持有）。本设计扩展到 `embedding/rerank`；判断模型走用户自带 LLM 的小请求（见 D14）；平台不再有任何后台模型。
4. **key 不落库**：不做服务端保存用户 key；浏览器持有 + 回合/通话期间内存持有，维持上游安全姿态（ADR-0017，`own_keys.py:9-12`）。
5. **运行形态**：容器化部署，不重写 serverless。架构三步：SQLite → Postgres；后台副作用沿用上游「回合后进程内任务」模式（见 D7）；通话可拆独立入口（见 D8）。
6. **上游跟进**：分支大改后不再 merge 上游 main；引擎级修复按需 cherry-pick。

## 4. 已定决策

| # | 决策 | 理由 |
|---|---|---|
| D1 | 公益免费先行，计费只留数据不建系统 | 先试免费路线能不能走通 |
| D2 | 平台零 key，BYOK 扩到 embedding/rerank | 成本和责任全在用户侧；硅基流动一把 key 同时覆盖向量化与重排。上游 `engine.py:49`「Retrieval is always the deployer's」这一行随之改写 |
| D3 | 没配判断模型时：照常聊天；资料召回只靠 `recall_story` 工具兜底（模型自己发起查询），不再有每回合的主动召回 | 保留上游的兜底机制，比「完全无召回」可用 |
| D4 | 记忆提炼、对话起标题沿用上游现状：回合结束后在**本进程内**、用该回合所用 key（用户自带 LLM 即用户的 key）继续做（`memory.py:33`、`own_keys.py:11`） | 这就是上游行为，SaaS 零改动即符合 BYOK |
| D5 | key 只在浏览器 + 回合/通话内存，不做服务端保存 | 维持 ADR-0017；公益目标用户（自带 key 群体）接受这个 UX |
| D6 | SQLite → Postgres：`store.py` 的存储层外层已全是 `async def`，SQLite 藏在 `Database` 包装层里线程执行；迁移 = 换 `Database` 内核（asyncpg，或沿用线程卸载 + psycopg），`Store` 接口与全部调用方不动 | 实现者检查确认的最低改动路径 |
| D7 | jobs 表只做记录、重试账目与统计；执行一律在 api 进程的回合后任务里。**不做独立 worker 进程** | 用户 key 只存在于浏览器与该回合的进程内存，任何跨进程执行者都拿不到 key；平台零凭据下没有可离线执行的作业。worker 角色推迟到将来出现不依赖用户凭据的作业（如计费统计） |
| D8 | 通话可拆独立入口（同一镜像，`EIDOLON_ROLE` 区分 api/calls），但 **v1 默认单进程承载全部角色**；拆分时通话节点是完整后端（直连 Postgres，自己写回合与通话记录），粘路由由入口层按节点标记实现；节点重启的通话按上游 `dropped` 语义结束 | aiortc 必须常驻；单机公益阶段没有拆分收益，先把拆分的口子留好 |
| D9 | 角色入库：`characters.toml`、`idol_id`/Spine 校验、人设包从启动路径摘除，换成数据库角色 + 适配层产出引擎所需的 `Character` 视图。上游 `Character`（`characters.py:148`）大量字段带默认值（`speakers/facts/idol_id/bar_*/photo_*`），适配层可按需填充 | SaaS 角色形状与 283 角色文件完全不同；上游那套留在上游 |
| D10 | 输出格式参数化：单语言为默认，`<ja><zh>` 双语模式作为角色可选。前端流式协议 `delta` 事件本就带 `lang` 字段（`api.ts:222`），单语言模式下段落只带文本 | 用户角色不必是日语偶像；引擎与前端渲染跟着角色设置走 |
| D11 | 素材外链优先，平台不托管文件 | 删除投诉时删一条 URL 即可；存储责任最小 |
| D12 | 玩法取舍：保留文字对话、通话、记忆、资料召回、好感度（机制通用）；**关闭**：礼物（目录与出处校验是 283 的）、照片（丹波鸟 tag 与画风配置是部署者概念）、主动搭话（调度作业跑在部署者 key 上，`reach_outs.py` 用 `config.lease()`）、生理期、酒吧、朋友圈、信、日程、天气、朗读、抽奖/重置卡 | 依赖部署者凭据或 283 目录的玩法在平台零 key 下无法运行，全部推迟到 M4 之后按需改造 |
| D13 | **角色私有**：v1 角色仅创建者自己可见，无分享、无发现。记忆归属用户，跨该用户自己的角色共享（沿用上游跨角色「听某某说」的转述语义，限定在同一用户的名下） | 保守起步；分享/广场牵扯音色归属（Fish Audio 音色绑账号）与内容审核，是独立功能 |
| D14 | 判断模型 = 用户自带 LLM 发的小请求（同一把 key，低推理档），设置里可整体关闭。关闭或未配时按上游语义：好感度/礼物停用（上游本就要求判断模型，`configuration.md:368`）、照片停用、通话表情走默认值、召回退到 D3 | 上游判断模型本就是「一次请求答三个是非题」的轻量用法；用用户的模型加一次小请求是最自然的等价物 |
| D15 | M0 必须包含「清除仓库 283 内容」提交：删除 `characters/`（人设、facts、头像、world.json）、`frontend/public/bar/` 图、酒吧代码页、corpus/mirror/stand/天气/greetings 的代码路径；`LICENSE` 与 `LICENSING.md` 保留 | 分支从上游 main 切出，283 内容全在工作树里；不清除则反目标第一条是空话 |

## 5. 里程碑

每个里程碑结束时系统必须可运行、测试全绿。模块名指上游对应文件（`backend/src/eidolon/`、`frontend/src/`）。

### M0 摘除领域绑定（后端里程碑，判据走 API）

| 改动 | 涉及 |
|---|---|
| 清除仓库 283 内容（D15） | `characters/`、`frontend/public/bar/`、相关前端页 |
| 角色入库：新表 `characters`（归属人、名称、人设分节文本、头像 URL、问候、音色设置、语言模式、可选生日/年龄），适配层产出引擎所需的 Character 视图；`characters.py` 的 toml 加载与 `idol_id` 强校验退场 | `characters.py`、`store.py`、`app.py` 启动路径 |
| 提示词去 283 化：关系称谓（制作人 → 角色自定义的「用户称谓」）、事务所/原作框架参数化；只改仍挂载的模块（`producer.py`、`judge.py`、`memory.py`、`emotion.py`、`engine.py`）；酒吧/信/朋友圈/日程/天气/照片/搭话模块不挂载不动 | 上述提示词模块 |
| 输出格式参数化：单语言默认，双语 `<ja><zh>` 为角色可选；流式 `delta` 协议与前端渲染跟随 | `engine.py`、前端消息渲染 |
| 启动路径摘除：corpus/mirror/stand/world/greetings/bar/weather 的路由、CLI 命令与启动要求下线；后端在零平台凭据下可启动 | `app.py`、`__main__.py`、`config.py` |

完成判据：`.env` 里没有任何第三方 key 时后端启动；通过 API 建一个纯文本角色，用用户自带 LLM key 完成流式文字回合（单语言模式）；pytest 全绿（被摘除功能的旧测试一并删除，不保留空壳）。前端在本里程碑不做界面改造，通用壳在 M2。

### M1 多租户与 BYOK 全量

| 改动 | 涉及 |
|---|---|
| SQLite → Postgres：换 `Database` 内核，`Store` 接口不动（D6） | `database.py`、`store.py` 调用方 |
| jobs 表：记录回合后的后台动作（记忆提炼、起标题），进程内执行、失败可见、可重试；不建独立 worker（D7） | `memory.py`、`titles.py`、`store.py` |
| BYOK 扩展：`Service` 与 `OWN_KEYS_PROXIED`（`config.py:43,68`）增加 embedding/rerank；向量化与重排调用改走用户 key（回合请求带来、导入请求带来）；判断模型改为用户 LLM 小请求，设置可关（D14） | `config.py`、`embedding.py`、`rerank.py`、`judge.py`、`assembly.py`、代理路由 |
| 后台配置页改为平台零 key 形态：平台凭据区块退场，限额与玩法开关保留 | `live_config.py`、admin 前端 |

完成判据：两个 api 实例容器共用一个 Postgres 并发服务文字回合无串数据；一个只带 LLM key + SiliconFlow key 的用户能获得带记忆（自带 key 提炼）、带 `recall_story` 工具召回的对话。

### M2 角色编辑与资料导入

| 改动 | 涉及 |
|---|---|
| 前端壳改造：下线 283 专属页，通用壳（角色列表、聊天、通话入口、设置与密钥页、角色编辑）；落地页换占位版 | `frontend/src/app` 整体 |
| 角色编辑界面：人设分节编辑、头像外链、问候语、音色（Fish Audio `voice_id`）、语言模式、判断模型开关 | 前端 + `characters` API |
| 通用文档导入：粘贴/上传文本 → 切块（沿用上游 1200 字符级切块思路）→ 用用户 embedding key 向量化 → 按角色归属存 `documents`/`passages` 表（表结构沿用 `episode_passages` 带 model/dimensions 标识的模式） | 新模块；复用 `story_import.py` 的切块与去重思路，不复用其格式解析 |
| 资料召回改造：`retrieval.py` 的资料来源从「剧情 + 角色资料 + 作品资料」改为「角色知识库」单一来源；召回、重排、阈值、`recall_story` 工具机制原样保留 | `retrieval.py`、`corpus.py` 的向量查找部分 |
| 素材外链：头像、（可选）立绘素材地址由用户提供；缺图时降级为纯头像/纯文字 | 前端降级逻辑、characters API |

完成判据：从注册 → 建角色 → 贴一份背景资料 → 带资料的对话全流程在浏览器走通；资料召回确实引用了导入内容且不编造。

### M3 通话

| 改动 | 涉及 |
|---|---|
| 通话角色拆分能力：`EIDOLON_ROLE=calls` 模式启动同一镜像；通话节点是完整后端，直连 Postgres 写回合与通话记录；粘路由由入口层实现；v1 默认部署仍为单进程（D8） | `call.py`、`__main__.py`、部署文档 |
| 音色：每角色用用户自己的 Fish Audio 账号与 `voice_id`（v1 角色私有，创建者即使用者，D13）；STT 走用户自己的 Soniox/百炼 key | `call.py`、自带密钥前端 |
| coturn 配置与分钟计量：compose 里 coturn 常驻；通话分钟落表（只记数，不建计费） | `docker-compose`、`call.py` |

完成判据：浏览器与后端完成一通用户音色的电话，识别与合成都走用户 key；通话限额与单通时长上限照旧生效。

### M4 公益上线

| 改动 |
|---|
| 服务条款页 + 素材/内容举报入口；管理员删除、封禁流程确认可用 |
| 用户数据导出与删除：导出复用上游数据包格式（ADR-0025，`store.py` 已有 `read_whole_conversations` 等读取路径） |
| 注册方式 invite 起步（`EIDOLON_REGISTRATION=invite`），跑稳后开放 |
| 公开源码确认（fork 公开）、部署文档重写、向上游 showcase 列表登记（`fork_showcase.yml` 模板，全年龄分级） |

## 6. 留给实现者的决定

- `characters`/`documents`/`passages`/`jobs` 的具体字段与索引；jobs 表的清理策略。
- 提示词模板的具体措辞与占位符命名；「用户称谓」的默认值；人设分节是自由文本还是固定节。
- 切块参数（目标块长、是否重叠）默认值；文档去重策略。
- 前端组件划分与页面结构。**实现前端前必读 `frontend/AGENTS.md`（shadcn 纪律）与 `DESIGN.md`**；本 fork 的目标用户不是 283 玩家，壳要重新设计而不是沿用。
- 测试组织：存储层换 Postgres 后的测试方案（本机 compose 或 testcontainers）。

## 7. 设计依据（对话与仓库材料）

- 许可与 fork 规矩：`LICENSING.md`（AGPL-3.0-or-later、Spine/VA 豁免）、`docs/community-forks.md`（fork 改名、素材不进公开仓库、showcase 登记）。
- BYOK 与 key 生命周期：`config.py`（`Service`、`OWN_KEYS_PROXIED`、免限额密钥、限额默认值）、`own_keys.py:9-12`（key 留浏览器；回合结束后的后台动作在进程内用所带 key 完成）、ADR-0017。
- 引擎可保留性的依据：`assembly.py`（记忆/召回的缺件降级）、`retrieval.py`（判断门控 + 并行预取）、`memory.py:33`（提炼用回合所用模型）与 supersedes 语义、`engine.py:49`（检索是部署者的——本设计改写）、ADR-0020（prompt 前缀缓存顺序）。
- 存储层形状：`store.py` 外层 `async def` + `Database` 包装（SQLite 线程执行），Postgres 迁移只动内核。
- 会话内定下的方向：公益模式与 BYOK 全量、素材 UGC 三规矩、容器化三步改造（Postgres/jobs 记录/通话可拆）、不重写 serverless、fork 与 worktree 位置。
