# 文档和头像的后续加固

Status: done

## 背景

v1 默认单进程部署。多个进程同时导入同一份文档时，可能重复发起 embedding 请求并重复计费；当前接受这个代价，后续需要跨进程协调。

## 验收标准

- [x] 评估并处理多进程重复向量化和重复计费。
- [x] 头像测试走真实 transport，只替换底层网络。
- [x] 召回的角色隔离使用真实存储验证普通召回、判断模型触发的回顾和 `recall_story` 三条路径。
- [x] 清理票 02 所列旧剧情召回死代码，逐项确认其他剧情模块的调用。

## Comments

### M3 前收尾补充（2026-11-17）

- `backend/tests/test_avatar.py` 的成功用例改走实际 AsyncHTTPTransport、httpcore pool 和 PublicOnlyBackend，只替换 DNS 与最底层的连接、读写。返回真实 PNG 字节，断言实际连接的是通过允许规则的 IP，Host 与 TLS server_hostname 保留原域名，HTTP 请求没有 Cookie。
- 新增混合公网/回环 DNS 结果用例，断言在连接前拒绝，底层连接次数为 0。内存 stream 记录 TLS hostname，但不进行真实 TLS 握手；真实 TLS 图片获取和浏览器显示另见票 05。
- 本票只完成头像一项；多进程向量化、真实存储下的三条召回路径、旧剧情死代码仍未处理，不以本次记录声称整票完成。

### 实现说明（票 06）

- 文档文字和段落先写入数据库，同一角色导入相同的规范化文本会得到同一个文档 ID。导入和召回时的补向量共用按角色和模型划分的锁，拿到锁后重新读取缺失的向量，向量写入完成后才释放锁。PostgreSQL 用独立事务的咨询锁协调各进程，其他角色仍可读写。SQLite 同一事件循环内的多个数据库实例按文件路径共用进程内锁。服务商已处理请求但结果尚未写入时，若进程退出或连接中断，重试仍可能再次计费。
- 在两种数据库中，用独立的 `Database`、`Documents` 和向量服务实例同时导入同一份文档。等第二个实例实际在等锁后放行第一个，确认只调用一次向量接口、只保留一份文档。普通召回、真实判断模型逻辑触发的回顾和 `recall_story` 均用同一用户的两个角色测试，两份文档对问题同样相关，每个角色只收到自己的资料。
- 移除 `StoryReferences`、`_search_work`、`recall_prompt`、`_transcript`、`EmptyDocumentSource` 和 `DocumentReferences`。`ReferenceSources` 直接使用角色文档段落，移除旧的 `corpus`、`work`、`facts`、`rank` 和重嵌入入口，以及 `ReferenceSource`、`Reembeddable`、后端启动和回合结束时的旧剧情资源处理。删除只覆盖旧剧情召回的断言和用例，仍覆盖对话行为的测试改用当前文档来源。
- `StoryCorpus`、`CharacterFacts`、`WorkFacts` 和长期记忆的独立实现与测试保留。`.scratch/prompt-caching/experiment.py` 是一次性的旧实验，仍引用 `StoryReferences`、`recall_prompt` 和在 `9df63455` 已移除的 `load_characters`，依赖 SaaS 改造前的代码和资料。
- 代码规范审查指出固定等待可能漏报并发问题，已改为观察实际锁等待。工单审查未发现遗漏。串行跑完 SQLite、PostgreSQL、文档接口、召回和头像等相关测试，共 119 项通过。`env UV_NO_SYNC=1 sh scripts/affected-tests.sh 9148e3e9` 的 pytest 共 275 项通过，Ruff 与 Pyright 均通过。临时 PostgreSQL 和测试目录已清理。
