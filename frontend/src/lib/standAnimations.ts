// How she looks during a call: emotion, whether she is speaking, whether she looks at the user,
// and any nod. Kept as pure state outside React; the call layer reads it from the snapshot.

/** Her emotion (GLOSSARY.md「情绪」): 平静、开心、害羞、惊讶、难过、生气、思考. */
export type Emotion = "calm" | "happy" | "shy" | "surprised" | "sad" | "angry" | "thinking";

/** A nod (`yes`) or a shake of the head (`no`); each gets a new id, so it is played once. */
export type Nod = { kind: "yes" | "no"; id: number };

/** How she should look right now. */
export type StandDirection = {
  /** Her emotion over the call so far; calm when it starts. */
  mood: Emotion;
  /** Her mouth is moving. */
  speaking: boolean;
  /** She looks at the user. */
  looking: boolean;
  nod: Nod | null;
};

/** How she looks when a call starts. */
export const CALM: StandDirection = { mood: "calm", speaking: false, looking: false, nod: null };