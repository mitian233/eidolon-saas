import { afterEach, describe, expect, it, vi } from "vitest";

import {
  type Announcement,
  EXCERPT_LENGTH,
  excerpt,
  keepReadUpTo,
  newestPublished,
  readUpTo,
  unread,
} from "@/lib/announcements";

describe("excerpt", () => {
  it("drops the Markdown marks, keeping the words of links and code", () => {
    expect(excerpt("**新角色**上线了：*樱庭纱季*，见[说明](https://example.com)和 `设置`")).toBe(
      "新角色上线了：樱庭纱季，见说明和 设置",
    );
  });

  it("drops the marks starting a line: list items, numbers, headings and quotes", () => {
    expect(excerpt("# 更新\n- 第一条\n* 第二条\n1. 第三条\n> 引用")).toBe("更新 第一条 第二条 第三条 引用");
  });

  it("joins the lines and runs of spaces with one space", () => {
    expect(excerpt("  第一段\n\n第二段   还有  ")).toBe("第一段 第二段 还有");
  });

  it("cuts a long body short with an ellipsis", () => {
    const body = "字".repeat(EXCERPT_LENGTH + 10);

    expect(excerpt(body)).toBe(`${"字".repeat(EXCERPT_LENGTH)}…`);
  });

  it("leaves a body exactly as long as an excerpt uncut", () => {
    const body = "字".repeat(EXCERPT_LENGTH);

    expect(excerpt(body)).toBe(body);
  });

  it("drops HTML tags, keeping the words between them", () => {
    expect(excerpt("<div>维护通知</div> <b>今晚</b>")).toBe("维护通知 今晚");
  });

  it("drops the underscores of emphasis, not those within a word", () => {
    expect(excerpt("_新_ 字段 __snake_case__")).toBe("新 字段 snake_case");
  });

  it("keeps the words of an image's description", () => {
    expect(excerpt("![立绘](a.png) 新衣装")).toBe("立绘 新衣装");
  });
});

/** This browser's localStorage, kept in memory. */
function storage(initial: Record<string, string> = {}) {
  const items = new Map(Object.entries(initial));
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => items.get(key) ?? null,
    setItem: (key: string, value: string) => void items.set(key, value),
    removeItem: (key: string) => void items.delete(key),
  });
  return items;
}

afterEach(() => vi.unstubAllGlobals());

const published = (id: string, at: string): Announcement => ({ id, body: id, published_at: at, pinned: false });

describe("what has been read on this device", () => {
  it("is kept for each user apart, and read back as kept", () => {
    const items = storage();

    keepReadUpTo("reader-1", "2026-10-12T08:00:00+00:00");
    keepReadUpTo("reader-2", "2026-10-01T08:00:00+00:00");

    expect(readUpTo("reader-1")).toBe("2026-10-12T08:00:00+00:00");
    expect(readUpTo("reader-2")).toBe("2026-10-01T08:00:00+00:00");
    expect(readUpTo("reader-3")).toBeNull();
    expect(items.get("eidolon.announcementsRead.reader-1")).toBe(JSON.stringify("2026-10-12T08:00:00+00:00"));
  });

  it("is nothing when what is stored is not a time", () => {
    storage({
      "eidolon.announcementsRead.broken-1": "{not json",
      "eidolon.announcementsRead.broken-2": JSON.stringify(42),
      "eidolon.announcementsRead.broken-3": JSON.stringify("yesterday"),
    });

    expect(readUpTo("broken-1")).toBeNull();
    expect(readUpTo("broken-2")).toBeNull();
    expect(readUpTo("broken-3")).toBeNull();
  });

  it("stays for this page when storage cannot be used", () => {
    const unreachable = () => {
      throw new DOMException("denied", "SecurityError");
    };
    vi.stubGlobal("localStorage", { getItem: unreachable, setItem: unreachable, removeItem: unreachable });

    expect(readUpTo("private-1")).toBeNull();
    expect(() => keepReadUpTo("private-1", "2026-10-12T08:00:00+00:00")).not.toThrow();
    expect(readUpTo("private-1")).toBe("2026-10-12T08:00:00+00:00");
  });
});

describe("unread", () => {
  const list = [
    published("c", "2026-10-12T08:00:00+00:00"),
    published("b", "2026-10-10T08:00:00+00:00"),
    published("a", "2026-10-01T08:00:00+00:00"),
  ];

  it("is every announcement when none has been read", () => {
    expect(unread(list, null)).toEqual(new Set(["a", "b", "c"]));
  });

  it("is those published after what was read", () => {
    expect(unread(list, "2026-10-10T08:00:00+00:00")).toEqual(new Set(["c"]));
    expect(unread(list, "2026-10-12T08:00:00+00:00")).toEqual(new Set());
  });

  it("compares the times, not how they are written", () => {
    expect(unread(list, "2026-10-10T17:00:00+09:00")).toEqual(new Set(["c"]));
  });

  it("is none when there are no announcements", () => {
    expect(unread([], null)).toEqual(new Set());
  });
});

describe("marking read", () => {
  it("reads up to the newest announcement listed, so later ones are new", () => {
    const list = [published("b", "2026-10-10T08:00:00+00:00"), published("c", "2026-10-12T08:00:00+00:00")];
    const upTo = newestPublished(list);

    expect(upTo).toBe("2026-10-12T08:00:00+00:00");
    expect(unread([published("d", "2026-10-13T08:00:00+00:00"), ...list], upTo)).toEqual(new Set(["d"]));
  });

  it("has nothing to read up to when there are no announcements", () => {
    expect(newestPublished([])).toBeNull();
  });
});
