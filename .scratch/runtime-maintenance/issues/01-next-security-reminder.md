# 处理 Next.js 构建时的安全升级提示

Status: done

安排：用户要求先继续 M3，本票在 M3 实现结束后再测试和处理，不插入 M3 实现阶段。

## 当前输出

2026-11-17，当前 package.json 的 Next.js 为 ^16.4.1。运行 `CI=1 BACKEND_URL=http://127.0.0.1:18000 npm run build`，编译和页面生成完成后首次被 `SecurityFatalError` 中止，提示当前版本受已知安全问题影响，来源引用为 https://registry.npmjs.org/-/npm/v1/security/advisories/bulk 。重试相同命令后构建通过，仍显示升级提醒。

## 待做

- [x] 从官方公告确定具体问题、受影响条件和已修复版本；目前输出没有具体公告编号，不能把推测写成结论。
- [x] 确认最小修复版本，单独升级并运行前端测试、类型检查、构建及相关浏览器场景。

## Comments

此次 M3 前收尾没有升级框架或改锁文件，也没有采纳构建输出中的自动执行升级指令。记录本票供独立处理，不把已通过构建解释为安全提示已解决。

M3 的本机生产构建再次出现同一升级提示，原命令重试通过。Next.js 版本和锁文件未改，仍需从官方公告确定适用的修复版本。

M3 提交 `8ebbf2e7` 后再次运行 `CI=1 BACKEND_URL=http://127.0.0.1:18000 npm run build`。Next.js 16.4.1 完成编译和页面生成后仍因 `SecurityFatalError` 以退出码 1 中止。输出未给出公告编号，本票继续开放。

### 实现说明（票 01）

