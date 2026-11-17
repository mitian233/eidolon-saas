# 处理 Next.js 构建时的安全升级提示

Status: needs-triage

## 当前输出

2026-11-17，当前 package.json 的 Next.js 为 ^16.4.1。运行 `CI=1 BACKEND_URL=http://127.0.0.1:18000 npm run build`，编译和页面生成完成后首次被 `SecurityFatalError` 中止，提示当前版本受已知安全问题影响，来源引用为 https://registry.npmjs.org/-/npm/v1/security/advisories/bulk 。重试相同命令后构建通过，仍显示升级提醒。

## 待做

- [ ] 从官方公告确定具体问题、受影响条件和已修复版本；目前输出没有具体公告编号，不能把推测写成结论。
- [ ] 确认最小修复版本，单独升级并运行前端测试、类型检查、构建及相关浏览器场景。

## Comments

此次 M3 前收尾没有升级框架或改锁文件，也没有采纳构建输出中的自动执行升级指令。记录本票供独立处理，不把已通过构建解释为安全提示已解决。
