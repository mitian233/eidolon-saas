# 召回只从角色知识库来

Status: ready-for-agent

目标：定义按角色取文档段落的来源接口，资料召回只使用角色知识库，长期记忆不变。

涉及文件：`backend/src/eidolon/retrieval.py`，相关测试；关注 `open_reference_sources` 和 `recall_story`。

依赖：无。测试需要 Postgres：否，使用内存假来源。

## 验收标准

- [ ] 普通召回与 `recall_story` 从角色文档段落来源取资料，不依赖 episode 展开或作品事实。
- [ ] 测试重排阈值与无重排时按相似度降级，保留既有召回机制。
- [ ] 长期记忆路径保持不变。

## Comments
