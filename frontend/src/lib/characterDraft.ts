// 新建、编辑角色用的表单草稿：文字项都是字符串（空白表示没填），生日的月和日分开选。
// 保存时由 fromDraft 换成后端的 CharacterInput：两端空白去掉，没填的可选项交 null 或默认值。

import type { Character, CharacterInput } from "@/lib/api";
import { missingBirthDay } from "@/lib/producerProfile";

/** 后端 CharacterInput 的长度上限（按字数）。表单用输入框的 maxLength 挡，浏览器按 UTF-16 计，
 * emoji 这类字算两个，所以只会比后端挡得早一点，不会交上去超长的。 */
export const CHARACTER_LIMITS = {
  name: 100,
  intro: 2000,
  sheet: 100_000,
  greeting: 10_000,
  voiceId: 200,
  userAddress: 80,
} as const;

/** 后端的默认值：没选颜色时的中性灰，她对用户的默认称谓。 */
export const DEFAULT_COLOR = "#64748b";
export const DEFAULT_USER_ADDRESS = "你";

export type CharacterDraft = {
  name: string;
  intro: string;
  sheet: string;
  avatarUrl: string;
  greeting: string;
  voiceId: string;
  color: string;
  /** 空白保存成默认的「你」。 */
  userAddress: string;
  languageMode: Character["language_mode"];
  birthMonth: number | null;
  birthDay: number | null;
  /** 输入框里的原样，空白是没填。 */
  age: string;
};

/** 新建角色时的空草稿。 */
export const EMPTY_DRAFT: CharacterDraft = {
  name: "",
  intro: "",
  sheet: "",
  avatarUrl: "",
  greeting: "",
  voiceId: "",
  color: DEFAULT_COLOR,
  userAddress: "",
  languageMode: "single",
  birthMonth: null,
  birthDay: null,
  age: "",
};

export function toDraft(character: Character): CharacterDraft {
  const [month, day] = character.birthday?.split("-").map(Number) ?? [null, null];
  return {
    name: character.name,
    intro: character.intro,
    sheet: character.sheet,
    avatarUrl: character.avatar_url ?? "",
    greeting: character.greeting,
    voiceId: character.voice_id,
    color: character.color,
    userAddress: character.user_address === DEFAULT_USER_ADDRESS ? "" : character.user_address,
    languageMode: character.language_mode,
    birthMonth: month,
    birthDay: day,
    age: character.age === null ? "" : String(character.age),
  };
}

/** 草稿里不能保存的项，每项一个原因：名字和人设必填；头像地址要是 http(s) 网址；颜色是 #rrggbb；
 * 年龄是正整数；生日选了月要再选日。长度上限由输入框的 maxLength 挡住。 */
export type DraftProblem = "name" | "sheet" | "avatarUrl" | "color" | "age" | "birthDay";

export function draftProblems(draft: CharacterDraft): DraftProblem[] {
  const problems: DraftProblem[] = [];
  if (!draft.name.trim()) problems.push("name");
  if (!draft.sheet.trim()) problems.push("sheet");
  if (draft.avatarUrl.trim() && !isWebAddress(draft.avatarUrl.trim())) problems.push("avatarUrl");
  if (!/^#[0-9a-fA-F]{6}$/.test(draft.color)) problems.push("color");
  if (draft.age.trim() && parseAge(draft.age) === null) problems.push("age");
  if (missingBirthDay(draft)) problems.push("birthDay");
  return problems;
}

/** 先用 draftProblems 挡下不能保存的草稿；传进来有问题的草稿会抛错，不会悄悄存成别的值。 */
export function fromDraft(draft: CharacterDraft): CharacterInput {
  const problems = draftProblems(draft);
  if (problems.length > 0) throw new Error(`character draft has problems: ${problems.join(", ")}`);
  const { birthMonth, birthDay } = draft;
  return {
    name: draft.name.trim(),
    intro: draft.intro.trim(),
    sheet: draft.sheet.trim(),
    avatar_url: draft.avatarUrl.trim() || null,
    greeting: draft.greeting.trim(),
    voice_id: draft.voiceId.trim(),
    color: draft.color.toLowerCase(),
    user_address: draft.userAddress.trim() || DEFAULT_USER_ADDRESS,
    language_mode: draft.languageMode,
    birthday: birthMonth !== null && birthDay !== null ? { month: birthMonth, day: birthDay } : null,
    age: draft.age.trim() ? parseAge(draft.age) : null,
  };
}

/** 两份草稿存下去是否一样：文字两端的空白和颜色的大小写不算改动。 */
export function sameDraft(a: CharacterDraft, b: CharacterDraft): boolean {
  const saved = (d: CharacterDraft) => ({
    ...d,
    name: d.name.trim(),
    intro: d.intro.trim(),
    sheet: d.sheet.trim(),
    avatarUrl: d.avatarUrl.trim(),
    greeting: d.greeting.trim(),
    voiceId: d.voiceId.trim(),
    color: d.color.toLowerCase(),
    userAddress: d.userAddress.trim() || DEFAULT_USER_ADDRESS,
    age: d.age.trim(),
  });
  const [x, y] = [saved(a), saved(b)];
  return (Object.keys(x) as (keyof CharacterDraft)[]).every((key) => x[key] === y[key]);
}

function isWebAddress(value: string): boolean {
  try {
    const { protocol } = new URL(value);
    return protocol === "http:" || protocol === "https:";
  } catch {
    return false;
  }
}

/** 正整数的年龄；其他写法（小数、0、负数、夹着字）是 null。 */
function parseAge(value: string): number | null {
  const trimmed = value.trim();
  if (!/^\d+$/.test(trimmed)) return null;
  const age = Number(trimmed);
  return Number.isSafeInteger(age) && age > 0 ? age : null;
}
