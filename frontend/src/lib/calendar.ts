// The calendar's arithmetic (.scratch/calendar spec「日历子页」「怎么算」): which days carry what,
// out of four kinds — the characters' birthdays, the producer's own (「我的生日」), Japan's
// holidays and, while schedules are on, the jobs placed this week and next
// (.scratch/schedule spec「界面」; lib/schedule's `dayJobs` gives them, dated). Birthdays come back every year and are worked out here; holidays are given, a year at
// a time, as the backend lists them. February 29 falls on February 28 in a year without it, as the
// producer's birthday does where she congratulates him. The page only draws what these say.
// Which of the month and the week view this device last showed is kept here too (at the end).
//
// A date is an ISO day, `YYYY-MM-DD`, in no time zone: the producer's today is `todayIn` his.

import type { Birthday } from "@/lib/api";

/** The kinds of day, in the order the events of one day are listed. */
export const CALENDAR_KINDS = ["character", "producer", "holiday", "schedule"] as const;

export type CalendarKind = (typeof CALENDAR_KINDS)[number];

/** A holiday as the holidays endpoint gives it: `date` is `YYYY-MM-DD`, `name` the Japanese name. */
export type Holiday = { date: string; name: string };

/** A job placed on a day, as the month view shows it: whose, the job's id and name, the slots it
 * takes as written (「下午」「上午到下午」「一整天」), and whether it is saved or a draft. */
export type DayJob<C> = {
  date: string;
  character: C;
  jobId: string;
  name: string;
  slotsText: string;
  isSaved: boolean;
};

/** What the calendar is worked out from. `characters` each with her `birthday` as `MM-DD`, or null
 * when unset; `producerBirthday` null when he has not set one; `holidays` of the years read so far;
 * `jobs` placed, in the order a day lists them (none where schedules are off). */
export type CalendarData<C extends { birthday: string | null }> = {
  characters: readonly C[];
  producerBirthday: Birthday | null;
  holidays: readonly Holiday[];
  jobs?: readonly DayJob<C>[];
};

/** The calendar as a page shows it: the producer's `today` (in his time zone), the data and the
 * kinds shown on this device. */
export type CalendarView<C extends { birthday: string | null }> = {
  today: string;
  data: CalendarData<C>;
  shown: readonly CalendarKind[];
};

/** One thing on a day: her birthday, the producer's, a holiday, or a job placed. */
export type CalendarEvent<C> =
  | { kind: "character"; character: C }
  | { kind: "producer" }
  | { kind: "holiday"; name: string }
  | { kind: "schedule"; job: DayJob<C> };

/** The kinds there are: no 「我的生日」 while the producer has no birthday, no 「日程」 while
 * schedules are off. */
export function calendarKinds(producerBirthday: Birthday | null, hasSchedule: boolean): CalendarKind[] {
  return CALENDAR_KINDS.filter(
    (kind) => (kind !== "producer" || producerBirthday !== null) && (kind !== "schedule" || hasSchedule),
  );
}

/** The events on `date` of the kinds `shown`: her birthdays (in the idols' order), then the
 * producer's, then the holiday, then the jobs. */
export function eventsOn<C extends { birthday: string | null }>(
  date: string,
  data: CalendarData<C>,
  shown: readonly CalendarKind[],
): CalendarEvent<C>[] {
  const { year } = partsOf(date);
  const events: CalendarEvent<C>[] = [];
  if (shown.includes("character")) {
    for (const character of data.characters) {
      if (character.birthday === null) continue;
      const [month, day] = character.birthday.split("-").map(Number);
      if (birthdayIn(year, month, day) === date) events.push({ kind: "character", character });
    }
  }
  const mine = data.producerBirthday;
  if (shown.includes("producer") && mine && birthdayIn(year, mine.month, mine.day) === date) {
    events.push({ kind: "producer" });
  }
  if (shown.includes("holiday")) {
    for (const holiday of data.holidays) if (holiday.date === date) events.push({ kind: "holiday", name: holiday.name });
  }
  if (shown.includes("schedule")) {
    for (const job of data.jobs ?? []) if (job.date === date) events.push({ kind: "schedule", job });
  }
  return events;
}

/** The first event on `today` or after, of the kinds `shown`, within a year; null when there is
 * none. Holidays are only found in the years `data` has. */
export function nextEvent<C extends { birthday: string | null }>(
  today: string,
  data: CalendarData<C>,
  shown: readonly CalendarKind[],
): { date: string; event: CalendarEvent<C> } | null {
  for (let date = today, i = 0; i <= 366; date = addDays(date, 1), i++) {
    const [event] = eventsOn(date, data, shown);
    if (event) return { date, event };
  }
  return null;
}

