import { describe, expect, it } from "vitest";
import type { Message } from "@/lib/api";
import {
  conversationLog,
  emptyLog,
  type ConversationLog,
  type LogAction,
} from "@/lib/conversationLog";

function message(id: number, role: Message["role"], text: string): Message {
  return role === "user"
    ? { id, role, text, ja: null, zh: null, segments: [], created_at: "2026-09-26T00:00:00Z", affinity: null }
    : {
        id,
        role,
        text: null,
        ja: text,
        zh: `（${text}）`,
        segments: [{ ja: text, zh: `（${text}）` }],
        created_at: "2026-09-26T00:00:00Z",
        affinity: null,
      };
}

/** When the user's words were sent or heard, as LiveConversation stamps them. */
const NOW = "2026-09-28T08:49:00.000Z";

function delta(segment: number, lang: "ja" | "zh" | "text", text: string): LogAction {
  return { type: "delta", segment, lang, text };
}

function play(actions: LogAction[], from: ConversationLog = emptyLog): ConversationLog {
  return actions.reduce(conversationLog, from);
}

const history = play([
  { type: "loaded", messages: [message(1, "user", "早上好"), message(2, "character", "おはよう")] },
]);

describe("conversationLog", () => {
  it("shows the recorded messages it is loaded with, one entry each, dated when recorded", () => {
    expect(history.turn).toBeNull();
    expect(history.entries).toEqual([
      { kind: "user", key: "m1", text: "早上好", at: "2026-09-26T00:00:00Z" },
      {
        kind: "character",
        key: "m2",
        segments: [{ ja: "おはよう", zh: "（おはよう）" }],
        pending: false,
        at: "2026-09-26T00:00:00Z",
        affinity: null,
      },
    ]);
  });

  it("replaces everything, including a turn in progress, when loaded again", () => {
    const log = play(
      [
        { type: "submitted", text: "你好", at: NOW },
        { type: "loaded", messages: [] },
      ],
      history,
    );
    expect(log).toEqual(emptyLog);
  });

  it("shows a typed turn at once and confirms it on `user` without a second copy", () => {
    const submitted = play([{ type: "submitted", text: "你好", at: NOW }], history);
    expect(submitted.turn?.confirmed).toBe(false);

    const log = conversationLog(submitted, { type: "user", text: "你好", at: "2026-09-28T08:49:05.000Z" });
    expect(log.turn?.confirmed).toBe(true);
    // Dated when it was typed; the backend taking it up does not change that.
    expect(log.entries.slice(2)).toEqual([
      { kind: "user", key: log.turn?.userKey, text: "你好", at: NOW },
      { kind: "character", key: log.turn?.replyKey, segments: [], pending: true, at: NOW, affinity: null },
    ]);
  });

  it("opens a turn on `user` when nothing was typed, as in a call", () => {
    const log = play([{ type: "user", text: "在吗", at: NOW }], history);
    expect(log.turn?.confirmed).toBe(true);
    expect(log.entries).toHaveLength(4);
    expect(log.entries[2]).toMatchObject({ kind: "user", text: "在吗", at: NOW });
    expect(log.entries[3]).toMatchObject({ kind: "character", segments: [], pending: true });
  });

  it("merges deltas by segment and language, each language adding up on its own", () => {
    const log = play(
      [
        { type: "user", text: "在吗", at: NOW },
        delta(0, "ja", "いる"),
        delta(0, "zh", "在"),
        delta(0, "ja", "よ"),
        delta(1, "ja", "どうした"),
        delta(0, "zh", "哦"),
        delta(1, "zh", "怎么了"),
      ],
      history,
    );
    expect(log.entries[3]).toMatchObject({
      segments: [
        { ja: "いるよ", zh: "在哦" },
        { ja: "どうした", zh: "怎么了" },
      ],
      pending: true,
    });
  });

  it("merges plain-language deltas into the primary text, subtitle empty", () => {
    const log = play(
      [
        { type: "user", text: "你好", at: NOW },
        delta(0, "text", "你好，"),
        delta(0, "text", "今天过得怎么样？"),
      ],
      history,
    );
    expect(log.entries[3]).toMatchObject({
      segments: [{ ja: "你好，今天过得怎么样？", zh: "" }],
      pending: true,
    });
  });

  it("swaps the reply for the recorded one, dated when recorded and with how it changed her affinity, on `done` and ends the turn", () => {
    const affinity = { up: true, tier_changed: false, tier: "trust", cooldown: false, thawed: false } as const;
    const recorded = { ...message(4, "character", "いるよ"), created_at: "2026-09-28T08:49:30Z", affinity };
    const log = play(
      [
        { type: "submitted", text: "在吗", at: NOW },
        { type: "user", text: "在吗", at: NOW },
        delta(0, "ja", "いる"),
        { type: "done", message: recorded, affinity: null },
      ],
      history,
    );
    expect(log.turn).toBeNull();
    expect(log.entries).toHaveLength(4);
    expect(log.entries[2]).toMatchObject({ kind: "user", text: "在吗", at: NOW });
    expect(log.entries[3]).toEqual({
      kind: "character",
      key: "m4",
      segments: recorded.segments,
      pending: false,
      at: "2026-09-28T08:49:30Z",
      affinity,
    });
  });

  it("takes the turn in progress back off the log on `error` and `interrupted`", () => {
    for (const end of [
      { type: "error", message: "角色暂时无法回复，请稍后再试。" },
      { type: "interrupted" },
    ] as LogAction[]) {
      for (const opening of [
        [{ type: "submitted", text: "你好", at: NOW }],
        [{ type: "submitted", text: "你好", at: NOW }, { type: "user", text: "你好", at: NOW }, delta(0, "ja", "こん")],
        [{ type: "user", text: "你好", at: NOW }, delta(0, "ja", "こん")],
      ] as LogAction[][]) {
        const what = `${opening.map((a) => a.type).join(", ")}, then ${end.type}`;
        expect(play([...opening, end], history), what).toEqual(history);
      }
    }
  });

  it("leaves the log alone on `delta`, `done`, `error` and `interrupted` with no turn in progress", () => {
    for (const action of [
      delta(0, "ja", "いる"),
      { type: "done", message: message(9, "character", "いるよ"), affinity: null },
      { type: "error", message: "角色暂时无法回复，请稍后再试。" },
      { type: "interrupted" },
    ] as LogAction[]) {
      expect(conversationLog(history, action), action.type).toBe(history);
    }
  });

  it("keeps two turns in a row apart", () => {
    const log = play(
      [
        { type: "user", text: "一", at: NOW },
        delta(0, "ja", "いち"),
        { type: "done", message: message(4, "character", "いち"), affinity: null },
        { type: "user", text: "二", at: NOW },
        delta(0, "ja", "に"),
        { type: "done", message: message(6, "character", "に"), affinity: null },
      ],
      history,
    );
    expect(log.turn).toBeNull();
    expect(log.entries.map((e) => (e.kind === "character" ? e.segments[0].ja : e.kind === "user" ? e.text : e.event))).toEqual([
      "早上好",
      "おはよう",
      "一",
      "いち",
      "二",
      "に",
    ]);
    expect(new Set(log.entries.map((e) => e.key)).size).toBe(6);
  });

  it("drops a reply cut off halfway when the call is hung up or drops", () => {
    const log = play(
      [
        { type: "user", text: "一", at: NOW },
        { type: "done", message: message(4, "character", "いち"), affinity: null },
        { type: "user", text: "二", at: NOW },
        delta(0, "ja", "に"),
        { type: "interrupted" },
      ],
      history,
    );
    expect(log.turn).toBeNull();
    expect(log.entries).toHaveLength(4);
    expect(log.entries.every((e) => e.kind !== "character" || !e.pending)).toBe(true);
  });

  it("gives a new turn keys no entry shown with it has, after an earlier turn was dropped", () => {
    const log = play(
      [
        { type: "user", text: "一", at: NOW },
        { type: "done", message: message(4, "character", "いち"), affinity: null },
        { type: "user", text: "二", at: NOW },
        { type: "interrupted" },
        { type: "user", text: "三", at: NOW },
      ],
      history,
    );
    expect(new Set(log.entries.map((e) => e.key)).size).toBe(log.entries.length);
  });

  it("replaces the turn in progress, subtitles shown included, when a follow-on joins it", () => {
    const followedOn = play(
      [
        { type: "user", text: "一", at: NOW },
        delta(0, "ja", "い"),
        delta(0, "zh", "（一）"),
        { type: "user", text: "一\n二", at: NOW },
      ],
      history,
    );
    expect(followedOn.entries).toHaveLength(4);
    expect(followedOn.entries[2]).toMatchObject({ kind: "user", text: "一\n二" });
    expect(followedOn.entries[3]).toMatchObject({ segments: [], pending: true });

    const log = play(
      [delta(0, "ja", "に"), { type: "done", message: message(4, "character", "に"), affinity: null }],
      followedOn,
    );
    expect(log.entries.slice(2).map((e) => e.kind)).toEqual(["user", "character"]);
    expect(log.entries[3]).toMatchObject({ segments: [{ ja: "に", zh: "（に）" }], pending: false });
  });

  it("shows only what `done` carries of a reply the user interrupted halfway", () => {
    const log = play(
      [
        { type: "user", text: "一", at: NOW },
        delta(0, "ja", "いち"),
        delta(0, "zh", "（いち）"),
        delta(1, "ja", "に"),
        { type: "done", message: message(4, "character", "いち"), affinity: null },
      ],
      history,
    );
    expect(log.entries[3]).toMatchObject({
      segments: [{ ja: "いち", zh: "（いち）" }],
      pending: false,
    });
  });

});
