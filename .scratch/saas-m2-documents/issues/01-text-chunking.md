# 通用纯文本切块和去重

Status: done

目标：提供通用纯函数，将文本稳定切成段落并提供规范化文本的去重哈希，供持久化复用。

涉及文件：`backend/src/eidolon/` 下新模块、`backend/tests/` 下纯单元测试；可参考 `corpus.py` 的 `_passages` 和 `StoryCorpus.save`。

依赖：无。测试需要 Postgres：否。

## 验收标准

- [x] 目标块长约 1200 字，明确记录是否重叠；超长单行也能切开。
- [x] 覆盖空文本、换行、超长单行、重复段落和相同文本重复导入时切法稳定。
- [x] 规范化后计算稳定哈希，供后续持久化去重；不访问数据库。

## Comments

### 实现说明（票 01）

新增 `eidolon.document_text`：`normalize_text` 统一换行、去除各行两端和全文首尾空白；`text_hash` 对规范化文本计算 SHA-256；`passages` 按行合并，每块最多 1200 个 Unicode 字符，超长单行按字符硬切，不重叠，按规范化哈希保留首次出现的段落。空白文本返回空列表，非法块长抛出 `ValueError`。纯 pytest 测试不需要 Postgres。
