// The cards of the play page's first level (.scratch/play-hub spec「卡片注册表」): for each card, its
// name, where it goes (its subpage), when it is shown, what its status line says and whether a dot
// sits by its name. A card is one entry of `CARDS`; the page lays them out (the first across a
// whole row, the rest in a grid) and only asks what is on them. Gifts and achievements are made of
// the gift state, which the first level and the subpages read alike; the calendar (.scratch/calendar
// spec「玩法页的『日历』卡」) of the characters' birthdays, the producer's and the holidays, and is
// there whether affinity and gifts are open or not; the cycles (.scratch/cycle-page spec「玩法页的卡」) of the
// periods the user wrote down, there only while the deployment and the user have cycles on.

import { copy } from "@/i18n";
import { unlockedStages, unseenStages } from "@/lib/achievements";
import { type CalendarEvent, type CalendarView, nextEvent, partsOf } from "@/lib/calendar";
import { type Her, monthDay, soonest } from "@/lib/cycles";
import type { GiftState } from "@/lib/gifts";
import { playHref, type PlaySubpage } from "@/lib/playRoute";

const t = copy.play;

/** What the calendar card is made of: the calendar, with each character's name and nullable birthday. */
export type CalendarCardContext = CalendarView<{ name: string; birthday: string | null }>;

/** What the cycles card is made of: today, every character's records and estimate, and the name of each. */
export type CyclesCardContext = { today: string; hers: readonly Her[]; nameOf: (characterId: string) => string };


/** What the cards are made of: the gift state (null until it has been read), whether draw chances
 * have come that are not yet seen (`newRewards`, the nav's dot), the latest unlock of the
 * combined achievements seen on this device (`achievementsSeenAt`), the calendar's (null until
 * the characters, the profile and the holidays have been read), and how many of this week's jobs
 * are still to be placed (`schedulePending`, lib/schedule's `pendingJobs`; 0 while schedules are
 * off or unread, or this week is not published), the cycles' (`cycles`, null while cycles are off
 * or unread, so the card does not show and then go). */
export type PlayContext = {
  state: GiftState | null;
  newRewards: boolean;
  achievementsSeenAt: string | null;
  calendar: CalendarCardContext | null;
  schedulePending: number;
  cycles: CyclesCardContext | null;
};

/** A card as the page shows it: `status` is empty until the state has been read. */
export type PlayCard = {
  id: PlaySubpage;
  name: string;
  href: string;
  status: string;
  hasDot: boolean;
  /** What a screen reader says of the dot. */
  dotLabel: string;
};

type Definition = {
  id: PlaySubpage;
  name: string;
  isShown: (context: PlayContext) => boolean;
  /** Empty until what it is made of has been read. */
  status: (context: PlayContext) => string;
  hasDot: (context: PlayContext) => boolean;
  dotLabel: string;
};

/** Gifts and achievements are there while affinity and gifts are open; until
 * the state has been read nothing says they are not. */
const isGiftsOpen = ({ state }: PlayContext) => state === null || state.open;

function join(parts: (string | null)[]): string {
  return parts.filter((part) => part !== null).join(t.separator);
}

const CARDS: Definition[] = [
  {
    id: "gifts",
    name: t.cards.gifts.name,
    isShown: isGiftsOpen,
    status: ({ state }) => {
      if (!state) return "";
      const items = state.backpack.reduce((n, held) => n + held.count, 0);
      return join([
        t.cards.gifts.draws(state.draws),
        items > 0 ? t.cards.gifts.backpack(items) : null,
        state.reset_cards > 0 ? t.cards.gifts.resetCards(state.reset_cards) : null,
      ]);
    },
    hasDot: ({ newRewards }) => newRewards,
    dotLabel: t.cards.gifts.dot,
  },
  {
    id: "achievements",
    name: t.cards.achievements.name,
    isShown: isGiftsOpen,
    status: (context) => {
      const { state } = context;
      if (!state) return "";
      const unseen = unseenCount(state, context);
      if (unseen > 0) return t.cards.achievements.unseen(unseen);
      return t.cards.achievements.unlocked(state.achievements ? unlockedStages(state.achievements) : 0);
    },
    hasDot: (context) => context.state !== null && unseenCount(context.state, context) > 0,
    dotLabel: t.cards.achievements.dot,
  },
  {
    id: "calendar",
    name: t.cards.calendar.name,
    isShown: () => true,
    status: ({ calendar, schedulePending }) => {
      if (!calendar) return "";
      return join([schedulePending > 0 ? t.cards.calendar.pending(schedulePending) : null, nextText(calendar)]);
    },
    hasDot: () => false,
    dotLabel: "",
  },
  {
    id: "cycles",
    name: t.cards.cycles.name,
    isShown: ({ cycles }) => cycles !== null,
    status: ({ cycles }) => (cycles ? cyclesText(cycles) : ""),
    hasDot: () => false,
    dotLabel: "",
  },
];

/** The cycles card's 「记过 3 位 · 最近 円香 10月31日」, or what it is for while no one is written down. */
function cyclesText({ today, hers, nameOf }: CyclesCardContext): string {
  const next = soonest(hers, today);
  if (!next) return t.cards.cycles.empty;
  const count = hers.filter((her) => her.records.length > 0).length;
  return t.cards.cycles.status(count, nameOf(next.characterId), monthDay(next.firstDay));
}

/** The calendar card's 「下一个：10月27日 樋口円香的生日」 (「今天：…」 when it is today); null when there is none. */
function nextText(calendar: CalendarCardContext): string | null {
  const found = nextEvent(calendar.today, calendar.data, calendar.shown);
  if (!found) return null;
  const what = eventText(found.event);
  if (found.date === calendar.today) return t.cards.calendar.today(what);
  const { month, day } = partsOf(found.date);
  return t.cards.calendar.next(t.calendar.date(month, day), what);
}

/** An event as the calendar card says it: 「樋口円香的生日」「文化の日」「我的生日」. */
function eventText(event: CalendarEvent<{ name: string }>): string {
  if (event.kind === "character") return t.cards.calendar.birthday(event.character.name);
  if (event.kind === "schedule") return event.job.name;
  return event.kind === "producer" ? t.calendar.mine : event.name;
}

/** How many stages of the combined achievements were unlocked since the last seen on this device. */
function unseenCount(state: GiftState, { achievementsSeenAt }: PlayContext): number {
  return state.achievements ? unseenStages(state.achievements, achievementsSeenAt) : 0;
}

/** The cards to show, top to bottom: no gifts or achievements where affinity and gifts are closed. */
export function playCards(context: PlayContext): PlayCard[] {
  return CARDS.filter((card) => card.isShown(context)).map((card) => ({
    id: card.id,
    name: card.name,
    href: playHref(card.id),
    status: card.status(context),
    hasDot: card.hasDot(context),
    dotLabel: card.dotLabel,
  }));
}

/** A card's name, which is also the title of its subpage. */
export function playTitle(id: PlaySubpage): string {
  return CARDS.find((card) => card.id === id)?.name ?? id;
}
