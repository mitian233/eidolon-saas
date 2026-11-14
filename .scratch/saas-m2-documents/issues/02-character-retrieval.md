# 召回只从角色知识库来

Status: done

目标：定义按角色取文档段落的来源接口，资料召回只使用角色知识库，长期记忆不变。

涉及文件：`backend/src/eidolon/retrieval.py`，相关测试；关注 `open_reference_sources` 和 `recall_story`。

依赖：无。测试需要 Postgres：否，使用内存假来源。

## 验收标准

- [x] 普通召回与 `recall_story` 从角色文档段落来源取资料，不依赖 episode 展开或作品事实。
- [x] 测试重排阈值与无重排时按相似度降级，保留既有召回机制。
- [x] 长期记忆路径保持不变。

## Comments


### 实现说明（票 02）

`retrieval.CharacterDocumentSource.search(query_vector, character_id, limit)` 返回按相似度降序的 `DocumentPassage(text, origin, similarity)`；来源须按角色过滤并只使用与查询向量模型、维度兼容的向量。普通召回、判断模型触发的回顾和 `recall_story` 均检索这一来源，沿用重排、阈值和按相似度降级；长期记忆路径未改。装配暂以空来源运行，票 03 替换。测试用内存来源。

旧剧情召回辅助代码暂留待清理：`StoryReferences`、`_search_work`、`recall_prompt`、`_transcript`，以及 `ReferenceSources` 中仅供旧来源使用的 `corpus`、`work`、`facts` 和重嵌入相关接口；其他剧情模块可能仍有调用，清理前须逐项确认。旧的完整剧情和目录展开不再参与召回。