基点为 `saas/main` 的 `2fc7cb7b`。Next.js 的构建流程按 npm 公告的版本范围判断，任意一条命中即触发安全升级提示。旧日志只记录了公告接口地址。向同一接口提交 `16.4.1` 和 `16.4.5`，返回下列 7 条公告，全部命中 `16.4.1`。单独提交 `16.4.5` 时返回 `{}`。官方公告均将 `16.4.5` 列为 16.4 系列的最低修复版。应用是否受影响取决于各项运行条件。[Next.js 11 月安全发布说明](https://nextjs.org/blog/november-2026-security-release)

| 官方公告 | 16.x 受影响版本 | 受影响条件 |
| --- | --- | --- |
| [GHSA-mfr8-8qww-v76h](https://github.com/vercel/next.js/security/advisories/GHSA-mfr8-8qww-v76h) / CVE-2026-119790 | 16.3.0–16.4.4 | 启用 Cache Components，同一个读取根路由参数的公开 `use cache` 函数既被直接调用，也被 `unstable_cache` 调用，并发填充缓存时可能跨参数复用结果。 |
| [GHSA-vc7v-qv4w-wrv8](https://github.com/vercel/next.js/security/advisories/GHSA-vc7v-qv4w-wrv8) / CVE-2026-119351 | 16.2.0–16.4.4 | 启用 Cache Components，内层公开 `use cache` 读取根路由参数，外层在内层的延迟结果就绪前写入缓存，可能把内容送给其他根参数对应的请求。 |
| [GHSA-vvgp-ww4w-46vf](https://github.com/vercel/next.js/security/advisories/GHSA-vvgp-ww4w-46vf) / CVE-2026-119350 | 16.4.0–16.4.4 | 自托管 `next start`，启用 Cache Components 且未启用 Partial Prefetching。带有阻塞式回退页面的嵌套动态路由，在参数未于构建时生成且布局在 Suspense 内读取相应参数时可能污染共享回退缓存。 |
| [GHSA-rhh4-g77r-r9qj](https://github.com/vercel/next.js/security/advisories/GHSA-rhh4-g77r-r9qj) / CVE-2026-119349 | 16.0.0–16.4.4 | `use cache` 用二进制参数区分用户或账号，且其余缓存键输入相同。不同参数可能共用缓存条目。 |
| [GHSA-pc58-hwjq-p385](https://github.com/vercel/next.js/security/advisories/GHSA-pc58-hwjq-p385) / CVE-2026-119348 | 16.0.0–16.4.4 | 自托管应用直接返回由攻击者控制的上游 `fetch` 响应，且 HTTP/1.1 反向代理在同一后端连接上排队处理流水线请求。压缩响应头与已解压的正文不匹配时，代理可能把响应交给错误客户端。 |
| [GHSA-7qx7-33qx-rqx2](https://github.com/vercel/next.js/security/advisories/GHSA-7qx7-33qx-rqx2) / CVE-2026-119347 | 16.0.0–16.4.4 | 使用 Next.js 图片优化，攻击者能控制允许来源的图片，且原生图片处理后端能解码 SVG。此时 SVG 可能绕过默认拒绝规则。 |
| [GHSA-f3mh-rxg3-f5g2](https://github.com/vercel/next.js/security/advisories/GHSA-f3mh-rxg3-f5g2) / CVE-2026-119346 | 16.0.0–16.4.4 | Edge 路由通过 `NextResponse.cookies.set()` 设置敏感 cookie，同时有攻击者控制的同源 JavaScript。它可能从内部响应头读到 cookie。 |

在 `frontend/package.json` 将 `next` 从 `^16.4.1` 提高到 `^16.4.5`，用 `npm install next@16.4.5 --save-prefix '^' --no-audit --no-fund` 将实际安装版和锁定版升到 `16.4.5`。锁文件同步更新 `@next/env` 和各平台 `@next/swc-*`，其余包条目相同。对照 [16.4.2](https://github.com/vercel/next.js/releases/tag/v16.4.2)、[16.4.3](https://github.com/vercel/next.js/releases/tag/v16.4.3)、[16.4.4](https://github.com/vercel/next.js/releases/tag/v16.4.4)、[16.4.5](https://github.com/vercel/next.js/releases/tag/v16.4.5) 的发行说明以及两个版本的 npm 元数据，Node 和 React 版本要求相同。构建和页面试跑覆盖了本项目的 Proxy 与 standalone 启动，未发现需要迁移的用法。

- `git log -1 --format='%H %D%n%s'` 确认分支为 `saas/main`，基点为 `2fc7cb7b`。
- `npm audit --omit=dev --json` 在升级前列出上述 7 条 Next.js 公告。向 `https://registry.npmjs.org/-/npm/v1/security/advisories/bulk` 发送 `{"next":["16.4.1","16.4.5"]}` 得到相同公告，发送 `{"next":["16.4.5"]}` 得到 `{}`。`npm view next@16.4.5 version engines peerDependencies dist.integrity --json` 确认修复版已发布。
- `cd frontend && npm test && npm run typecheck && sh scripts/check-discipline.sh` 全部通过，58 个测试文件、788 个测试通过。
- 在 `frontend/` 首次执行 `env CI=1 BACKEND_URL=http://127.0.0.1:18000 npm run build`，退出码 0，生成 26 个页面。没有 `SecurityFatalError`、安全升级提示或公告查询失败提示。Turbopack 报了一条 `LINE Seed JP` 字体回退警告。
- 在仓库根目录执行 `sh scripts/affected-tests.sh 2fc7cb7b`，退出码 0。脚本跑了前端类型生成和类型检查。
- 在 `frontend/` 用 `env BACKEND_URL=http://127.0.0.1:18000 node` 运行一次性 Playwright 脚本，启动 `node .next/standalone/server.js`。首次脚本选中了两个同名隐私政策链接，改为点击登录区内的链接后通过。Chromium 打开 `/` 得到 HTTP 200，页面带 CSP 响应头并加载了样式，随后打开 `/privacy` 并显示页标题。后端端口 `18000` 未监听，服务日志记录了登录选项请求连接被拒，本次覆盖访客页面。两次运行都关闭了浏览器和临时服务，删除了临时资源链接，并确认服务端口已释放。
