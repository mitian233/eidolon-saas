# 文档和头像的后续加固

Status: ready-for-agent

## 背景

v1 默认单进程部署。多个进程同时导入同一份文档时，可能重复发起 embedding 请求并重复计费；当前接受这个代价，后续需要跨进程协调。

## 验收标准

- [ ] 评估并处理多进程重复向量化和重复计费。
- [x] 头像测试走真实 transport，只替换底层网络。
- [ ] 召回的角色隔离使用真实存储验证普通召回、判断模型触发的回顾和 `recall_story` 三条路径。
- [ ] 清理票 02 所列旧剧情召回死代码，逐项确认其他剧情模块的调用。

## Comments

### M3 前收尾补充（2026-11-17）

- `backend/tests/test_avatar.py` 的成功用例改走实际 AsyncHTTPTransport、httpcore pool 和 PublicOnlyBackend，只替换 DNS 与最底层的连接、读写。返回真实 PNG 字节，断言实际连接的是通过允许规则的 IP，Host 与 TLS server_hostname 保留原域名，HTTP 请求没有 Cookie。
- 新增混合公网/回环 DNS 结果用例，断言在连接前拒绝，底层连接次数为 0。内存 stream 记录 TLS hostname，但不进行真实 TLS 握手；真实 TLS 图片获取和浏览器显示另见票 05。
- 本票只完成头像一项；多进程向量化、真实存储下的三条召回路径、旧剧情死代码仍未处理，不以本次记录声称整票完成。
