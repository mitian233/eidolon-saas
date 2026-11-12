import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import { act0Text, landingText } from "./fontText";

/** 子集脚本写的清单：要了哪些字（text、act0），每种字体的完整子集里实际有哪些字（glyphs）。 */
const subset: { text: string; act0: string; glyphs: Record<string, string> } = JSON.parse(
  readFileSync(new URL("subset.json", import.meta.url), "utf-8"),
);

function missing(text: string, from: string) {
  const covered = new Set(from);
  return [...text].filter((ch) => !covered.has(ch));
}

const regenerate =
  "在 frontend 目录运行 `node scripts/landing-fonts.mts` 重新生成子集，连同 src/app/(landing)/fonts/ 一起提交。";

describe("落地页的字体子集", () => {
  it("覆盖落地页、登录组件和法务文案里的每一个字", () => {
    const lacking = missing(landingText(), subset.text);
    expect(lacking, `字体子集缺这些字：${lacking.join("")}。${regenerate}`).toEqual([]);
  });

  it("首屏预载的那一份覆盖第 0 幕上的每一个字", () => {
    const lacking = missing(act0Text(), subset.act0);
    expect(lacking, `第 0 幕的字体子集缺这些字：${lacking.join("")}。${regenerate}`).toEqual([]);
  });


  it("每一个字，正文和登录面板用的 Noto Sans SC 里都有", () => {
    const lacking = missing(landingText(), subset.glyphs["noto-sans-sc-400"]);
    expect(lacking, `Noto Sans SC 的子集没有这些字：${lacking.join("")}，会退回系统字体。${regenerate}`).toEqual([]);
  });
});
