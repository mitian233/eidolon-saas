# 文档导入 API

Status: done

目标：提供粘贴或上传文本的导入 API，校验角色归属并接收用户向量化配置。

涉及文件：后端 API 路由、文档持久化模块、请求模型与相关测试。

依赖：票 03。测试需要 Postgres：是，主要用 SQLite，至少一条持久化路径用临时 Postgres。

## 验收标准

- [x] 支持粘贴和上传文本，并拒绝跨用户访问角色。
- [x] 使用请求中的用户 embedding 配置；处理没有 key、向量化失败、重复导入和换模型。
- [x] SQLite 覆盖主要情况，临时 Postgres 覆盖至少一条持久化路径。

## Comments


### 票 03 交接

`backend.documents` 是装配中的 `Backend.documents`（类型 `eidolon.documents.Documents`）：
`await documents.import_text(owner_id, character_id, origin, text, embedder)` 返回文档 ID；
空文本或角色不属于用户时抛 `ValueError`，向量化失败会保留文档以便重试。重复导入
返回原 ID、保留首次来源；换模型时补齐向量。`await documents.delete(owner_id,
character_id, document_id)` 返回是否删除。自带 embedding 按请求创建，密钥不持久化；
调用方负责其关闭。票 03 未做列表接口，票 04 如需展示文档请补上。


### 实现说明（票 04）

新增角色文档的导入、列表和删除 HTTP 接口，复用用户自带 embedding 服务及角色归属检查。重复导入保留首次来源；向量化失败后文本留存，同样的文本重新导入可重试。列表里的已向量化段落数表示具有任意模型向量的段落数，并不表示当前模型可用；旧文档的创建时间为 null。SQLite 和临时 PostgreSQL 均通过 HTTP 持久化测试。前端通配转发层已支持这些路径和方法。
