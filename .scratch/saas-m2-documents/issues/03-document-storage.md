# 文档和段落持久化与用户向量化

Status: ready-for-agent

目标：实现按角色归属的 `documents` / `passages` 存储，接入纯文本切块、来源接口和用户自带密钥向量化。

涉及文件：后端数据库和迁移、`embedding.py`、票 1 新模块、票 2 来源接口及相关测试。

依赖：票 01、票 02。测试需要 Postgres：是，先用 SQLite，再用 `backend/tests/conftest.py` 的 `database_target`、`postgres_url` 和 `pgserver` 临时 Postgres。

## 验收标准

- [ ] 文档和段落按角色归属保存，支持删除与重复导入。
- [ ] 使用用户自带密钥向量化，模型和维度隔离，换模型或维度不混用旧向量。
- [ ] SQLite 和临时 Postgres 覆盖持久化路径。

## Comments

### 票 01 交接

使用 `eidolon.document_text.passages` 切块、`text_hash` 对规范化文本生成 SHA-256。默认每块最多 1200 个 Unicode 字符、无重叠；相同段落只保留首次出现。文档级重复导入可对整份文本调用 `text_hash`，持久化仍须按角色及模型/维度区分。
