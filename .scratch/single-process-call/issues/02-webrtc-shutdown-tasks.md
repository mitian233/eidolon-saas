# WebRTC 收尾后仍运行的 ICE 后台任务

Status: ready-for-agent

## 已观察到的行为

2026-11-17，在 af2a7dfb 之后仅修改语音和头像测试的工作区运行：

```sh
cd backend && UV_NO_SYNC=1 uv run pytest -q tests/test_call.py tests/test_call_outcome.py tests/test_own_keys.py tests/test_usage.py tests/test_exempting_keys.py tests/test_call_stats.py tests/test_call_records.py tests/test_concurrent_calls.py
```

95 passed，53 warnings，25.61 秒，退出码 0；随后输出四条 `Task exception was never retrieved`。协程为 aioice `Connection.check_start`，发送 STUN 时 UDP transport 的 `_sock` 已为 None，错误处理又访问已为 None 的 `_loop.call_exception_handler`。

## 已读到的代码

安装的 aioice `Connection.connect` 在正常离开 ICE 等待后取消各 candidate pair 的 task（ice.py:604）；`Connection.close` 通知等待者失败并关闭 protocol（ice.py:615），但没有在该方法内逐个等待所有 candidate pair task。这里还不能断言具体是哪一个测试或哪一种产品通话操作触发，不能据此声称通话功能失败或已经修好。

## 完成条件

- [ ] 找到留下后台任务的具体测试/连接时序，保留真实的未接通或替换通话场景。
- [ ] 在连接所属的生命周期中正确结束后台工作；如为上游问题，确认已有修复及所需最小版本，不在产品中临时 monkeypatch 第三方私有状态。
- [ ] 原测试断言仍通过，结束时不再有未取走的 task 错误；不以过滤日志、忽略异常或固定 sleep 代替修复。

## Comments

本轮仅记录；没有修改 aioice/aiortc、产品通话逻辑或测试关闭流程。新增的语音和头像测试组合 41 passed，未出现这些后台任务错误。该组合结果不能证明这里的竞态已经解决。
