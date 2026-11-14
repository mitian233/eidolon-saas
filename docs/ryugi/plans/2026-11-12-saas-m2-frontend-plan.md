# M2 前端任务计划 — Eidolon-SaaS

来源规格：`docs/ryugi/specs/2026-11-12-saas-byok-design.md` §M2「角色编辑与资料导入」

## Task 1: 下线 283 专属导航与页面

**Goal:** 把导航从 `conversations / moments / play / settings` 改成 `conversations / settings`，删掉 moments 和 play 的路由页文件。  
对应规格「前端壳改造：下线 283 专属页」。

**Files:**
- `frontend/src/lib/navShell.ts`
- `frontend/src/lib/navShell.test.ts`
- `frontend/src/components/app/AppNav.tsx`
- `frontend/src/app/(app)/(nav)/moments/page.tsx` → 删除
- `frontend/src/app/(app)/(nav)/play/page.tsx` → 删除
- `frontend/src/app/(app)/(nav)/play/[subpage]/page.tsx` → 删除

**Interfaces:**
- Produces: `NAV_ITEMS = ["conversations", "settings"]`；`navItems()` 不再有 moments/play 参数；`isInShell()` 不再把 `/moments`、`/play/*` 算进外壳
- Consumes: 现有 `navShell.ts` 导出（`departure`、`showsShellCallBar` 等保持不变）

**Failing test:** `navShell.test.ts` 新增断言：`/moments` 和 `/play` 不在外壳里；`navItems()` 结果只有 `conversations` 和 `settings`；观察这两条在修改前失败

**Verify:** `cd frontend && npm run vitest -- src/lib/navShell.test.ts`  
**Expected:** navShell 相关 test 全绿；`npx tsc --noEmit` 通过

---

## Task 2: 角色创建/编辑界面

**Goal:** 在对话列表加「＋ 新建角色」按钮；每行角色右键菜单加「编辑角色」；新路由 `/characters/new` 和 `/characters/[characterId]/edit` 显示字段齐全的编辑表单（名字、简介、人设、头像 URL、问候语、语音 ID、主题色、称谓、语言模式、生日、年龄）；`api.ts` 加 `createCharacter`、`updateCharacter`、`deleteCharacter`、`getCharacter`。  
对应规格「角色编辑界面」。

**Files:**
- `frontend/src/lib/api.ts`
- `frontend/src/i18n/zh.ts`
- `frontend/src/lib/navShell.ts` — `isInShell` 把 `/characters/*` 加进外壳
- `frontend/src/app/(app)/(nav)/characters/new/page.tsx`（新）
- `frontend/src/app/(app)/(nav)/characters/[characterId]/edit/page.tsx`（新）
- `frontend/src/components/app/CharacterForm.tsx`（新）
- `frontend/src/components/conversations/ConversationList.tsx`

**Interfaces:**
- Produces: `createCharacter(input)`, `updateCharacter(id, input)`, `deleteCharacter(id)`, `getCharacter(id)` in `api.ts`；`CharacterForm` 受控表单组件；`/characters/new` 和 `/characters/[id]/edit` 路由
- Consumes: 现有 `/api/characters` CRUD 端点（后端 M1 已完成）；`Character` 类型（已在 `api.ts`）；`NavShell` 和 `PageShell` 外壳组件

**Failing test:** 新建 `frontend/src/components/app/CharacterForm.test.tsx`：表单初始值对应传入的 character（或空），submit 调用 onSave，取消调用 onCancel；观察在实现前失败

**Verify:** `cd frontend && npm test -- --testPathPattern='CharacterForm'`，然后 `npx tsc --noEmit`，然后 `npm run build`  
**Expected:** CharacterForm 测试绿；typecheck 通过；生产构建成功

---

## Review Focus

- Task 1：moments/play 相关的 `navDots`、`navDestination`、`isGiftsSubpageInView` 是否干净（没有死代码）；删掉的页面路由是否会让访问 `/moments` 触发 404（Next.js 路由找不到就 404）
- Task 2：`deleteCharacter` 后路由要回到 `/conversations`；创建/编辑表单的 submit 要用正确的 HTTP 方法（POST 新建、PUT 更新）；`avatar_url` 空字符串 vs null 语义；`language_mode`、`birthday`、`age` 的可选字段在 `CharacterInput` 里要能留空
