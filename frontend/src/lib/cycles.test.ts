import { describe, expect, it } from "vitest";

import {
  canShowNextMonth,
  clampDays,
  CYCLE_FILTERS,
  type CycleEstimate,
  cyclesWho,
  dayBar,
  defaultDays,
  filterCounts,
  fullDate,
  type Her,
  herLine,
  isPickable,
  monthMarks,
  shownRecords,
  stripOf,
} from "@/lib/cycles";
import { calendarWho } from "@/lib/schedule";

const TODAY = "2026-10-25";

function estimate(change: Partial<CycleEstimate> = {}): CycleEstimate {
  return {
    cycle: 28,
    period: 5,
    reasons: [],
    periods: [
      { first_day: "2026-10-27", days: 5 },
      { first_day: "2026-11-24", days: 5 },
      { first_day: "2026-12-22", days: 5 },
    ],
    off_by: null,
    today: { kind: "premenstrual" },
    ...change,
  };
}

/** 记过两次的她：9月1日、9月29日各 5 天，推算 10月27日 起。 */
function her(change: Partial<Her> = {}): Her {
  return {
    character_id: "mano",
    records: [
      { id: "r1", first_day: "2026-09-01", days: 5 },
      { id: "r2", first_day: "2026-09-29", days: 5 },
    ],
    estimate: estimate(),
    ...change,
  };
}

function unrecorded(id: string): Her {
  return { character_id: id, records: [], estimate: null };
}

function markOn(date: string, h: Her) {
  const month = { year: Number(date.slice(0, 4)), month: Number(date.slice(5, 7)) };
  const cell = monthMarks(month, TODAY, h).find((c) => c.date === date);
  if (!cell) throw new Error(`${date} 不在这个月`);
  return cell.mark;
}

describe("the marks of a month", () => {
  it("has a square for each day, a week to a row from Monday", () => {
    const cells = monthMarks({ year: 2026, month: 10 }, TODAY, her());
    expect(cells).toHaveLength(35);
    expect(cells[0].date).toBe("2026-09-28");
    expect(cells.find((c) => c.date === TODAY)?.isToday).toBe(true);
  });

  it("marks the recorded periods, the estimated periods and the premenstrual days before each", () => {
    expect(markOn("2026-09-29", her()).kind).toBe("recorded");
    expect(markOn("2026-10-03", her()).kind).toBe("recorded");
    expect(markOn("2026-10-04", her()).kind).toBeNull();
    expect(markOn("2026-10-21", her()).kind).toBeNull();
    expect(markOn("2026-10-22", her()).kind).toBe("premenstrual");
    expect(markOn("2026-10-26", her()).kind).toBe("premenstrual");
    expect(markOn("2026-10-27", her()).kind).toBe("estimated");
    expect(markOn("2026-10-31", her()).kind).toBe("estimated");
    expect(markOn("2026-11-01", her()).kind).toBeNull();
    expect(markOn("2026-11-19", her()).kind).toBe("premenstrual");
    expect(markOn("2026-12-22", her()).kind).toBe("estimated");
  });

  it("writes 「经前」 on the first day of each premenstrual stretch alone", () => {
    expect(markOn("2026-10-22", her()).isPremenstrualStart).toBe(true);
    expect(markOn("2026-10-23", her()).isPremenstrualStart).toBe(false);
    expect(markOn("2026-11-19", her()).isPremenstrualStart).toBe(true);
    expect(markOn("2026-10-27", her()).isPremenstrualStart).toBe(false);
  });

  it("lets a recorded period cover what is estimated", () => {
    const covered = her({
      records: [...her().records, { id: "r3", first_day: "2026-10-20", days: 4 }],
    });
    expect(markOn("2026-10-22", covered).kind).toBe("recorded");
    expect(markOn("2026-10-23", covered).kind).toBe("recorded");
    // 经前剩下的头一天才写「经前」。
    expect(markOn("2026-10-24", covered)).toEqual({ kind: "premenstrual", isFaded: false, isPremenstrualStart: true });
  });

  it("fades what is estimated, never what is recorded, when there is any reason", () => {
    const faded = her({ estimate: estimate({ reasons: ["irregular"] }) });
    expect(markOn("2026-10-27", faded).isFaded).toBe(true);
    expect(markOn("2026-10-22", faded).isFaded).toBe(true);
    expect(markOn("2026-09-29", faded).isFaded).toBe(false);
    expect(markOn("2026-10-27", her()).isFaded).toBe(false);
  });

  it("has no marks for her before anything is written down", () => {
    expect(markOn(TODAY, unrecorded("mano"))).toEqual({ kind: null, isFaded: false, isPremenstrualStart: false });
  });
});

