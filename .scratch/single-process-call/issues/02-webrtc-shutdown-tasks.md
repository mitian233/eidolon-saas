# WebRTC 收尾后仍运行的 ICE 后台任务

Status: done

安排：用户要求先继续 M3，本票在 M3 实现结束后再测试和处理，不插入 M3 实现阶段。

## 已观察到的行为

2026-11-17，在 af2a7dfb 之后仅修改语音和头像测试的工作区运行：

```sh
cd backend && UV_NO_SYNC=1 uv run pytest -q tests/test_call.py tests/test_call_outcome.py tests/test_own_keys.py tests/test_usage.py tests/test_exempting_keys.py tests/test_call_stats.py tests/test_call_records.py tests/test_concurrent_calls.py
```

95 passed，53 warnings，25.61 秒，退出码 0；随后输出四条 `Task exception was never retrieved`。协程为 aioice `Connection.check_start`，发送 STUN 时 UDP transport 的 `_sock` 已为 None，错误处理又访问已为 None 的 `_loop.call_exception_handler`。

## 已读到的代码

安装的 aioice `Connection.connect` 在正常离开 ICE 等待后取消各 candidate pair 的 task（ice.py:604）；`Connection.close` 通知等待者失败并关闭 protocol（ice.py:615），但没有在该方法内逐个等待所有 candidate pair task。这里还不能断言具体是哪一个测试或哪一种产品通话操作触发，不能据此声称通话功能失败或已经修好。

## 完成条件

- [x] 找到留下后台任务的具体测试/连接时序，保留真实的未接通或替换通话场景。
- [x] 在连接所属的生命周期中正确结束后台工作；如为上游问题，确认已有修复及所需最小版本，不在产品中临时 monkeypatch 第三方私有状态。
- [x] 原测试断言仍通过，结束时不再有未取走的 task 错误；不以过滤日志、忽略异常或固定 sleep 代替修复。

## Comments

本轮仅记录；没有修改 aioice/aiortc、产品通话逻辑或测试关闭流程。新增的语音和头像测试组合 41 passed，未出现这些后台任务错误。该组合结果不能证明这里的竞态已经解决。

M3 提交 `8ebbf2e7` 后用上面的原命令重跑，95 项通过，53 条弃用提醒，用时 26.14 秒。此次没有出现此前的 aioice 后台任务错误。该问题仍可能偶发，保留本票。

### 实现说明（票 02）

在 `92428bf7` 运行原组合，95 项通过，进程退出时报出 4 条 `Connection.check_start` 异常。随后给 ICE 任务标上创建它的用例名，找到 `tests/test_call.py` 中的四个来源：

- `test_a_call_that_never_connects_does_not_count`：浏览器没有应用 SDP 应答，第一通等待超时，第二通在测试收尾时关闭。
- `test_a_call_whose_voice_services_cannot_be_made_is_refused_and_does_not_count` 和 `test_a_call_whose_voice_service_fails_before_any_turn_does_not_count`：服务故障后重拨，重拨收到应答但尚未接通，测试收尾时关闭。
- `test_deleting_a_character_while_her_offer_is_being_answered_cancels_the_call`：角色删除后，刚应答的连接在未接通时关闭。

`Calls` 经 Pipecat `disconnect()`、aiortc `RTCPeerConnection.close()` 和 `RTCIceTransport.stop()` 调到 aioice `Connection.close()`。`0.10.2` 先关 UDP socket，把取消候选对任务留给 `connect()`。如果还有候选对未开始，`connect()` 可在关闭后继续创建任务，首包 STUN 就会碰到已关闭的 socket。如果还在等 end-of-candidates，`connect()` 也可能一直走不到取消任务的代码。

`backend/pyproject.toml` 要求 `aioice>=0.12.1`，`backend/uv.lock` 锁定 `0.12.1`。该版的 `close()` 在关 socket 前停止启动新检查，取消并等待已启动的检查。应用继续通过 `disconnect()` 关闭连接。aiortc `1.16.0` 另修了在已关闭的 transport 上调用 `start()` 时抛出的 `InvalidStateError`，本票堆栈则在 `Connection.check_start()` 发送 STUN 时抛出 `AttributeError`。[aioice 发行说明](https://aioice.readthedocs.io/en/stable/changelog.html#id2) · [aioice 修复提交](https://github.com/aiortc/aioice/commit/719767ede7b64e7ee8a4ebb3098c90112b4ea4b1) · [aiortc 发行说明](https://aiortc.readthedocs.io/en/stable/changelog.html#id1)

`tests/test_concurrent_calls.py` 新增真实替换通话测试。第一通发出 STUN 请求后再拨第二通，断言第一通的 ICE 任务已结束，且第二通能接通。旧版在任务仍未结束处失败。同步到 `0.12.1` 后，原组合加新用例 96 项通过，无未取走的任务异常或仍在运行就被销毁的任务。随后运行 `env UV_NO_SYNC=1 sh scripts/affected-tests.sh 92428bf7`，Ruff 和 Pyright 通过，pytest 6 项通过，其中包括运行时工作区已有的 `test_webrtc_shutdown.py`。

运行原组合时，升级前后都观察到 `test_a_turn_a_failure_cuts_short_fails_even_once_the_call_was_settled_before_it` 收尾时的 `eidolon.data_access.Closed` 日志。这条日志来自活动记录写入。仓库约定和工单要求两路代码审阅均无发现。
