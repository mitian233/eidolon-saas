// 应用页（根 layout 在 src/app/(app)/ 的那些页）的字体和首屏检查（.scratch/root-layout-font-lcp）：
// 人工运行，不进 vitest。以后改应用的字体时再跑一遍，和之前的数字对比。
//
//   npm run build && BACKEND_URL=http://localhost:8000 npm run start   # 构建版，不用 dev
//   node scripts/app-check.mjs [origin] [runs]                          # 默认 http://localhost:3000，3 轮
//
// 量这几项：
//   1. `/login`、`/privacy` 在手机 4G 节流下的 LCP（几轮取中位数），每页不超过 2.5 秒才算通过。
//      节流、视口见 phone-4g.mjs。
//   2. 登录后的 `/conversations` 和一个对话页（第一位角色）的 LCP：只打印数字，不算通过与否，
//      里面还掺着接口耗时。会话用开发登录取（后端要开 EIDOLON_DEV_LOGIN=1，会建一位叫 app-check 的用户并替它
//      同意条款），或者把一个有效会话的 cookie 值放进环境变量 APP_SESSION。两者都没有时跳过。
//   3. 每页的阻塞样式表（首屏 HTML 里的 <link rel="stylesheet">）有几个，各自 gzip 后多大；带 @font-face
//      的算字体 CSS，按字体名列出条数、字重和切片数。gzip 是脚本自己压的（和 next start 默认的压缩一样是
//      gzip），不受节流和传输头影响，前后好比。
//
// 退出码：第 1 项两页都通过时是 0，否则是 1。

import { gzipSync } from "node:zlib";

import { chromium } from "playwright";

import { fontFaces, fontFamilies } from "./font-css.mjs";
import { lastLcp, medianByLcp, phone4gPage } from "./phone-4g.mjs";

const origin = (process.argv[2] ?? "http://localhost:3000").replace(/\/$/, "");
const runs = Number(process.argv[3] ?? 3);
const LCP_BUDGET_MS = 2500;

const results = [];
function report(name, ok, detail) {
  results.push({ name, ok });
  console.log(`${ok === null ? "跳过" : ok ? "通过" : "失败"}  ${name}${detail ? `：${detail}` : ""}`);
}

const formatKB = (bytes) => `${(bytes / 1024).toFixed(1)} KB`;

/** 几轮里各自的 LCP 和中位数那一轮。登录后的页面等接口也回来了再读。 */
async function measureLcp(pathname, { cookies } = {}) {
  const measures = [];
  for (let n = 0; n < runs; n++) {
    const { context, page } = await phone4gPage(browser, { cookies });
    await page.goto(`${origin}${pathname}`, { waitUntil: "load", timeout: 120000 });
    if (cookies) await page.waitForLoadState("networkidle", { timeout: 60000 }).catch(() => {});
    await page.waitForTimeout(1500);
    measures.push({ lcp: await lastLcp(page), path: new URL(page.url()).pathname });
    await context.close();
  }
  const median = medianByLcp(measures);
  const each = measures.map((m) => (m.lcp ? m.lcp.t.toFixed(0) : "无")).join("、");
  const what = median.lcp?.id ? `#${median.lcp.id}` : median.lcp?.text ? `「${median.lcp.text}」` : "无";
  const landed = median.path === pathname ? "" : `，停在 ${median.path}`;
  return { ms: median.lcp?.t ?? NaN, detail: `${(median.lcp?.t ?? NaN).toFixed(0)} ms（各轮 ${each}；LCP 元素 ${what}${landed}）` };
}

/** 打印首屏 HTML 里的阻塞样式表：个数、各自 gzip 后的大小，字体 CSS 按字体名汇总。 */
async function printStylesheets(pathname, { cookies } = {}) {
  const headers = cookies ? { cookie: cookies.map((c) => `${c.name}=${c.value}`).join("; ") } : {};
  const html = await (await fetch(`${origin}${pathname}`, { headers })).text();
  const hrefs = [...html.matchAll(/<link\b[^>]*>/g)]
    .map(([tag]) => tag)
    .filter((tag) => /\brel="stylesheet"/.test(tag) && !/\bmedia="(print|not all)"/.test(tag))
    .map((tag) => tag.match(/\bhref="([^"]+)"/)?.[1])
    .filter(Boolean);
  let fontBytes = 0;
  const lines = [];
  for (const href of hrefs) {
    const css = await (await fetch(new URL(href, origin))).text();
    const bytes = gzipSync(css).length;
    const faces = fontFaces(css);
    const name = new URL(href, origin).pathname.split("/").at(-1);
    if (faces.length === 0) {
      lines.push(`        ${name}：样式 ${formatKB(bytes)}`);
      continue;
    }
    fontBytes += bytes;
    const families = fontFamilies(faces)
      .map((f) => `${f.family} ${f.faces} 条${f.weights.length ? `（字重 ${f.weights.join("/")}，${f.ranges} 个切片）` : ""}`)
      .join("；");
    lines.push(`        ${name}：字体 ${formatKB(bytes)}，${families}`);
  }
  console.log(`      阻塞样式表 ${hrefs.length} 个，字体 CSS gzip 后共 ${formatKB(fontBytes)}`);
  for (const line of lines) console.log(line);
}

/** 登录后的会话 cookie；拿不到时是 null。 */
async function signedInCookies() {
  if (process.env.APP_SESSION) return [{ name: "eidolon_session", value: process.env.APP_SESSION, url: origin }];
  const context = await browser.newContext();
  try {
    const res = await context.request.post(`${origin}/api/auth/dev-login`, { data: { name: "app-check" }, headers: { origin } });
    if (!res.ok()) return null;
    // 新建的用户要先同意条款，否则登录后的页都会被送去 /consent。
    await context.request.post(`${origin}/api/account/consent`, {
      data: { agree_to_terms: true, at_least_13: true },
      headers: { origin },
    });
    return await context.cookies();
  } finally {
    await context.close();
  }
}

/** 第一位角色的对话页；没有角色时是 null。 */
async function firstConversation(cookies) {
  const context = await browser.newContext();
  try {
    await context.addCookies(cookies);
    const res = await context.request.get(`${origin}/api/characters`);
    const characters = res.ok() ? await res.json() : [];
    return characters.length > 0 ? `/conversation/${encodeURIComponent(characters[0].id)}` : null;
  } finally {
    await context.close();
  }
}

const browser = await chromium.launch();

// —— 1. 不用登录的页：LCP 卡预算

for (const pathname of ["/login", "/privacy"]) {
  const { ms, detail } = await measureLcp(pathname);
  report(`${pathname} 手机 4G 下的 LCP 不超过 ${LCP_BUDGET_MS} ms（${runs} 轮的中位数）`, ms <= LCP_BUDGET_MS, detail);
  await printStylesheets(pathname);
}

// —— 2. 登录后的页：只报数字

const cookies = await signedInCookies();
if (cookies) {
  const conversation = await firstConversation(cookies);
  for (const pathname of ["/conversations", conversation]) {
    if (!pathname) {
      console.log("跳过  对话页：后端没有角色");
      continue;
    }
    const { detail } = await measureLcp(pathname, { cookies });
    console.log(`数字  ${pathname} 手机 4G 下的 LCP（不卡验收）：${detail}`);
    await printStylesheets(pathname, { cookies });
  }
} else {
  report("登录后的 /conversations 和对话页", null, "后端没开开发登录，也没有 APP_SESSION");
}

await browser.close();

process.exit(results.some((r) => r.ok === false) ? 1 : 0);