const roster = [
  { id: "mano", name: "櫻木真乃", intro: "" },
  { id: "hiori", name: "風野灯織", intro: "" },
  { id: "madoka", name: "樋口円香", intro: "" },
  { id: "koito", name: "福丸小糸", intro: "" },
];

/** 真乃推算在经前，灯织记过、今天什么都不是，円香和小糸没记过。 */
const hers: Her[] = [
  her(),
  her({ character_id: "hiori", estimate: estimate({ today: null }) }),
  unrecorded("madoka"),
  unrecorded("koito"),
];

const ids = (list: { id: string }[]) => list.map((c) => c.id);

describe("who the avatar strip shows", () => {
  it("counts each of the four", () => {
    expect(filterCounts(hers)).toEqual({ all: 4, recorded: 2, now: 1, unrecorded: 2 });
  });

  it("counts her in her period, recorded or estimated, as now", () => {
    const inPeriod = [
      her({ estimate: estimate({ today: { kind: "recorded", day: 2 } }) }),
      her({ character_id: "hiori", estimate: estimate({ today: { kind: "estimated" } }) }),
    ];
    expect(filterCounts(inPeriod).now).toBe(2);
  });

  it("shows those the filter keeps, in the roster's order", () => {
    const strip = (filter: (typeof CYCLE_FILTERS)[number]) => ids(stripOf(roster, hers, { filter, query: "", picked: "mano" }));
    expect(strip("all")).toEqual(["mano", "hiori", "madoka", "koito"]);
    expect(strip("recorded")).toEqual(["mano", "hiori"]);
    expect(strip("now")).toEqual(["mano"]);
  });

  it("keeps the one picked in the strip even when the filter leaves her out", () => {
    expect(ids(stripOf(roster, hers, { filter: "unrecorded", query: "", picked: "mano" }))).toEqual([
      "mano",
      "madoka",
      "koito",
    ]);
  });

  it("does not filter while searching", () => {
    expect(ids(stripOf(roster, hers, { filter: "recorded", query: "福丸", picked: "mano" }))).toEqual([
      "mano",
      "koito",
    ]);
    expect(ids(stripOf(roster, hers, { filter: "recorded", query: "円香", picked: "hiori" }))).toEqual(["hiori", "madoka"]);
  });
});

describe("her line", () => {
  it("asks to write one down before anything is", () => {
    expect(herLine(unrecorded("mano"), TODAY)).toBe("还没记过。记下一次，这里就开始推算。");
  });

  it("says the day of a recorded period", () => {
    expect(herLine(her({ estimate: estimate({ today: { kind: "recorded", day: 3 } }) }), TODAY)).toBe("经期第 3 天");
  });

  it("says she is estimated in her period", () => {
    const h = her({ estimate: estimate({ today: { kind: "estimated" } }) });
    expect(herLine(h, TODAY)).toBe("推算在经期");
  });

  it("says she is estimated premenstrual, and when the period comes", () => {
    expect(herLine(her(), TODAY)).toBe("推算在经前 · 10月27日 来");
  });

  it("says when the period was estimated to come, past it and nothing written down", () => {
    const late = her({
      estimate: estimate({
        reasons: ["late"],
        today: null,
        periods: [
          { first_day: "2026-10-12", days: 5 },
          { first_day: "2026-11-09", days: 5 },
          { first_day: "2026-12-07", days: 5 },
        ],
      }),
    });
    expect(herLine(late, TODAY)).toBe("推算 10月12日 来，还没记下");
  });

  it("says otherwise when the next period comes and the premenstrual days begin", () => {
    const h = her({
      estimate: estimate({
        today: null,
        periods: [
          { first_day: "2026-10-31", days: 5 },
          { first_day: "2026-11-28", days: 5 },
          { first_day: "2026-12-26", days: 5 },
        ],
      }),
    });
    expect(herLine(h, TODAY)).toBe("下次经期推算在 10月31日（还有 6 天），经前从 10月26日 起。");
  });
});

