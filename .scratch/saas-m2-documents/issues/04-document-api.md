# 文档导入 API

Status: ready-for-agent

目标：提供粘贴或上传文本的导入 API，校验角色归属并接收用户向量化配置。

涉及文件：后端 API 路由、文档持久化模块、请求模型与相关测试。

依赖：票 03。测试需要 Postgres：是，主要用 SQLite，至少一条持久化路径用临时 Postgres。

## 验收标准

- [ ] 支持粘贴和上传文本，并拒绝跨用户访问角色。
- [ ] 使用请求中的用户 embedding 配置；处理没有 key、向量化失败、重复导入和换模型。
- [ ] SQLite 覆盖主要情况，临时 Postgres 覆盖至少一条持久化路径。

## Comments


### 票 03 交接

`backend.documents` 是装配中的 `Backend.documents`（类型 `eidolon.documents.Documents`）：
`await documents.import_text(owner_id, character_id, origin, text, embedder)` 返回文档 ID；
空文本或角色不属于用户时抛 `ValueError`，向量化失败会保留文档以便重试。重复导入
返回原 ID、保留首次来源；换模型时补齐向量。`await documents.delete(owner_id,
character_id, document_id)` 返回是否删除。自带 embedding 按请求创建，密钥不持久化；
调用方负责其关闭。票 03 未做列表接口，票 04 如需展示文档请补上。
