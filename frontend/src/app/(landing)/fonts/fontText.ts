// 落地页的字体子集要覆盖的文字：落地页、登录组件和法务文案。角色由用户自建，
// 这里不再读仓库里的角色配置；子集脚本（scripts/landing-fonts.mts）按它生成子集，
// 覆盖契约测试拿它和子集的清单比对。只在本地（脚本和测试）运行，不进页面。

import { copy } from "@/i18n";
import { PROVIDER_LABELS } from "@/lib/signIn";

/** 不管文案里有没有，总要有的字：ASCII（拉丁字母、数字、色值），和常见的标点。 */
const ALWAYS =
  Array.from({ length: 0x7f - 0x21 }, (_, i) => String.fromCharCode(0x21 + i)).join("") +
  "、。，．・：；！？「」『』（）〈〉《》【】〔〕ー～…‥—―‘’“”♪☆★";

/** 文案目录里的一节：字符串原样收；带参数的句子用空参数调一次，收它的固定部分，参数另外收。 */
function strings(node: unknown): string[] {
  if (typeof node === "string") return [node];
  if (typeof node === "function") return strings((node as (...args: string[]) => unknown)("", "", ""));
  if (node && typeof node === "object") return Object.values(node).flatMap(strings);
  return [];
}

/** 去重、排好序，不含空白。 */
const unique = (parts: string[]) => [...new Set(parts.join("").replace(/\s/g, ""))].sort().join("");

/** 要覆盖的每一个字。 */
export function landingText(): string {
  return unique([
    ALWAYS,
    ...strings(copy.app),
    ...strings(copy.landing),
    ...strings(copy.legal),
    ...strings(copy.login),
    ...Object.values(PROVIDER_LABELS),
  ]);
}

/**
 * 首屏上的字：标题、副标题、声明和右上角的仓库链接、入口。这几个字另做一份很小的子集，
 * 只预载它；完整子集一起预载会和首屏的 CSS 抢带宽。文案改了而没有重新生成时，
 * 那几个字会从完整子集里取，字体对、只是晚一点到，覆盖契约测试同样会拦。
 */
export function act0Text(): string {
  return unique([copy.app.name, copy.app.description, copy.landing.disclaimer, copy.app.repositoryLabel, copy.landing.signIn, copy.landing.continue]);
}