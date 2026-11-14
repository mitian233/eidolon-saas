import { describe, expect, it } from "vitest";
import { lookingUpText } from "@/lib/lookingUp";

describe("lookingUpText", () => {
  it("names her in full and what she looks up, in order", () => {
    expect(lookingUpText("櫻木真乃", ["story"])).toBe("櫻木真乃正在回忆");
    expect(lookingUpText("櫻木真乃", ["story", "story"])).toBe("櫻木真乃正在回忆、回忆");
  });
});
