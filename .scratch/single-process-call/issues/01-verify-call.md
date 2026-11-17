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
