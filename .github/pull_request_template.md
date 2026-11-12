<!--
写法见 .agents/skills/pr/SKILL.md：不写开场白，用 GLOSSARY.md 里的词。
Summary 选最小的一种视图讲清要点（diff 草图、调用树、文件树、Mermaid……）。
对应的 spec / ticket 在 .scratch/<feature>/ 下时，在 Summary 第一段写出路径。
-->

## Summary

<!-- 为什么要改、改了什么；配一张 diff 草图或树 -->

```diff
```

## Evidence

<!-- 截图最好（界面改动时）；其次是测试结果、命令输出、实测记录 -->

- **Before:**
  **After:**
- pytest / pyright / ruff / tsc / vitest 结果：

## Merge Danger

**Door:** <!-- one-way 或 two-way：数据库迁移、删除数据、改 .env 变量名等难以撤回的改动是 one-way -->

**Blast Radius:** <!-- 一个词：对话、通话、角色、记忆、登录、部署、开发流程…… -->

<!-- 合并后可能的影响：已有部署要不要改 .env、有没有数据库迁移、是否影响已有用户数据 -->

<!--
提交前自查（不用勾选，删掉也行）：
- 配置项有增删改时：.env.example、docs/configuration.md、docs/deploy.md 已同步；功能有增删时 README 也已更新
- 出现新术语或改了术语含义时：GLOSSARY.md 已更新
- 做了难以撤回的设计决策时：docs/adr/ 已加 ADR
- 没有提交 .env、密钥或任何原作素材（仓库不携带原作内容，见 LICENSING.md）
-->
