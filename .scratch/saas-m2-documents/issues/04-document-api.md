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
