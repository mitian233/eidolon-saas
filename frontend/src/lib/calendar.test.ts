import { afterEach, describe, expect, it, vi } from "vitest";

import {
  calendarKinds,
  calendarMode,
  cellLines,
  type CalendarData,
  type CalendarEvent,
  type CalendarKind,
  eventsOn,
  keepCalendarMode,
  monthCells,
  monthOf,
  nextEvent,
  shiftMonth,
  todayIn,
} from "@/lib/calendar";

type Idol = { id: string; name: string; birthday: string | null };

const MANO: Idol = { id: "mano", name: "櫻木真乃", birthday: "04-25" };
const MADOKA: Idol = { id: "madoka", name: "樋口円香", birthday: "10-27" };
const KOITO: Idol = { id: "koito", name: "福丸小糸", birthday: "10-27" };
const LEAP: Idol = { id: "leap", name: "閏年子", birthday: "02-29" };

const ALL: CalendarKind[] = ["character", "producer", "holiday", "schedule"];

function data(change: Partial<CalendarData<Idol>> = {}): CalendarData<Idol> {
  return {
    characters: [MANO, MADOKA, KOITO],
    producerBirthday: { month: 11, day: 3 },
    holidays: [
      { date: "2026-11-03", name: "文化の日" },
      { date: "2026-11-23", name: "勤労感謝の日" },
      { date: "2027-01-01", name: "元日" },
    ],
    ...change,
  };
}

/** 一件事写成一个词：角色写 id，我的生日写「me」，节假日写名字，日程写「谁:工作名」。 */
const word = (e: CalendarEvent<Idol>) =>
  e.kind === "character"
    ? e.character.id
    : e.kind === "producer"
      ? "me"
      : e.kind === "schedule"
        ? `${e.job.character.id}:${e.job.name}`
        : e.name;

/** 这一天的事，一件一个词。 */
const on = (date: string, d = data(), shown: CalendarKind[] = ALL) => eventsOn(date, d, shown).map(word);

describe("某一天的事", () => {
  it("没事的日子什么都没有", () => {
    expect(on("2026-10-26")).toEqual([]);
  });

  it("两位同一天生日都列出来，按偶像顺序", () => {
    expect(on("2026-10-27")).toEqual(["madoka", "koito"]);
    expect(on("2026-10-27", data({ characters: [KOITO, MADOKA] }))).toEqual(["koito", "madoka"]);
  });

  it("没设生日的角色不出现在生日里", () => {
    expect(on("2026-04-25", data({ characters: [{ ...MANO, birthday: null }, MADOKA] }))).toEqual([]);
  });

  it("角色生日、我的生日、节假日碰在一天时按这个顺序", () => {
    const d = data({ characters: [{ ...MANO, birthday: "11-03" }] });

    expect(on("2026-11-03", d)).toEqual(["mano", "me", "文化の日"]);
  });

  it("生日每年都在，节假日只在给的那一天", () => {
    expect(on("2031-04-25")).toEqual(["mano"]);
    expect(on("2027-11-03")).toEqual(["me"]);
  });

  it("2 月 29 日的生日在没有 29 日的年份落在 28 日，闰年照旧", () => {
    const d = data({ characters: [LEAP], producerBirthday: { month: 2, day: 29 } });

    expect(on("2027-02-28", d)).toEqual(["leap", "me"]);
    expect(on("2028-02-28", d)).toEqual([]);
    expect(on("2028-02-29", d)).toEqual(["leap", "me"]);
  });

  it("制作人没生日时没有我的生日", () => {
    expect(on("2026-11-03", data({ producerBirthday: null }))).toEqual(["文化の日"]);
  });

  it("只列开着的几类", () => {
    const d = data({ characters: [{ ...MANO, birthday: "11-03" }] });

    expect(on("2026-11-03", d, ["holiday"])).toEqual(["文化の日"]);
    expect(on("2026-11-03", d, ["character", "producer"])).toEqual(["mano", "me"]);
    expect(on("2026-11-03", d, [])).toEqual([]);
  });

  it("日程排在节假日后面，照给的顺序；筛掉「日程」时没有", () => {
    const job = (character: Idol, name: string, date = "2026-11-03") => ({
      date,
      character,
      jobId: `2026-11-02-${name}`,
      name,
      slotsText: "下午",
      isSaved: true,
    });
    const d = data({ jobs: [job(MADOKA, "拍摄广告"), job(MANO, "舞蹈课"), job(MANO, "吃饭", "2026-11-04")] });

    expect(on("2026-11-03", d)).toEqual(["me", "文化の日", "madoka:拍摄广告", "mano:舞蹈课"]);
    expect(on("2026-11-04", d)).toEqual(["mano:吃饭"]);
    expect(on("2026-11-03", d, ["character", "producer", "holiday"])).toEqual(["me", "文化の日"]);
  });
});

describe("有哪几类", () => {
  it("四类；制作人没生日时没有我的生日，日程关着时没有日程", () => {
    expect(calendarKinds({ month: 1, day: 1 }, true)).toEqual(["character", "producer", "holiday", "schedule"]);
    expect(calendarKinds(null, true)).toEqual(["character", "holiday", "schedule"]);
    expect(calendarKinds({ month: 1, day: 1 }, false)).toEqual(["character", "producer", "holiday"]);
  });
});

