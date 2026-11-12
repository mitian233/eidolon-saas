// 手机 4G 下量 LCP：应用页检查（app-check.mjs）用。
//
// 节流照 Lighthouse 移动端默认：RTT 150 ms、下行 1.6 Mbps、上行 750 Kbps、CPU 4 倍降速；
// 视口 390×844、DPR 3、触屏。每轮新开上下文，不带缓存。

const PHONE = { viewport: { width: 390, height: 844 }, deviceScaleFactor: 3, isMobile: true, hasTouch: true };

/**
 * 新开一个节流的手机上下文和页面，页面里记下每个 LCP 候选（用 lastLcp 取）。
 * `requests` 按 CDP 的 requestId 记每个请求的地址、发出时刻（秒）、类型和传输字节数。
 * `cookies` 给了就先放进上下文，例如登录后的会话。
 */
export async function phone4gPage(browser, { cookies } = {}) {
  const context = await browser.newContext(PHONE);
  if (cookies) await context.addCookies(cookies);
  const page = await context.newPage();
  const cdp = await context.newCDPSession(page);
  await cdp.send("Network.enable");
  await cdp.send("Network.setCacheDisabled", { cacheDisabled: true });
  await cdp.send("Network.emulateNetworkConditions", {
    offline: false,
    latency: 150,
    downloadThroughput: (1.6 * 1024 * 1024) / 8,
    uploadThroughput: (750 * 1024) / 8,
  });
  await cdp.send("Emulation.setCPUThrottlingRate", { rate: 4 });

  const requests = new Map();
  cdp.on("Network.requestWillBeSent", (e) => requests.set(e.requestId, { url: e.request.url, t: e.timestamp }));
  cdp.on("Network.responseReceived", (e) => {
    const r = requests.get(e.requestId);
    if (r) r.type = e.type;
  });
  cdp.on("Network.loadingFinished", (e) => {
    const r = requests.get(e.requestId);
    if (r) r.bytes = e.encodedDataLength;
  });

  await page.addInitScript(() => {
    window.__lcp = [];
    new PerformanceObserver((list) => {
      for (const e of list.getEntries()) window.__lcp.push({ t: e.startTime, id: e.element?.id ?? null, text: e.element?.textContent?.slice(0, 30) });
    }).observe({ type: "largest-contentful-paint", buffered: true });
  });

  return { context, page, requests };
}

/** 页面到目前为止最后一个 LCP 候选：`{ t, id, text }`，还没有时是 null。 */
export async function lastLcp(page) {
  return (await page.evaluate(() => window.__lcp)).at(-1) ?? null;
}

/** 几轮里 LCP 居中的那一轮（没量到 LCP 的排在最后）。 */
export function medianByLcp(measures) {
  const sorted = [...measures].sort((a, b) => (a.lcp?.t ?? Infinity) - (b.lcp?.t ?? Infinity));
  return sorted[Math.floor(sorted.length / 2)];
}
