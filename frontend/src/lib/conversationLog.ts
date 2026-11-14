// The conversation page's log: what it shows of the conversation, kept up to date from
// the same turn events whether the turn is typed or spoken in a call.

import type { AffinityChange } from "@/lib/affinity";
import type { ConversationEvent, Recorded, Segment, TurnEvent } from "@/lib/api";
import { type EventShown, unwellOf } from "@/lib/conversationEvents";

/** One message or conversation event shown, or her reach-out, shown as her reply is but marked
 * `reachOut` (GLOSSARY.md「搭话」). `at` (ISO) is when it was recorded; for the turn
 * under way, when the user sent or said the words, which the reply shares until it is recorded.
 * Her reply keeps how the turn changed her affinity, once recorded, and a gift record how the
 * gift did; null where it did not. A gift record keeps the gift's name too, and her being unwell
 * since when (`EventShown`). */
export type Entry =
  | { kind: "user"; key: string; text: string; at: string }
  | ({ kind: "event"; key: string; at: string; affinity: AffinityChange | null } & EventShown)
  | {
      kind: "character";
      key: string;
      segments: Segment[];
      pending: boolean;
      at: string;
      affinity: AffinityChange | null;
    };

/** The exchange under way: the user's words and the reply, both the last entries shown.
 * A turn the user typed is unconfirmed until the backend's `user` event takes it up. */
export type Turn = { confirmed: boolean; userKey: string; replyKey: string };

export type ConversationLog = { entries: Entry[]; turn: Turn | null };

export type LogAction =
  /** The conversation was opened or started: show its record. */
  | { type: "loaded"; messages: Recorded[] }
  /** The user typed something outside a call, at `at`; show it before the backend takes it up. */
  | { type: "submitted"; text: string; at: string }
  /** The backend took up the user's words, heard at `at`; words typed keep the time they were sent. */
  | (Extract<TurnEvent, { type: "user" }> & { at: string })
  | Exclude<TurnEvent, { type: "user" | "looking-up" }>
  /** The turn ended without `done` or `error`: the user hung up, the call dropped, or
   * the text turn's event stream closed early. */
  | { type: "interrupted" }
  /** Something that is not a turn happened, just recorded: she hung up. */
  | { type: "event"; event: ConversationEvent };

export const emptyLog: ConversationLog = { entries: [], turn: null };

export function conversationLog(log: ConversationLog, action: LogAction): ConversationLog {
  switch (action.type) {
    case "loaded":
      return { entries: action.messages.map(toEntry), turn: null };
    case "submitted":
      return opened(withoutTurn(log), action.text, action.at, false);
    case "user":
      if (log.turn && !log.turn.confirmed) {
        return { ...log, turn: { ...log.turn, confirmed: true } };
      }
      return opened(withoutTurn(log), action.text, action.at, true);
    case "delta": {
      const turn = log.turn;
      if (!turn) return log;
      return { ...log, entries: replaced(log.entries, turn.replyKey, (e) => withDelta(e, action)) };
    }
    case "done": {
      const turn = log.turn;
      if (!turn) return log;
      const reply = toEntry(action.message);
      const entries = replaced(log.entries, turn.replyKey, () => reply);
      // She ended the conversation after her reply: that comes after it.
      return { entries: action.ended ? [...entries, toEntry(action.ended)] : entries, turn: null };
    }
    case "error":
    case "interrupted":
      return withoutTurn(log);
    case "event":
      return { ...log, entries: [...log.entries, toEntry(action.event)] };
  }
}

/** The segments of her reply in the turn under way, as far as they have arrived; none if no turn
 * is under way. */
export function replySoFar(log: ConversationLog): Segment[] {
  const turn = log.turn;
  const reply = turn && log.entries.find((entry) => entry.key === turn.replyKey);
  return reply?.kind === "character" ? reply.segments : [];
}

/** Opens a turn with the user's words and an empty reply to fill. The turn in progress is
 * always the last two entries, so an entry's position is never shared by two entries
 * shown together and serves as its key until the entry is replaced by the recorded one. */
function opened(log: ConversationLog, text: string, at: string, confirmed: boolean): ConversationLog {
  const position = log.entries.length;
  const turn = { confirmed, userKey: `new-${position}`, replyKey: `new-${position + 1}` };
  return {
    entries: [
      ...log.entries,
      { kind: "user", key: turn.userKey, text, at },
      { kind: "character", key: turn.replyKey, segments: [], pending: true, at, affinity: null },
    ],
    turn,
  };
}

/** A turn that ends without `done` left no record: take it back off the log. */
function withoutTurn(log: ConversationLog): ConversationLog {
  const turn = log.turn;
  if (!turn) return log;
  const entries = log.entries.filter((e) => e.key !== turn.userKey && e.key !== turn.replyKey);
  return { entries, turn: null };
}

function replaced(entries: Entry[], key: string, update: (entry: Entry) => Entry): Entry[] {
  return entries.map((entry) => (entry.key === key ? update(entry) : entry));
}

function withDelta(entry: Entry, event: TurnEvent & { type: "delta" }): Entry {
  if (entry.kind !== "character") return entry;
  const segments = [...entry.segments];
  const current = segments[event.segment] ?? { ja: "", zh: "" };
  // A plain-language reply (`text`) keeps its words in the primary `ja` field, subtitle empty.
  const lang = event.lang === "text" ? "ja" : event.lang;
  segments[event.segment] = { ...current, [lang]: current[lang] + event.text };
  return { ...entry, segments };
}

function toEntry(message: Recorded): Entry {
  if ("type" in message) {
    return {
      kind: "event",
      key: `e${message.id}`,
      event: message.kind,
      at: message.created_at,
      gift: message.gift_name ?? null,
      unwell: unwellOf(message),
      affinity: message.affinity,
    };
  }
  return message.role === "user"
    ? { kind: "user", key: `m${message.id}`, text: message.text ?? "", at: message.created_at }
    : {
        kind: "character",
        key: `m${message.id}`,
        segments: message.segments,
        pending: false,
        at: message.created_at,
        affinity: message.affinity,
      };
}
