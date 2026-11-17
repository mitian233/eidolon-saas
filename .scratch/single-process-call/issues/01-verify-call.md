# 验证单进程通话

Status: done

## 验收项

- [x] 使用已有非收费测试验证自建角色 voice_id 传至 Fish Audio 请求，以及 Soniox/百炼自带 key 的选择。
- [x] 验证用户隔离、通话时长写入、限额与自带 key 免限额，以及独立的单通时长上限；先跑已有覆盖，只补缺口。
- [x] 本地构建版使用 Playwright、假麦克风和模拟通话验证删除外壳持有的通话角色后，连接结束时通话层、通话条和导航 inert 清除，覆盖拨号、展开和收起状态。
- [x] 同样验证与 A 通话时进入 B 编辑页，返回 B 对话需确认挂断；取消后仍在 B 编辑页且 A 通话继续；返回 A 不误问。
- [x] 记录模拟 UI 与真实语音端到端证据的区别；真实 STT/TTS、音色、模型行为和公网头像留待人工或公网复验，不更改地址安全检查。
- [x] 按仓库规则运行受影响检查；关闭本次服务和临时数据库并检查端口，记录命令、计数与缺口。

## Comments

### 实际验收记录（未完成）

- `cd backend && UV_NO_SYNC=1 uv run pytest -q tests/test_call.py tests/test_call_outcome.py tests/test_own_keys.py tests/test_usage.py`：62 passed。覆盖假语音服务的 WebRTC 回环、音色选择、单通上限、限额和密钥选择；这些测试主要使用 SQLite。
- `cd backend && UV_NO_SYNC=1 uv run pytest -q tests/test_own_speech_keys.py tests/test_exempting_keys.py tests/test_call_stats.py tests/test_call_records.py tests/test_concurrent_calls.py`：42 passed。覆盖自带密钥、免限额、通话记录及隔离的既有测试。
- 包含 `tests/test_fish_segments.py` 的组合运行在 60 秒超时，出现 53 个进度点但无最终结果，不计通过。角色 voice_id 到 Fish 实际请求的完整链路仍未确认。
- `cd backend && UV_NO_SYNC=1 uv run pytest -q 'tests/test_database.py::test_two_concurrent_connections_see_each_others_commits[postgres]'`：1 passed，证明 pgserver fixture 可用，并非通话 Postgres 验收。
- `cd frontend && CI=1 npm run build`：通过；普通 `npm run build` 因 Next.js 交互升级提示超时。系统 Chromium 能打开本地构建版登录页；两项指定的模拟通话浏览器验收尚未进行。
- `sh scripts/affected-tests.sh 0a2b3c41`：通过。未修改产品代码；`apply_patch` 命令在本环境不可用，若发现产品缺陷不得绕过此限制修改。
- 尚需补足 Postgres 通话测试缺口、Fish 请求链路与两项浏览器验收。真实语音、外部头像和模型行为仍需人工或公网验证；无网络安全规则变更。

### 正式数据库通话测试（2026-11-17）

- 本次只补正式测试，不修改产品实现。开工提交为 `9016a7276d304b4d1808dd2a7608c9aa8d9ec554`，受影响测试使用 `9016a727`；上面的 `0a2b3c41` 是上一轮记录。
- `backend/tests/test_call_stats.py` 将现有 `test_a_call_that_connected_counts_for_as_long_as_its_record_says_and_one_that_did_not_does_not` 改用 `database_target`，分别在 SQLite 和 pgserver 启动的独立临时 PostgreSQL 数据库运行。数据库、临时服务器由现有 fixture 收尾删除，不接触用户已有数据库。活动记录读取 helper 同样支持两种数据库，并在线程中读取、关闭连接。
- 复用真实 WebRTC 回环和假语音服务，接通、完成一个回合并挂断；在线程中用 `database.connect` 读取 `calls` 并关闭连接，断言恰有一条记录、`conversation_id` 是拨号的会话、`duration_s > 0`，统计接口的 `count` 和 `seconds` 与记录完全一致。`kogane` 仅沿用现有测试角色，不是产品默认角色。
- 合并后首次单跑 PostgreSQL 参数，在旧 helper 的 `sqlite3.connect` 处失败（unable to open database file）；改用 `database.connect` 后，`cd backend && UV_NO_SYNC=1 uv run pytest -q tests/test_call_stats.py`：7 passed，14 warnings，7.14 秒。SQLite、PostgreSQL 两个参数均执行，无跳过；保留了原有未接通、活动记录、角色统计和对话记录断言。
- `UV_NO_SYNC=1 sh scripts/affected-tests.sh 9016a727`：Ruff 通过，Pyright 0 errors / 0 warnings，通话统计测试 7 passed，14 warnings，7.08 秒。pytest 提示来自 audioop、AudioContextTTSService 和 WorkerRunner 的弃用提醒。
- 文件编辑工具本次已能直接修改实际开发目录，此前工具不可编辑的阻碍已解除。没有推送，也不开 PR。
- 本票继续保持未完成：自建角色 `voice_id` 到 Fish 请求的完整链路仍未确认。本次只补数据库通话测试，不以此声称真实 STT/TTS 或 M3 多节点已经跑通。
- 两份只读审查报告：任务要求 0 项问题；代码规范发现 1 项重复场景（CODING_STANDARDS.md 的 Same setup, assertions split）。已将新断言并入现有双数据库测试，删除新增的重复测试。

