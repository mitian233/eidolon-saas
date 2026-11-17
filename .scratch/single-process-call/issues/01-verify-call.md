# 验证单进程通话

Status: ready-for-agent

## 验收项

- [ ] 使用已有非收费测试验证自建角色 voice_id 传至 Fish Audio 请求，以及 Soniox/百炼自带 key 的选择。
- [ ] 验证用户隔离、通话时长写入、限额与自带 key 免限额，以及独立的单通时长上限；先跑已有覆盖，只补缺口。
- [ ] 本地构建版使用 Playwright、假麦克风和模拟通话验证删除外壳持有的通话角色后，连接结束时通话层、通话条和导航 inert 清除，覆盖拨号、展开和收起状态。
- [ ] 同样验证与 A 通话时进入 B 编辑页，返回 B 对话需确认挂断；取消后仍在 B 编辑页且 A 通话继续；返回 A 不误问。
- [ ] 记录模拟 UI 与真实语音端到端证据的区别；真实 STT/TTS、音色、模型行为和公网头像留待人工或公网复验，不更改地址安全检查。
- [ ] 按仓库规则运行受影响检查；关闭本次服务和临时数据库并检查端口，记录命令、计数与缺口。

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
