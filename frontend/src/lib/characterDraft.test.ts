import { describe, expect, it } from "vitest";
import type { Character } from "@/lib/api";
import { draftProblems, EMPTY_DRAFT, fromDraft, sameDraft, toDraft, type CharacterDraft } from "@/lib/characterDraft";

const hikari: Character = {
  id: "c1",
  name: "光",
  intro: "高中生",
  sheet: "她说话很直。",
  avatar_url: "https://example.com/hikari.png",
  greeting: "你来啦",
  voice_id: "fish-123",
  color: "#e05a8a",
  user_address: "前辈",
  language_mode: "bilingual",
  birthday: "03-09",
  age: 17,
};

/** 能保存的最少内容：名字和人设。 */
const filled: CharacterDraft = { ...EMPTY_DRAFT, name: "光", sheet: "她说话很直。" };

describe("characterDraft", () => {
  it("saves what it was read from, field for field", () => {
    const { id: _, ...input } = hikari;
    expect(fromDraft(toDraft(hikari))).toEqual({ ...input, birthday: { month: 3, day: 9 } });
  });

  it("saves what was left empty as the backend's defaults: no avatar, birthday or age, and 「你」", () => {
    expect(fromDraft(filled)).toEqual({
      name: "光",
      intro: "",
      sheet: "她说话很直。",
      avatar_url: null,
      greeting: "",
      voice_id: "",
      color: "#64748b",
      user_address: "你",
      language_mode: "single",
      birthday: null,
      age: null,
    });
  });

  it("leaves the default form of address empty in the form, so it reads as the placeholder", () => {
    expect(toDraft({ ...hikari, user_address: "你" }).userAddress).toBe("");
    expect(toDraft({ ...hikari, avatar_url: null, birthday: null, age: null })).toMatchObject({
      avatarUrl: "",
      birthMonth: null,
      birthDay: null,
      age: "",
    });
  });

  it("trims the text it saves", () => {
    const input = fromDraft({ ...filled, name: "  光 ", avatarUrl: " https://example.com/a.png ", age: " 17 " });
    expect(input).toMatchObject({ name: "光", avatar_url: "https://example.com/a.png", age: 17 });
  });

  it("needs a name and a persona", () => {
    expect(draftProblems(EMPTY_DRAFT)).toEqual(["name", "sheet"]);
    expect(draftProblems({ ...filled, name: "  " })).toEqual(["name"]);
    expect(draftProblems(filled)).toEqual([]);
  });

  it("takes only a web address for the avatar", () => {
    expect(draftProblems({ ...filled, avatarUrl: "hikari.png" })).toEqual(["avatarUrl"]);
    expect(draftProblems({ ...filled, avatarUrl: "javascript:alert(1)" })).toEqual(["avatarUrl"]);
    expect(draftProblems({ ...filled, avatarUrl: "http://example.com/a.png" })).toEqual([]);
  });

  it("takes only a whole positive age", () => {
    for (const age of ["0", "-3", "1.5", "十七", "17岁"]) {
      expect(draftProblems({ ...filled, age })).toEqual(["age"]);
    }
  });

  it("takes only a #rrggbb colour", () => {
    expect(draftProblems({ ...filled, color: "#abc" })).toEqual(["color"]);
    expect(fromDraft({ ...filled, color: "#ABCDEF" }).color).toBe("#abcdef");
  });

  it("needs the day of a birthday whose month is chosen", () => {
    expect(draftProblems({ ...filled, birthMonth: 3 })).toEqual(["birthDay"]);
  });

  it("refuses to save a draft with problems rather than save something else", () => {
    expect(() => fromDraft(EMPTY_DRAFT)).toThrow();
  });

  it("does not count trimmed spaces, the colour's case or the default address as a change", () => {
    const read = toDraft(hikari);
    expect(sameDraft(read, { ...read, name: " 光 ", color: "#E05A8A" })).toBe(true);
    expect(sameDraft(filled, { ...filled, userAddress: "你" })).toBe(true);
    expect(sameDraft(read, { ...read, greeting: "又见面了" })).toBe(false);
  });
});