describe("the line of the day picked", () => {
  it("says how to begin before a day is picked", () => {
    expect(dayBar(null, her(), TODAY)).toEqual({ text: "点一天来记下她这次经期的第一天。", action: null });
  });

  it("says what the day is and offers it as a first day", () => {
    expect(dayBar("2026-10-23", her(), TODAY)).toEqual({ text: "10月23日 · 推算的经前", action: { kind: "first" } });
    expect(dayBar("2026-10-10", her(), TODAY)).toEqual({ text: "10月10日", action: { kind: "first" } });
    expect(dayBar(TODAY, her(), TODAY).action).toEqual({ kind: "first" });
  });

  it("will not write down a day still to come", () => {
    expect(dayBar("2026-10-28", her(), TODAY)).toEqual({ text: "10月28日 · 推算的经期", action: { kind: "future" } });
  });

  it("offers to change the period a recorded day is in", () => {
    expect(dayBar("2026-10-01", her(), TODAY)).toEqual({
      text: "10月1日 · 记下的经期",
      action: { kind: "edit", record: { id: "r2", first_day: "2026-09-29", days: 5 } },
    });
  });
});

describe("the periods written down", () => {
  const records = (n: number) =>
    Array.from({ length: n }, (_, i) => ({
      id: `r${i}`,
      first_day: `2026-0${i + 1}-0${i + 1}`,
      days: 5,
    }));

  it("puts the newest first, with the days since the one before", () => {
    const { rows } = shownRecords(
      [
        { id: "a", first_day: "2026-08-03", days: 5 },
        { id: "b", first_day: "2026-09-01", days: 4 },
      ],
      false,
    );
    expect(rows.map((row) => [row.record.id, row.text])).toEqual([
      ["b", "4 天 · 隔 29 天"],
      ["a", "5 天"],
    ]);
  });

  it("shows the latest 3, and every one when there is only one more", () => {
    expect(shownRecords(records(3), false)).toMatchObject({ toggle: null });
    expect(shownRecords(records(4), false).rows).toHaveLength(4);
    expect(shownRecords(records(4), false).toggle).toBeNull();
    const five = shownRecords(records(5), false);
    expect(five.rows.map((row) => row.record.id)).toEqual(["r4", "r3", "r2"]);
    expect(five.toggle).toBe("展开全部 5 次");
  });

  it("shows them all when unfolded, with a way to fold them again", () => {
    const five = shownRecords(records(5), true);
    expect(five.rows).toHaveLength(5);
    expect(five.toggle).toBe("收起");
  });
});

describe("writing one down", () => {
  it("starts from the estimated period's days, 5 before any", () => {
    expect(defaultDays(estimate({ period: 6 }))).toBe(6);
    expect(defaultDays(null)).toBe(5);
  });

  it("keeps the days between 1 and 10", () => {
    expect(clampDays(0)).toBe(1);
    expect(clampDays(1)).toBe(1);
    expect(clampDays(10)).toBe(10);
    expect(clampDays(11)).toBe(10);
  });

  it("picks no day after today in the little calendar", () => {
    expect(isPickable(TODAY, TODAY)).toBe(true);
    expect(isPickable("2026-10-26", TODAY)).toBe(false);
    expect(canShowNextMonth({ year: 2026, month: 9 }, TODAY)).toBe(true);
    expect(canShowNextMonth({ year: 2026, month: 10 }, TODAY)).toBe(false);
  });

  it("writes the day out in full whatever the browser's language", () => {
    expect(fullDate(TODAY)).toBe("2026年10月25日 周日");
  });
});

describe("who is picked from the address", () => {
  const roster = ["mano", "hiori", "madoka"];

  it("picks the one the address names", () => {
    expect(cyclesWho(calendarWho({ who: "madoka" }), roster)).toBe("madoka");
  });

  it("picks the first in the roster when it names none, or one it does not know", () => {
    expect(cyclesWho(calendarWho({}), roster)).toBe("mano");
    expect(cyclesWho(calendarWho({ who: "nobody" }), roster)).toBe("mano");
    expect(cyclesWho("mano", [])).toBeNull();
  });
});
