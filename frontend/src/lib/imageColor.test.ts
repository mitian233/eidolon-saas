import { describe, expect, it } from "vitest";

import { themePair } from "@/theme/themeCss";

import { CALL_MUTED, contrast, distance, imageColorScale, mix, paperColors, shareTrack } from "./imageColor";

const { body } = paperColors;
/** 新主题（globals.css）里压在她壁纸上的正文和次要文字（时间戳、日期条）。 */
const foreground = themePair("--foreground");
const mutedForeground = themePair("--muted-foreground");
/** 统计里排行条的底（DESIGN.md「统计页」）。 */
const muted = themePair("--muted");

/** 界面上每一对「底色 + 上面的字或图标」，以及要达到的对比度。 */
function pairs(hex: string) {
  const s = imageColorScale(hex);
  return [
    ...(["light", "dark"] as const).flatMap((mode) => [
      { what: `${mode} 壁纸上的正文`, fg: foreground[mode], bg: s.wall[mode], min: 4.5 },
      { what: `${mode} 壁纸上的次要文字`, fg: mutedForeground[mode], bg: s.wall[mode], min: 4.5 },
      { what: `${mode} 头像描边`, fg: s.mark[mode], bg: body[mode], min: 3 },
      // 对话列表上没看过的搭话的圆点（DESIGN.md「Conversation list」）：选中行铺 bg-muted，悬停行铺 bg-muted/60。
      // 选中行这一对和统计排行条那一对是同一对（bar 就是 mark），合成一行。
      { what: `${mode} 列表圆点和选中行的底、统计排行条和它的底`, fg: s.mark[mode], bg: muted[mode], min: 3 },
      { what: `${mode} 列表圆点和悬停行的底`, fg: s.mark[mode], bg: mix(muted[mode], body[mode], 0.6), min: 3 },
      { what: `${mode} 按钮图标`, fg: s.button.fg[mode], bg: s.button.bg[mode], min: 4.5 },
      { what: `${mode} 她颜色的字`, fg: s.accent[mode], bg: body[mode], min: 4.5 },
      { what: `${mode} 强调色填底上的字`, fg: s.onAccent[mode], bg: s.accent[mode], min: 4.5 },
    ]),
    { what: "dark 按钮底色和页面", fg: s.button.bg.dark, bg: body.dark, min: 3 },
    { what: "分享图色带上的字", fg: s.share.onBanner, bg: s.share.banner, min: 4.5 },
    { what: "分享图排行条和它的底", fg: s.share.bar, bg: shareTrack, min: 3 },
    { what: "通话层下部白字", fg: "#ffffff", bg: s.call.deep, min: 7 },
    { what: "通话层下部次要字", fg: mix("#ffffff", s.call.deep, CALL_MUTED), bg: s.call.deep, min: 4.5 },
  ];
}

describe("imageColorScale", () => {
  it("任意色相和深浅的印象色在明暗两种模式下都看得清", () => {
    const colors = ["#f9c6d9", "#d44a96", "#184776", "#e6d92e", "#edf5ff", "#251914"]
      .map((hex) => ({ name: hex, hex }));
    for (let r = 0; r < 256; r += 51)
      for (let g = 0; g < 256; g += 51)
        for (let b = 0; b < 256; b += 51) {
          const hex = `#${[r, g, b].map((v) => v.toString(16).padStart(2, "0")).join("")}`;
          colors.push({ name: hex, hex });
        }

    const failures: string[] = [];
    for (const { name, hex } of colors)
      for (const p of pairs(hex)) {
        const ratio = contrast(p.fg, p.bg);
        if (ratio < p.min) failures.push(`${name} ${p.what} ${p.fg} on ${p.bg} ${ratio.toFixed(2)}`);
      }
    expect(failures).toEqual([]);
  });

  it("同为粉色的两位角色，通话层底色仍然分得开", () => {
    const mano = imageColorScale("#ffbad6");
    const kogane = imageColorScale("#f84cad");
    expect(distance(mano.call.deep, kogane.call.deep)).toBeGreaterThan(0.03);
  });

  it("分享图的色带铺原色：深的印象色上写白字，浅的写同色相的深色", () => {
    const hiori = imageColorScale("#144384");
    expect(hiori.share).toMatchObject({ banner: "#144384", onBanner: "#ffffff" });
    const mano = imageColorScale("#ffbad6");
    expect(mano.share).toMatchObject({ banner: "#ffbad6", onBanner: mano.button.fg.light });
  });

  it("分享图排行条的底就是主题里的 --share-track", () => {
    expect(themePair("--share-track").light).toBe(shareTrack);
  });

  it("拒绝不是 #rrggbb 的色值", () => {
    expect(() => imageColorScale("pink")).toThrow();
  });

  it("同一个印象色只推算一次：每次渲染都会调用它，逐级搜索颜色太慢", () => {
    expect(imageColorScale("#ffbad6")).toBe(imageColorScale("#FFBAD6"));
  });
});
