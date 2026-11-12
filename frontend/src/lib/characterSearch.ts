// 对话列表的搜索框：一位角色留不留下。名字和简介都算候选；
// 输入和候选先经过同一套折叠，折叠后的输入是某个候选的子串就留下。

import type { Character } from "@/lib/api";

export type Searchable = Pick<Character, "name" | "intro">;

/** 搜索框里是 `query` 时她留不留下；空着（去掉前后空格后）时都留下。 */
export function matchesSearch(character: Searchable, query: string): boolean {
  const q = fold(query);
  return !q || [character.name, character.intro].some((candidate) => fold(candidate).includes(q));
}

/** 名字里的分隔：空白、中点、撇号、连字符、点。 */
const SEPARATORS = /[\s・'’\-·.]/g;

/** 繁体字和日文字形折成简体，搜索时不因字形差异漏掉。 */
const GLYPHS: Record<string, string> = {
  櫻: "樱", 風: "风", 織: "织", 燈: "灯", 宮: "宫", 岡: "冈", 戀: "恋", 鐘: "钟", 鍾: "钟",
  瀬: "濑", 瀨: "濑", 結: "结", 華: "华", 霧: "雾", 倉: "仓", 淺: "浅", 円: "圆", 圓: "圆",
  絲: "糸", 雛: "雏", 緋: "绯", 沢: "泽", 澤: "泽", 優: "优", 愛: "爱", 穂: "穗", 園: "园",
  樹: "树", 凜: "凛", 葉: "叶", 鳩: "鸠", 鈴: "铃", 陽: "阳", 課: "课", 後: "后",
};

/** 带长音符号的元音，和几种长音写法（oo、ou、oh、uu、aa、ii、ee），都折成一个元音。 */
const LONG_MARKS: [RegExp, string][] = [
  [/[ōô]/g, "o"],
  [/[ūû]/g, "u"],
  [/[āâ]/g, "a"],
  [/[īî]/g, "i"],
  [/[ēê]/g, "e"],
  [/o[ouh]/g, "o"],
  [/uu/g, "u"],
  [/aa/g, "a"],
  [/ii/g, "i"],
  [/ee/g, "e"],
];

function fold(text: string): string {
  let folded = text
    .normalize("NFKC")
    .toLowerCase()
    .replace(SEPARATORS, "")
    // 片假名转平假名
    .replace(/[ァ-ヶ]/g, (kana) => String.fromCharCode(kana.charCodeAt(0) - 0x60))
    .replace(/(.)々/gu, "$1$1");
  folded = Array.from(folded, (ch) => GLYPHS[ch] ?? ch).join("");
  for (const [mark, vowel] of LONG_MARKS) folded = folded.replace(mark, vowel);
  return folded;
}