# 文档和段落持久化与用户向量化

Status: done

目标：实现按角色归属的 `documents` / `passages` 存储，接入纯文本切块、来源接口和用户自带密钥向量化。

涉及文件：后端数据库和迁移、`embedding.py`、票 1 新模块、票 2 来源接口及相关测试。

依赖：票 01、票 02。测试需要 Postgres：是，先用 SQLite，再用 `backend/tests/conftest.py` 的 `database_target`、`postgres_url` 和 `pgserver` 临时 Postgres。

## 验收标准

- [x] 文档和段落按角色归属保存，支持删除与重复导入。
- [x] 使用用户自带密钥向量化，模型和维度隔离，换模型或维度不混用旧向量。
- [x] SQLite 和临时 Postgres 覆盖持久化路径。

## Comments

### 票 01 交接

使用 `eidolon.document_text.passages` 切块、`text_hash` 对规范化文本生成 SHA-256。默认每块最多 1200 个 Unicode 字符、无重叠；相同段落只保留首次出现。文档级重复导入可对整份文本调用 `text_hash`，持久化仍须按角色及模型/维度区分。


### 票 02 交接

`eidolon.retrieval.CharacterDocumentSource` 定义 `async search(query_vector: Sequence[float], character_id: str, limit: int) -> list[DocumentPassage]`；段落带 `text`、`origin` 和余弦相似度 `similarity`，须按当前角色过滤、相似度降序，且向量模型和维度须与本次查询匹配。`open_reference_sources(embedder, source)` 将其用于普通召回与两条回顾路径。`assembly.build` 的部署者和用户自带向量服务两条装配现在都使用 `EmptyDocumentSource`，所以票 03 接好真实存储前不会返回资料；请在两处按当前 embedder 构造真实来源，处理资源生命周期及模型/维度变更。票 02 的内存假来源只验证召回契约，不验证持久化和重新向量化。


### 实现说明（票 03）

`eidolon.documents.Documents` 按角色保存文档、段落和按模型及维度区分的向量；
`import_text(owner_id, character_id, origin, text, embedder)` 校验归属、按规范化
全文哈希去重并返回文档 ID，重复导入保留首次来源；`delete(owner_id, character_id,
document_id)` 删除文档；`source(embedder)` 提供票 02 的检索接口，按需补齐当前
模型和查询维度的向量。向量化失败时文本保留，可重试。角色和用户删除均清除文档。
装配的普通及自带服务路径均使用该来源；SQLite 和临时 PostgreSQL 覆盖持久化和删除，
并有导入到回合召回的测试。未使用真实收费接口。
