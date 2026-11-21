import { describe, expect, it } from "vitest";

import { matchesSearch, type Searchable } from "@/lib/characterSearch";

const ROSTER: Searchable[] = [
  { name: "櫻庭紗季", intro: "さくらば さき Sakuraba Saki" },
  { name: "北川恋鈴", intro: "きたがわ れいりん Kitagawa Reirin" },
  { name: "森川奈々", intro: "もりかわ なな" },
  { name: "水野透", intro: "みずの とおる Mizuno Toru" },
  { name: "石田円葉", intro: "いしだ まるは" },
  { name: "誰か", intro: "" },
];

/** 搜索框里是 `query` 时留下的角色，按名单的顺序。 */
function found(query: string): string[] {
  return ROSTER.filter((c) => matchesSearch(c, query)).map((c) => c.name);
}

describe("matchesSearch", () => {
  it.each(["樱庭", "紗季", "櫻庭紗季"])("名字只输一部分也找得到：%s", (query) => {
    expect(found(query)).toEqual(["櫻庭紗季"]);
  });

  it.each(["恋铃", "恋鈴", "戀鈴", "戀铃"])("繁体、日文字形和简体混着输都行：%s", (query) => {
    expect(found(query)).toEqual(["北川恋鈴"]);
  });

  it("圆叶找得到日文写法的円葉", () => {
    expect(found("圆叶")).toEqual(["石田円葉"]);
  });

  it.each(["奈々", "奈奈", "森川奈"])("々 和它前面的字一样：%s", (query) => {
    expect(found(query)).toEqual(["森川奈々"]);
  });

  it.each(["さき", "サキ", "さくらば", "サクラバサキ", "ｻｸﾗﾊﾞ"])("简介里的假名，平假名片假名都算：%s", (query) => {
    expect(found(query)).toEqual(["櫻庭紗季"]);
  });

  it.each(["saki", "Sakuraba", "sakurabasaki", "SAKURABA"])("简介里的罗马字不分大小写和空格：%s", (query) => {
    expect(found(query)).toEqual(["櫻庭紗季"]);
  });

  it.each(["toru", "tooru", "tōru", "Tohru"])("长音的几种写法都认：%s", (query) => {
    expect(found(query)).toEqual(["水野透"]);
  });

  it("简介里的词也找得到", () => {
    expect(found("れいりん")).toEqual(["北川恋鈴"]);
  });

  it("前后多打的空格不算", () => {
    expect(found("  紗季 ")).toEqual(["櫻庭紗季"]);
  });

  it.each(["", "   "])("空着时全部留下：%j", (query) => {
    expect(found(query)).toEqual(ROSTER.map((c) => c.name));
  });

  it.each(["佐藤", "xyz", "ぽぽちゃん"])("不认识的输入什么都不留下：%s", (query) => {
    expect(found(query)).toEqual([]);
  });

  it("没有简介的角色照旧用名字找得到", () => {
    expect(found("誰か")).toEqual(["誰か"]);
  });
});