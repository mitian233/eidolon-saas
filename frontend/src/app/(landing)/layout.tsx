import "../globals.css";
import "./landing.css";

import type { Metadata } from "next";
import localFont from "next/font/local";
import { headers } from "next/headers";

import { copy } from "@/i18n";

/**
 * 标题、描述和分享卡片（Open Graph、Twitter 卡片）。卡片要绝对地址，而自托管的构建不知道部署在哪个
 * 域名下：按这次请求的地址拼（Caddy 转发时带着原来的 Host 和 X-Forwarded-Proto）。
 */
export async function generateMetadata(): Promise<Metadata> {
  const h = await headers();
  return {
    metadataBase: requestOrigin(h.get("x-forwarded-host") ?? h.get("host"), h.get("x-forwarded-proto")),
    title: copy.app.name,
    description: copy.app.description,
    openGraph: {
      type: "website",
      url: "/",
      siteName: copy.app.name,
      locale: "zh_CN",
      title: copy.share.title,
      description: copy.share.description,
    },
    twitter: {
      card: "summary",
      title: copy.share.title,
      description: copy.share.description,
    },
  };
}

/** 这次请求的站点地址。经过几层代理时转发头是逗号分隔的一串，取第一段（离访客最近的那层）；拼不出来时没有。 */
function requestOrigin(host: string | null, proto: string | null): URL | undefined {
  const first = (v: string | null) => v?.split(",")[0].trim() || null;
  const h = first(host);
  if (!h) return undefined;
  try {
    return new URL(`${first(proto) === "https" ? "https" : "http"}://${h}`);
  } catch {
    return undefined;
  }
}

// 落地页的字体：按落地页实际用字做的静态子集，自托管（scripts/landing-fonts.mts 生成，改了文案要重新生成）。
// 每种两份：`-act0` 只有首屏上的字，很小，首屏预载它；完整子集不预载，等页面要用到首屏以外的字时再取。
// landing.css 把子集排进应用的字体栈；回退字体的度量由那里的字体栈负责，不让 next/font 去推算。
const jaAct0 = localFont({
  src: "./fonts/shippori-mincho-b1-600-act0.woff2",
  weight: "600",
  variable: "--lp-font-ja-act0",
  adjustFontFallback: false,
});
const ja = localFont({
  src: "./fonts/shippori-mincho-b1-600.woff2",
  weight: "600",
  variable: "--lp-font-ja",
  adjustFontFallback: false,
  preload: false,
});
const zhTitleAct0 = localFont({
  src: "./fonts/noto-serif-sc-600-act0.woff2",
  weight: "600",
  variable: "--lp-font-zh-title-act0",
  adjustFontFallback: false,
});
const zhTitle = localFont({
  src: "./fonts/noto-serif-sc-600.woff2",
  weight: "600",
  variable: "--lp-font-zh-title",
  adjustFontFallback: false,
  preload: false,
});
const zhAct0 = localFont({
  src: "./fonts/noto-sans-sc-400-act0.woff2",
  weight: "400",
  variable: "--lp-font-zh-act0",
  adjustFontFallback: false,
});
const zh = localFont({
  src: "./fonts/noto-sans-sc-400.woff2",
  weight: "400",
  variable: "--lp-font-zh",
  adjustFontFallback: false,
  preload: false,
});

const fontVariables = [jaAct0, ja, zhTitleAct0, zhTitle, zhAct0, zh].map((f) => f.variable).join(" ");

/** 落地页自己的根 layout：不加载应用根 layout 里 next/font 的 CJK 切片，首屏只带自托管子集。 */
export default function LandingLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN" className={fontVariables}>
      <body>{children}</body>
    </html>
  );
}