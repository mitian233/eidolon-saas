# M3：可拆通话节点

Status: ready-for-agent

用户于 2026-11-17 指示「推送，然后继续 M3」。既有提交已推至 fork/saas/main 的 54300b31。按 docs/ryugi/specs/2026-11-12-saas-byok-design.md 的 D5、D8 和 M3 执行。默认仍为单进程，不部署用户服务器、不调用收费服务、不开 PR。

## 行为

- EIDOLON_ROLE=all（默认）保留现有单进程运行方式；api 不处理 WebRTC offer；calls 是完整后端，自己读写共享 PostgreSQL。
- 拆分必须配置 PostgreSQL、固定节点列表 EIDOLON_CALL_NODES（JSON 对象，节点 ID → 内部 HTTP(S) 根地址）；calls 另配置 EIDOLON_CALL_NODE_ID，必须是列表中的节点。节点 ID 限字母数字下划线连字符，1–64 字符；地址不得带凭据、query、fragment 或非根路径。
- api 的 GET /api/ice-servers 仍校验登录、归属、已结束、冷却和自带服务名称；选取有效登记且负载较低的节点，额外返回 offerEndpoint=/api/call-nodes/{id}/offer。all 保持原返回。
- 浏览器用该 endpoint 发送首次 offer、重新协商 POST、候选 PATCH。前端只按配置表转发 /api/call-nodes/{id}/offer 至对应内部 /api/offer；其他路径或未知节点返回 404，不向客户端给出的地址转发。普通 API 仍转 api。所有节点继续按 session 和 pc_id 归属鉴别用户。
- 用户 key 只在首次 offer 请求与处理节点内存中；不写数据库、不放进控制信息、不重试至另一个节点。
- 节点登记含进程实例 ID 和短期有效时间。数据库写事务原子保证：正在拨号的用户不能再拨；每个用户的新通话替换其旧通话；所有节点共享 concurrent_calls 上限，自己的旧通话不占新通话额外名额，免限额 key 仍受并发上限。
- 只有新通话已通过原有 Admissions 后才要求旧通话挂断；拒绝的新请求不能挂断正在进行的旧通话。原节点结束并确认后才能接新通话。
- 删除角色、删除账号等待远端通话/拨号终止；封禁继续在节点轮询用户状态后挂断。退出登录保持现状：前端正常退出挂断，服务端撤 session。
- 文字回合引发的冷却或结束对话传至正在通话的远端；本地通话自己引起的冷却保留原有「答完当前回合再挂」语义。
- 节点过期不再分配，也不占名额；失去登记的进程结束本机通话，防止过期进程继续服务。重复存活节点 ID 不允许启动；重启无通话迁移，浏览器按 dropped 结束。数据库不保存可恢复服务 key。
- 登记到期保留未确认结束的通话记录。旧进程确已退出后，用同一个节点 ID 启动新进程会清掉该 ID 的旧记录，使用户可以重拨。节点 ID 不可在旧进程还活着时重用。
- 当前角色以数据库读取为准，不使用另一个进程启动时的旧角色视图。拆分节点在处理新请求前读取共享运行设置。
- 原有 TURN 签发、通话时长、calls 记录、用户 key 选择、单通分钟和回合上限继续生效。提供单机固定节点部署示例，保留 coturn 的同机 peer 限制；不声称跨机器 TURN 或真实付费声音已试过。

## Testing Decisions

- 数据库协调：真实 Database、独立连接，database_target 的 SQLite/PostgreSQL 参数；测试竞争、删除等待、过期实例、失败或取消释放。生产拆分仅允许 PostgreSQL。
- 后端：两个 calls 后端及一个 api 后端共享临时 PostgreSQL，真实会话、角色 API 与 WebRTC 回环；仅外部模型、识别、合成为现有 fakes。不替换 Calls/Admissions/数据库协调。
- 前端：沿用 Vitest，真实 Request/Response，只有外部 fetch 替换；既有 key 生命周期测试扩展为固定节点 endpoint。需要浏览器时使用假麦克风和本机服务，不读取真实 key。
- 永久测试覆盖用户可观察的竞争、归属、时序和失败，不对源码文字或简单字段转发另写测试。
- 本机只跑相关测试和 affected-tests；构建、浏览器操作串行。正常 Git hooks。只命名暂存自己的文件；不提交或清理既有 .ryugi。

## 工作分工接口

CallNodes(database, node_ids: tuple[str, ...], node_id: str | None, clock: Clock) 位于 backend/src/eidolon/call_nodes.py。api 的 node_id=None；每实例生成独立随机 instance_id。

- start(): calls 登记自身，api 无需登记；重复有效 ID 或未知节点拒绝。
- choose(user_id, maximum: int | None) -> str: 拒绝正在拨号/容量满，返回列表中有效且较空节点。
- reserve(user_id, character_id, conversation_id, maximum) -> str: 在本节点创建 placing 记录，事务内执行全球准入。取消也释放已提交记录。
- activated(call_id) -> bool: placing 改 live，已被停止或失去登记返回 False。
- release(call_id): 删除仅本进程拥有的记录；幂等。
- stop(user_id, reason: CallEndReason, *, character_id=None, excluding=None): 要求匹配通话结束，等待记录删除；excluding 用于新通话替换旧通话。超时明确失败，不先删业务数据。
- cool(user_id, character_id, until: datetime), end(conversation_id, why: EndsFor): 向其他进程的通话发布通知；自身由原有同步回调处理。
- heartbeat() -> list[Control]: 续期并读取本进程控制，Control 含 call_id、stop_reason、cooldown_until、ended_for；冷却/结束通知读取后移除，stop 保留直到通话释放。过期/失去登记拒绝续期。
- count() -> int: 有效通话的不同用户数。
- aclose(): 仅删除本进程登记及记录，须先结束本机通话。

异常：CapacityReached、AlreadyPlacing、NodeUnavailable（各自稳定简短提示），分别由应用映射 503/calls_busy、409、503。数据库表不含任何 key、端点凭据或请求正文。call_nodes 仅共享节点状态归 NOT_USER_DATA；active_calls 按 user_id、conversation_id、character_id 删除。

## Comments

上一轮 aioice 收尾错误与 Next.js 升级提醒已存在独立票；用户补充要求留到 M3 实现结束后再测试和处理，本轮实现阶段不穿插修补。