### 实现说明（票 01，2026-11-17 收尾）

- 本轮起点 `af2a7dfb`。只补测试和记录；不修改产品实现、不开始 M3、不推送或开 PR。
- `test_own_speech_keys.py::test_custom_characters_voice_and_own_key_reach_fish` 通过真实 API 创建私有角色，将其保存的 `custom-fish-voice` 用于真实 WebRTC 通话和一个文字回合。使用生产 `SpeechServices`、`FishTTS` 与 Fish 消息编码，只替换外部识别服务和 WebSocket 网络连接。断言编码后的 `reference_id`、网络连接的 Authorization，以及回合正常结束。Soniox/百炼选择沿用既有测试。
- `UV_NO_SYNC=1 uv run pytest -q tests/test_own_speech_keys.py tests/test_fish_segments.py tests/test_avatar.py`：41 passed，12 warnings，36.07 秒。覆盖自带语音服务、Fish 分段及头像；没有收费服务请求。
- `UV_NO_SYNC=1 uv run pytest -q tests/test_call.py tests/test_call_outcome.py tests/test_own_keys.py tests/test_usage.py tests/test_exempting_keys.py tests/test_call_stats.py tests/test_call_records.py tests/test_concurrent_calls.py`：95 passed，53 warnings，25.61 秒。运行结束后另有四条 aioice `Connection.check_start` 后台任务错误（关闭后的 UDP transport 为 None），不能把这一运行描述为没有错误输出；见票 02。未修改第三方库，也未过滤或吞掉这些错误。
- 当前代码的构建版、独立临时 PostgreSQL、系统 Chromium、Playwright 运行六个场景：公开头像成功显示；拨号中删除；接通收起时删除；接通展开时删除；A 通话中从 B 编辑页返回并取消；A 通话中从 A 编辑页返回。全部断言通过，页面脚本错误 0。
- 三种删除均确认通话层、通话条与 `[inert]` 为 0，浏览器客户端 RTCPeerConnection 均关闭，真实角色 API 返回 404。展开场景将 DELETE 响应挂起后，程序触发已有通话条的展开按钮，再放行真实删除响应；这是覆盖响应到达时的状态，不声称鼠标可点击弹窗遮住的控件。
- 跨角色取消后仍在 B 编辑页，A 通话条继续计时；同角色返回直接进入 A 对话，无挂断确认。通话准备和 offer/PATCH 由本机浏览器 WebRTC 对端代答，发送 bot-ready，使用假麦克风；此结果证明页面状态处理，不证明真实 STT/TTS 或用户音色的实际听感。
- `CI=1 BACKEND_URL=http://127.0.0.1:18000 npm run build` 首次被 Next.js 安全升级提示中止，重试原命令后通过；保留 LINE Seed JP 字体提醒。Next.js 提示另记在维护票，不在本次收尾中擅自升级框架。
- 真实服务仍需要用户在自己的浏览器「设置 → 自带密钥」填写配置，再打一通电话；key 不应发送到聊天或写入本票。缺少相关资料时是否编造，仍在 M2 资料票 05 等待真实模型试用。
- `UV_NO_SYNC=1 sh scripts/affected-tests.sh af2a7dfb`：Ruff 通过，Pyright 0 errors / 0 warnings；`test_avatar.py`、`test_own_speech_keys.py` 共 27 passed，12 条弃用提醒，1.99 秒。此次输出没有 aioice 后台任务错误。
- 临时 Playwright 脚本和后端启动脚本已删除；没有读取 `.env` 或真实凭据。
- 临时前后端服务已停止。服务停止没有触发 pgserver 最后一个句柄的清理：其句柄记录仍指向已退出的启动进程，因此仅对本轮 `/tmp/eidolon-pre-m3-bmkzdlnh/postgres` 执行 pg_ctl fast stop，并删除本轮临时目录；命令返回 server stopped。没有停止或修改用户数据库。
- 清理后 `/usr/bin/ss -ltn '( sport = :3000 or sport = :18000 )'` 没有监听行，`/usr/bin/ps -C postgres -o pid=,args=` 没有进程行。浏览器及其 WebRTC 对端已关闭。
- 两份只读报告（任务要求、代码规范）均未发现需要修改的问题。未将真实收费语音、aioice 收尾问题或 Next.js 安全提醒描述为已解决。
