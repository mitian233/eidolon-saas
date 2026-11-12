import { describe, expect, it } from "vitest";
import type { Character, Memory } from "@/lib/api";
import { sourceCharacter, supersededMark } from "@/lib/memories";

const mano: Character = {
  id: "mano",
  name: "角色甲",
  intro: "",
  sheet: "",
  avatar_url: "/api/characters/mano/avatar",
  greeting: "",
  voice_id: "",
  color: "#ffbad6",
  user_address: "你",
  language_mode: "single",
  birthday: "04-25",
  age: null,
};

const memory = (source: string, superseded = false): Memory => ({
  id: 1,
  text: "制作人喜欢喝咖啡",
  source_character_id: source,
  source_character_name: source === "mano" ? "角色甲" : null,
  created_at: "2026-09-01T12:00:00Z",
  superseded,
});

describe("sourceCharacter", () => {
  it("找到记忆的来源角色，界面才能用她的颜色和头像标出来", () => {
    expect(sourceCharacter(memory("mano"), [mano])).toBe(mano);
  });

  it("来源角色已经不在配置里时没有角色", () => {
    expect(sourceCharacter(memory("hiori"), [mano])).toBeNull();
  });

  it("角色列表还没取到时也没有角色", () => {
    expect(sourceCharacter(memory("mano"), [])).toBeNull();
  });
});

describe("supersededMark", () => {
  it("被取代的记忆标出「已被取代」", () => {
    expect(supersededMark(memory("mano", true))).toBe("已被取代");
  });

  it("有效的记忆不标", () => {
    expect(supersededMark(memory("mano"))).toBeNull();
  });
});
