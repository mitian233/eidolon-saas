import { describe, expect, it } from "vitest";

import { matchesSearch, type Searchable } from "@/lib/characterSearch";

const ROSTER: Searchable[] = [
  { name: "櫻木真乃", intro: "さくらぎ まの Sakuragi Mano" },
  { name: "月岡恋鐘", intro: "つきおか こがね Tsukioka Kogane" },
  { name: "田中摩美々", intro: "たなか まみみ" },
  { name: "浅倉透", intro: "あさくら とおる Asakura Toru" },
  { name: "樋口円香", intro: "ひぐち まどか" },
  { name: "誰か", intro: "" },
];

/** 搜索框里是 `query` 时留下的角色，按名单的顺序。 */
function found(query: string): string[] {
  return ROSTER.filter((c) => matchesSearch(c, query)).map((c) => c.name);
}

describe("matchesSearch", () => {
  it.each(["樱木", "真乃", "櫻木真乃"])("名字只输一部分也找得到：%s", (query) => {
    expect(found(query)).toEqual(["櫻木真乃"]);
  });

  it.each(["恋钟", "恋鐘", "戀鐘", "戀钟"])("繁体、日文字形和简体混着输都行：%s", (query) => {
    expect(found(query)).toEqual(["月岡恋鐘"]);
  });

  it("圆香找得到日文写法的円香", () => {
    expect(found("圆香")).toEqual(["樋口円香"]);
  });

  it.each(["摩美々", "摩美美", "田中摩美"])("々 和它前面的字一样：%s", (query) => {
    expect(found(query)).toEqual(["田中摩美々"]);
  });

  it.each(["まの", "マノ", "さくらぎ", "サクラギマノ", "ｻｸﾗｷﾞ"])("简介里的假名，平假名片假名都算：%s", (query) => {
    expect(found(query)).toEqual(["櫻木真乃"]);
  });

  it.each(["mano", "Sakuragi", "sakuragimano", "SAKURAGI"])("简介里的罗马字不分大小写和空格：%s", (query) => {
    expect(found(query)).toEqual(["櫻木真乃"]);
  });

  it.each(["toru", "tooru", "tōru", "Tohru"])("长音的几种写法都认：%s", (query) => {
    expect(found(query)).toEqual(["浅倉透"]);
  });

  it("简介里的词也找得到", () => {
    expect(found("こがね")).toEqual(["月岡恋鐘"]);
  });

  it("前后多打的空格不算", () => {
    expect(found("  真乃 ")).toEqual(["櫻木真乃"]);
  });

  it.each(["", "   "])("空着时全部留下：%j", (query) => {
    expect(found(query)).toEqual(ROSTER.map((c) => c.name));
  });

  it.each(["佐藤", "xyz", "ぴーちゃん"])("不认识的输入什么都不留下：%s", (query) => {
    expect(found(query)).toEqual([]);
  });

  it("没有简介的角色照旧用名字找得到", () => {
    expect(found("誰か")).toEqual(["誰か"]);
  });
});