/** A month of a year; `month` runs from 1 to 12. */
export type CalendarMonth = { year: number; month: number };

/** One square of the month view: its day, whether it is in the month shown (the weeks are filled
 * out with the days of the months either side) and whether it is the producer's today. */
export type CalendarCell = { date: string; isInMonth: boolean; isToday: boolean };

/** The month `date` is in. */
export function monthOf(date: string): CalendarMonth {
  const { year, month } = partsOf(date);
  return { year, month };
}

/** The month `step` months after `from` (before it when negative). */
export function shiftMonth(from: CalendarMonth, step: number): CalendarMonth {
  const at = new Date(Date.UTC(from.year, from.month - 1 + step, 1));
  return { year: at.getUTCFullYear(), month: at.getUTCMonth() + 1 };
}

/** The squares of `shown`, a week to a row from Monday to Sunday, as many weeks as the month takes. */
export function monthCells(shown: CalendarMonth, today: string): CalendarCell[] {
  const first = `${shown.year}-${pad(shown.month)}-01`;
  const lead = (partsOf(first).weekday + 6) % 7;
  const days = new Date(Date.UTC(shown.year, shown.month, 0)).getUTCDate();
  return Array.from({ length: Math.ceil((lead + days) / 7) * 7 }, (_, i) => {
    const date = addDays(first, i - lead);
    return { date, isInMonth: i >= lead && i < lead + days, isToday: date === today };
  });
}

/** How many lines a square of the month view has on a computer. */
const CELL_LINES = 3;

/** What a square of the month view writes on a computer: every event when they fit in its three
 * lines; otherwise the first two, and `more` for the 「还有 n 项」 on the third. */
export function cellLines<E>(events: readonly E[]): { events: E[]; more: number } {
  if (events.length <= CELL_LINES) return { events: [...events], more: 0 };
  return { events: events.slice(0, CELL_LINES - 1), more: events.length - (CELL_LINES - 1) };
}

/** Today's date where the clock reads `now` in `timeZone`. */
export function todayIn(timeZone: string, now: Date): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone }).format(now);
}

/** The year, month, day and weekday (0 is Sunday) of an ISO day. */
export function partsOf(date: string): { year: number; month: number; day: number; weekday: number } {
  const [year, month, day] = date.split("-").map(Number);
  return { year, month, day, weekday: new Date(Date.UTC(year, month - 1, day)).getUTCDay() };
}

/** The day `days` after `date` (before it when negative). */
export function addDays(date: string, days: number): string {
  const { year, month, day } = partsOf(date);
  return new Date(Date.UTC(year, month - 1, day + days)).toISOString().slice(0, 10);
}

/** Where a birthday of `month`/`day` falls in `year`: February 29 on February 28 in a year without it. */
function birthdayIn(year: number, month: number, day: number): string {
  const isLeap = new Date(Date.UTC(year, 1, 29)).getUTCMonth() === 1;
  const fallsOn = month === 2 && day === 29 && !isLeap ? 28 : day;
  return `${year}-${pad(month)}-${pad(fallsOn)}`;
}

function pad(n: number): string {
  return String(n).padStart(2, "0");
}

// The month view or the week view (.scratch/schedule spec「界面」): while schedules are on the
// header can switch them, and the one last chosen is kept on this device alone, as the filter is:
// in localStorage, a user apart (key eidolon.calendarMode.<user ID>); the week view when none was
// chosen, or what is kept cannot be read or is not a view; only for this page when it cannot be kept.

/** Which view the calendar subpage shows. */
export type CalendarMode = "month" | "week";

function modeKey(userId: string): string {
  return `eidolon.calendarMode.${userId}`;
}

/** What could not be kept, for this page. */
const modeThisPage = new Map<string, CalendarMode>();

/** The view this user last chose on this device; the week view by default. */
export function calendarMode(userId: string): CalendarMode {
  const kept = modeThisPage.get(userId);
  if (kept) return kept;
  let stored: string | null = null;
  try {
    stored = localStorage.getItem(modeKey(userId));
  } catch {
    stored = null;
  }
  return stored === "month" ? "month" : "week";
}

/** Keep the view this user chose. */
export function keepCalendarMode(userId: string, mode: CalendarMode): void {
  try {
    localStorage.setItem(modeKey(userId), mode);
  } catch {
    // No storage: kept for this page alone.
    modeThisPage.set(userId, mode);
  }
}