describe("下一个", () => {
  const next = (today: string, d = data(), shown: CalendarKind[] = ALL) => {
    const found = nextEvent(today, d, shown);
    if (!found) return null;
    const { date, event } = found;
    return [date, word(event)];
  };

  it("找今天以后最近的一件", () => {
    expect(next("2026-10-23")).toEqual(["2026-10-27", "madoka"]);
    expect(next("2026-10-28")).toEqual(["2026-11-03", "me"]);
  });

  it("今天就有时是今天的", () => {
    expect(next("2026-10-27")).toEqual(["2026-10-27", "madoka"]);
  });

  it("同一天几件取排在前的", () => {
    expect(next("2026-10-28", data({ characters: [{ ...MANO, birthday: "11-03" }] }))).toEqual(["2026-11-03", "mano"]);
  });

  it("跨年能找到明年的", () => {
    expect(next("2026-11-24", data(), ["holiday"])).toEqual(["2027-01-01", "元日"]);
    expect(next("2026-11-24", data(), ["character"])).toEqual(["2027-04-25", "mano"]);
  });

  it("全筛掉、或者什么都没有时没有", () => {
    expect(next("2026-10-23", data(), [])).toBeNull();
    expect(next("2026-10-23", data({ producerBirthday: null }), ["producer"])).toBeNull();
    expect(next("2026-11-24", data({ characters: [], producerBirthday: null, holidays: [] }))).toBeNull();
  });
});

describe("今天", () => {
  it("按给的时区算", () => {
    const at = new Date("2026-10-26T15:30:00Z");

    expect(todayIn("Asia/Tokyo", at)).toBe("2026-10-27");
    expect(todayIn("Asia/Shanghai", at)).toBe("2026-10-26");
  });
});

describe("某个月的格子", () => {
  it("周一起，首尾补上前后月的天，凑满整周", () => {
    const cells = monthCells({ year: 2026, month: 10 }, "2026-10-23");

    expect(cells).toHaveLength(35);
    expect(cells.slice(0, 4).map((c) => [c.date, c.isInMonth])).toEqual([
      ["2026-09-28", false],
      ["2026-09-29", false],
      ["2026-09-30", false],
      ["2026-10-01", true],
    ]);
    expect(cells.slice(-2).map((c) => [c.date, c.isInMonth])).toEqual([
      ["2026-10-31", true],
      ["2026-11-01", false],
    ]);
  });

  it("行数按这个月要几周：四周、六周", () => {
    expect(monthCells({ year: 2027, month: 2 }, "2026-10-23")).toHaveLength(28);
    expect(monthCells({ year: 2027, month: 2 }, "2026-10-23")[0].date).toBe("2027-02-01");
    expect(monthCells({ year: 2026, month: 8 }, "2026-10-23")).toHaveLength(42);
  });

  it("只有今天那一格是今天，补上的天也算", () => {
    const today = (month: number, date: string) =>
      monthCells({ year: 2026, month }, date)
        .filter((c) => c.isToday)
        .map((c) => c.date);

    expect(today(10, "2026-10-23")).toEqual(["2026-10-23"]);
    expect(today(10, "2026-11-01")).toEqual(["2026-11-01"]);
    expect(today(10, "2026-12-01")).toEqual([]);
  });
});

describe("翻月", () => {
  it("今天所在的月；往前往后翻，跨年也行", () => {
    expect(monthOf("2026-10-23")).toEqual({ year: 2026, month: 10 });
    expect(shiftMonth({ year: 2026, month: 12 }, 1)).toEqual({ year: 2027, month: 1 });
    expect(shiftMonth({ year: 2026, month: 1 }, -1)).toEqual({ year: 2025, month: 12 });
  });
});

describe("电脑上一格最多三行", () => {
  const lines = (n: number) => {
    const { events, more } = cellLines(Array.from({ length: n }, (_, i) => i));
    return [events, more];
  };

  it("三件放得下就全写", () => {
    expect(lines(3)).toEqual([[0, 1, 2], 0]);
  });

  it("超过三件时写前两件，第三行是还有几项", () => {
    expect(lines(4)).toEqual([[0, 1], 2]);
  });
});

describe("月视图还是周视图，记在本机", () => {
  afterEach(() => vi.unstubAllGlobals());

  function storage(initial: Record<string, string> = {}) {
    const items = new Map(Object.entries(initial));
    vi.stubGlobal("localStorage", {
      getItem: (key: string) => items.get(key) ?? null,
      setItem: (key: string, value: string) => void items.set(key, value),
      removeItem: (key: string) => void items.delete(key),
    });
    return items;
  }

  it("按用户分开记着上次选的", () => {
    const items = storage();

    keepCalendarMode("user-1", "month");

    expect(calendarMode("user-1")).toBe("month");
    expect(calendarMode("user-2")).toBe("week");
    expect(items.get("eidolon.calendarMode.user-1")).toBe("month");
    keepCalendarMode("user-1", "week");
    expect(calendarMode("user-1")).toBe("week");
  });

  it("没选过、或者存的认不得时是周视图", () => {
    storage({ "eidolon.calendarMode.odd": "day" });

    expect(calendarMode("user-1")).toBe("week");
    expect(calendarMode("odd")).toBe("week");
  });

  it("存不进去时只在这次页面里记着", () => {
    const unreachable = () => {
      throw new DOMException("denied", "SecurityError");
    };
    vi.stubGlobal("localStorage", { getItem: unreachable, setItem: unreachable, removeItem: unreachable });

    expect(calendarMode("private-1")).toBe("week");
    expect(() => keepCalendarMode("private-1", "month")).not.toThrow();
    expect(calendarMode("private-1")).toBe("month");
  });
});
