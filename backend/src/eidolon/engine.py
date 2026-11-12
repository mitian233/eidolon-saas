"""The conversation engine: one conversation turn in, the character's reply out.

It knows nothing about voice. Given a conversation and the user's input text it
retrieves what the turn calls for, assembles the prompt, streams the chat model's reply as
per-segment deltas, and records both sides of the turn once the reply is complete.

Every turn, typed or spoken, speaks the same protocol: `user` (the input as taken up),
then any `delta`s, then `done` or `error`. Among the deltas, `SegmentComplete` says
when a segment is complete; it stays on the server. Input that is blank or too long is rejected
before the model is asked; a turn that is rejected or fails part-way leaves no record,
and what went wrong stays in the server log.

The reply follows the character's language mode (`Character.language_mode`, D10): plain
text by default, shown with `lang="text"`, or paired `<ja><zh>` segments when bilingual.
Either way the primary text is kept in the segment's `ja` and the subtitle in its `zh`
(empty in the plain mode), so the record keeps one shape.

The chat model is offered the recall-story tool on every turn when retrieval is available
(ADR-0033), but forbidden to call it in one that already recalled a passage. Its calls are
answered and the model asked again, once at most since every round costs the model's time
to first token; whatever it says along the way is part of the reply, and only the reply is
recorded. Should it write out a service's own tool-call markup instead (`MARKUP`), the
markup and all after it in the round go nowhere; a round with nothing shown before it is
asked again, once in a turn.

Every turn carries the character sheet, and her birthday if she has one, as a system
message of their own, the same for every user's turns with her that day, marked for the
service to cache; who the user is follows in another, then the conversation so far. What
changes from turn to turn (the time, her affinity, what retrieval found) comes after the
conversation, in a system message just before what the user is saying now, and is not
carried into the turns after it: so each turn's prompt opens as the one before it did, up
to the end of the conversation so far, marked for the service to cache too (ADR-0020).

The chat model reads at least as many of the latest turns as the deployer says, but they
are cut back only every so often, so what it reads opens the same way for a while
(`chat_history`).

The user's memories that retrieval finds go into the prompt, and once a turn is
recorded memory writes down what the user revealed in it, when memory is on. Once the
conversation's third turn is recorded, the background model names the conversation
(`titles`), memory on or off; her prompt never carries the title.

A turn can be told to stop part-way (a call's user interrupting the character): the
model and any tool it is waiting on are abandoned at once, and the turn is recorded as
ever, with only the segments complete by then.

Each turn runs on the models it is given (see `OwnKeys.for_turn`): one plays the
character, the other (the background model) writes down memories and names the
conversation. When the user's own fails, the turn fails saying so.

Where affinity is on as the turn begins (GLOSSARY.md「好感度」) and she is not in a cooldown,
the judge model judges what the user said to her before she replies: in the same request
as retrieval's judge, or, retrieval off, in one of its own while the turn gets on with the
rest. Once her reply is recorded affinity changes as it judged, and the change is recorded
with her reply; `done` tells it, and where it leaves her affinity. A turn not recorded
changes nothing; one the judge model could not judge leaves it as it is. She replies in the
tier the turn began in, knowing how what the user said made her feel, and parting with the
user if it is to begin a cooldown (GLOSSARY.md「冷却」); in one, she has no turns
(`Admissions`). What it judged of a turn recorded, and whether the turn began a cooldown,
the turn's activity record keeps (`TurnJudged`). In a call she parts by hanging up, after
that turn, after the user has been out of line once too often in the call, or after the
call's latest turns have taken too much off her affinity (`affinity.ends`), warning the
user first halfway there (`affinity.warns`): the turn is told it is in a call, how often so
far and how much each turn so far took, and once recorded tells the call what came of it
(`CallTurnRecorded`). Outside calls she parts the same way after the same turns, counted
over the conversation's latest typed turns, warning the user first that she will not want
to talk, and ends the conversation (GLOSSARY.md「已结束的对话」): each typed turn is
recorded with what it came to (`Typed`), the latest read back as the next begins; the one
she ends it after is recorded with her ending it, which `done` tells, and why, which the
activity record keeps, and those `on_ended` has are told then, for her to hang up a call in
it. A turn in a conversation she has ended is rejected, as is one that finds it ended,
elsewhere, as it is recorded.

She learns of the conversation's events (GLOSSARY.md「对话事件」) from a line of narration
before the user's words that came next, or before what the user is saying now; it leaves
her prompt with those words. Until she has replied after a gift, she is also told to
respond to it, once, however many came. Retrieval, memory and the judge model never read
the events.
"""

import asyncio
import logging
import sqlite3
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable, Mapping, Sequence
from contextlib import nullcontext
from copy import deepcopy
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from typing import Literal, ParamSpec, TypeVar

from eidolon.affinity import (
    FED_UP_TURNS,
    Affinities,
    EndsFor,
    Judged,
    Parting,
    Status,
    affinity_prompt,
    ends,
    hurt,
    warns,
)
from eidolon.affinity_judge import AffinityJudge
from eidolon.characters import Character
from eidolon.clock import Clock
from eidolon.config import FishAudioModel
from eidolon.data_access import Database
from eidolon.gift_catalog import Gift
from eidolon.her_now import HerNow, KnownNow, Occasion
from eidolon.judge import JudgeError
from eidolon.llm import ChatMessage, Reasoning, Tool, ToolCall, TurnLLMs
from eidolon.memory import Memories
from eidolon.own_keys import OwnKeyFailed
from eidolon.producer import ProducerProfile, effective_timezone, producer_prompt
from eidolon.reply_format import (
    ReplyParser,
    Segment,
    SegmentComplete,
    SegmentDelta,
    SpeechDelta,
    format_instructions,
    format_reply,
)
from eidolon.retrieval import RECALL_STORY_TOOL, Retrieval, Retrieved
from eidolon.store import (
    Conversation,
    ConversationEnded,
    ConversationEvent,
    Message,
    Recorded,
    Store,
    Typed,
    add_turn,
    read_ended,
    read_last_contact,
    read_profile,
    read_record,
    timestamp,
    told_her,
)
from eidolon.titles import Titles
from eidolon.today import always_known

MAX_INPUT_LENGTH = 2000
"""The longest thing a user can say in one turn, typed or spoken, in characters; longer
input is rejected, not cut short."""
MAX_TOOL_ROUNDS = 1
"""How many rounds of tool calls the chat model gets in one turn; after that it has to answer."""
LAST_ROUND_NOTE = (
    "（这一轮不能再调用任何工具了，请现在就回答对方。上面想起来的内容如果答不上对方的问题，"
    "就像一时记不清那样自然地说，不要提到查找、工具、记录或资料库。）"
)
"""Added to each tool result the model reads just before the round that forbids tool calls.
Without it the model, still wanting to look something up, writes out its own tool-call
markup as the reply. Worded and verified against the real chat model; rewording it needs
that verification again."""


@dataclass(frozen=True)
class UserSaid:
    """What the user said, as the turn takes it up; every turn opens with it."""

    text: str
    type: Literal["user"] = field(default="user", init=False)


Look = Literal["story"]
"""What she looks up (GLOSSARY.md「查看」): the story, recalled."""
LOOKS: dict[str, Look] = {RECALL_STORY_TOOL.name: "story"}
"""What she looks up by each tool she may call."""


@dataclass(frozen=True)
class LookingUp:
    """She is looking up `what` (GLOSSARY.md「查看」), each once, in the order called: as the
    chat model's calls are answered, or as retrieval recalls the story for her before she
    speaks. Comes between `delta`s, or before the first; it is not recorded."""

    what: tuple[Look, ...]
    type: Literal["looking-up"] = field(default="looking-up", init=False)


@dataclass(frozen=True)
class TurnDone:
    """The recorded reply, with how the turn changed her affinity if it did; her affinity
    after it (`Status.shown`), None where affinity is off; and her ending the conversation
    after it (`ConversationEvent.shown`), None if she did not. The turn succeeded."""

    message: Message
    affinity: dict[str, str | None] | None = None
    ended: dict | None = None
    type: Literal["done"] = field(default="done", init=False)


@dataclass(frozen=True)
class InCall:
    """The turn is taken in a call, in which the user has been out of line (GLOSSARY.md
    「不该说的话」) `out_of_line` times so far, in turns recorded, which took `hurts` each off
    her affinity (`affinity.hurt`), the latest last."""

    out_of_line: int = 0
    hurts: tuple[float, ...] = ()
    connected_at: datetime | None = None
    """When the call connected, as the clock told: they were last in touch before it."""


@dataclass(frozen=True)
class CallTurnRecorded:
    """What a turn of a call, now recorded, comes to for the call: whether the user was out
    of line in it, and whether she hangs up after it and why; if for a cooldown, when it
    ends (None should the cooldown not have begun after all, another turn recorded
    meanwhile); how much it hurt her (`affinity.hurt`). Comes just before
    `done`, in calls only; it stays on the server."""

    out_of_line: bool = False
    hangs_up: EndsFor | None = None
    cooldown_until: datetime | None = None
    hurt: float = 0.0
    type: Literal["call-turn-recorded"] = field(default="call-turn-recorded", init=False)


@dataclass(frozen=True)
class TurnJudged:
    """What the judge model made of a turn now recorded (GLOSSARY.md「好感度」), whether the
    turn began a cooldown, and why she ended the conversation after it, if she did, for its
    activity record. Comes just before `done`, in turns judged only; it stays on the server."""

    judged: Judged
    cooled: bool
    ended: EndsFor | None = None
    type: Literal["turn-judged"] = field(default="turn-judged", init=False)


@dataclass(frozen=True)
class TurnFailed:
    """Why the turn failed, for the user to read; it left no record."""

    message: str
    type: Literal["error"] = field(default="error", init=False)


@dataclass(frozen=True)
class TurnRejected:
    """Why the turn was rejected for its input, for the user to read; it left no record.
    The browser is told it as it is told a failure."""

    message: str
    type: Literal["error"] = field(default="error", init=False)


TurnEvent = (
    UserSaid
    | LookingUp
    | SegmentDelta
    | SpeechDelta
    | SegmentComplete
    | CallTurnRecorded
    | TurnJudged
    | TurnDone
    | TurnFailed
    | TurnRejected
)
"""A turn's events: `user`, any `delta`s, `looking-up` among them as she looks something up,
then `done`, or `error`. `shown(event)` is the event as it goes out to the browser, except
`SpeechDelta`, `SegmentComplete`, `CallTurnRecorded` and `TurnJudged`, which do not."""


def shown(event: TurnEvent) -> dict:
    """The event as it goes out to the browser: `done`'s reply as `Message.shown` has it."""
    if isinstance(event, TurnDone):
        return asdict(event) | {"message": event.message.shown()}
    return asdict(event)


FAILED = "角色暂时无法回复，请稍后再试。"
"""What the user reads when a turn fails; the details stay in the server log."""
TOO_LONG = f"这句话太长了，最多 {MAX_INPUT_LENGTH} 字。"
"""What the user reads when a turn is rejected for input over `MAX_INPUT_LENGTH`."""
BLANK = "没有收到要说的话。"
"""What the user reads when a turn is rejected for blank input."""
ENDED = "她已经结束了对话"
"""What the user reads when a turn is rejected for the conversation she has ended."""

log = logging.getLogger(__name__)


class EmptyReply(RuntimeError):
    pass


MARKUP = ("<｜", "</｜")
"""How a service's own tool-call markup opens (DeepSeek's `<｜｜DSML｜｜invoke …>`,
`<｜tool▁calls▁begin｜>`), should the chat model write it out as text instead of calling: never
in her words, nor shown, nor voiced."""


class _BeforeMarkup:
    """What a round's text may go on to the reply, as it streams: all before any `MARKUP`
    (`found` once it is), held back while what it ends with could be the start of one."""

    def __init__(self) -> None:
        self._held = ""
        self.found = False

    def feed(self, chunk: str) -> str:
        text = self._held + chunk
        at = [i for m in MARKUP if (i := text.find(m)) >= 0]
        if at:
            self.found, self._held = True, ""
            return text[: min(at)]
        keep = max(
            (n for m in MARKUP for n in range(1, len(m)) if text.endswith(m[:n])), default=0
        )
        self._held = text[len(text) - keep:]
        return text[: len(text) - keep]

    def finish(self) -> str:
        """What was held back, at the end of a round with none."""
        held, self._held = self._held, ""
        return held


class _Stopped(Exception):
    """The turn was told to stop."""


P = ParamSpec("P")
T = TypeVar("T")


async def _unless_stopped(
    stop: asyncio.Event | None, work: Callable[P, Awaitable[T]], *args: P.args, **kwargs: P.kwargs
) -> T:
    """What `work` comes to, unless `stop` is set first: then it is abandoned and this
    raises _Stopped."""
    if stop is None:
        return await work(*args, **kwargs)
    if stop.is_set():
        raise _Stopped
    working = asyncio.ensure_future(work(*args, **kwargs))
    stopped = asyncio.ensure_future(stop.wait())
    try:
        await asyncio.wait({working, stopped}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        stopped.cancel()
        if not working.done():
            working.cancel()
            await asyncio.wait({working})
    if working.cancelled():
        raise _Stopped
    return working.result()


async def _judged(
    judge: AffinityJudge,
    character: Character,
    history: list[Message],
    text: str,
    affinity: bool,
) -> Judged | None:
    """Asked about `affinity`, what saying `text` does to her affinity (None if not, or if it
    cannot be told)."""
    try:
        judged, _ = await judge.judge(character, history, text, affinity, False, None)
        return judged
    except JudgeError:
        log.warning("judging apart failed; affinity stays as it is", exc_info=True)
        return None


@dataclass(frozen=True)
class _BeforeAsking:
    """What a turn reads from the database before she is asked: whether she has ended the
    conversation, her character, the conversation's record, when the user and she were last
    in touch (None in a call, where she knows they are talking), her affinity as it begins,
    and the user profile."""

    ended: bool
    character: Character
    record: list[Recorded]
    last_contact: datetime | None
    affinity: Status | None
    profile: ProducerProfile


def latest_turns(messages: list[Message], turns: int | None) -> list[Message]:
    """The messages from the `turns`th last user message on (from the first if None), so
    what the chat model reads always opens with the user."""
    starts = [i for i, m in enumerate(messages) if m.role == "user"]
    kept = starts if turns is None else starts[-turns:]
    return messages[kept[0]:] if kept else []


def chat_history(messages: list[Message], turns: int | None) -> list[Message]:
    """The latest turns of `messages` the chat model reads: at least `turns` (all if None),
    cut back to that many each time they reach half as many again, rather than one at a
    time, so what it reads opens the same way from turn to turn in between."""
    total = sum(m.role == "user" for m in messages)
    if turns is None or total <= turns:
        return latest_turns(messages, None)
    step = max(1, turns // 2)
    return latest_turns(messages, total - step * ((total - turns) // step))


RESPOND_TO_GIFTS = (
    "（先回应对方说的话，再在合适的时候用你自己的方式回应收到的礼物，一次就够。）"
)
"""Told her after the gifts she has not replied since, once however many there are."""


def _narration(event: ConversationEvent, gift_catalog: Mapping[str, Gift]) -> str:
    """What she is told of `event`, as it was."""
    if event.kind == "hung_up":
        return "（你挂断了对方的电话。）"
    if event.kind == "ended":  # only read by a turn it will reject
        return "（你结束了和对方的对话。）"
    assert event.gift_id is not None
    gift = gift_catalog.get(event.gift_id)
    liked = "这是你喜欢的东西。" if event.liked else ""
    return f"（对方送给你一份{gift.name if gift else '礼物'}。{liked}）"


def _narration_line(entry: ConversationEvent, gift_catalog: Mapping[str, Gift]) -> str:
    """The line of narration telling her of `entry`."""
    return f"{_narration(entry, gift_catalog)}\n"


def narrations(
    record: Sequence[Recorded], gift_catalog: Mapping[str, Gift]
) -> dict[int | None, str]:
    """The narration of the events in `record`, by the id of the user message each comes
    before, None for those after them all: one line for each she is told of (`told_her`),
    then, if she has not replied since a gift, `RESPOND_TO_GIFTS`. Her reach-outs, no longer
    made, are left out."""
    lines: list[str] = []
    told: dict[int | None, str] = {}
    unanswered = False
    for entry in record:
        if not told_her(entry):
            continue
        if isinstance(entry, Message):
            if entry.role == "character":
                unanswered = False
            elif lines:
                told[entry.id], lines = "".join(lines), []
        elif isinstance(entry, ConversationEvent):
            lines.append(_narration_line(entry, gift_catalog))
            unanswered = unanswered or entry.kind == "gift"
    if unanswered:
        lines.append(f"{RESPOND_TO_GIFTS}\n")
    if lines:
        told[None] = "".join(lines)
    return told


class ConversationEngine:
    def __init__(
        self,
        db: Database,
        store: Store,
        characters: dict[str, Character],
        gift_catalog: Mapping[str, Gift],
        memory: Memories,
        titles: Titles,
        clock: Clock,
        her_now: HerNow,
        retrieval: Retrieval | None = None,
        history_turns: Callable[[], int | None] = lambda: None,
        affinities: Affinities | None = None,
        affinity_judge: AffinityJudge | None = None,
    ) -> None:
        """Without `retrieval`, turns carry no story or character facts and find no
        memories. Each turn reads only the conversation's latest turns, as many as
        `history_turns` says as it begins, or all of them if None; the chat model reads
        at least as many (`chat_history`). Without `affinities`, turns change no affinity;
        with them, retrieval's judge judges what turns do to it, or without retrieval
        `affinity_judge`. What she knows of now, `her_now` gives."""
        self._db = db
        self._store = store
        self._characters = characters
        self._gift_catalog = gift_catalog
        self._clock = clock
        self._retrieval = retrieval
        self._memory = memory
        self._titles = titles
        self._history_turns = history_turns
        self._affinities = affinities
        self._affinity_judge = affinity_judge
        self._her_now = her_now
        self._ended_listeners: list[Callable[[str, EndsFor], None]] = []
        self._cooled_listeners: list[Callable[[str, str, datetime], None]] = []

    def on_ended(self, listener: Callable[[str, EndsFor], None]) -> None:
        """Have `listener` told the conversation's id, and why, as she ends one, once it is
        recorded."""
        self._ended_listeners.append(listener)

    def on_cooled(self, listener: Callable[[str, str, datetime], None]) -> None:
        """Have `listener` told the user, the character and when it ends as a turn begins a
        cooldown, once it is recorded, in the task that took the turn."""
        self._cooled_listeners.append(listener)

    async def turn(
        self,
        conversation: Conversation,
        text: str,
        llms: TurnLLMs,
        device_timezone: str | None = None,
        stop: asyncio.Event | None = None,
        in_call: InCall | None = None,
        voiced_by: FishAudioModel | None = None,
    ) -> AsyncGenerator[TurnEvent, None]:
        """Take one turn on `llms`, `in_call` if it is taken in one, its reply voiced with
        `voiced_by` (for a text turn's, the model it would be read aloud with; None if none),
        which has her write delivery cues as it reads them. `device_timezone` is the time
        zone the user's device reports, used unless the user profile sets one. Once `stop`
        is set, the turn goes no further and is recorded with the segments complete by
        then."""
        text = text.strip()
        yield UserSaid(text)
        if not text or len(text) > MAX_INPUT_LENGTH:
            yield TurnRejected(TOO_LONG if text else BLANK)
            return
        # A text turn is under way, so that she does not reach out meanwhile; a call is, as
        # long as it lasts.
        taking = self._store.taking_turn(conversation.id) if in_call is None else nullcontext()
        try:
            with taking:
                async for event in self._reply(
                    conversation, text, llms, device_timezone, stop, in_call, voiced_by
                ):
                    yield event
        except OwnKeyFailed as e:  # theirs to fix, so they are told what went wrong
            log.warning("turn failed on the user's own key in conversation %s: %s",
                        conversation.id, e.service)
            yield TurnFailed(e.message)
        except Exception:  # the turn has started; report instead of dropping it
            log.exception("turn failed in conversation %s", conversation.id)
            yield TurnFailed(FAILED)

    async def _reply(
        self,
        conversation: Conversation,
        text: str,
        llms: TurnLLMs,
        device_timezone: str | None,
        stop: asyncio.Event | None,
        in_call: InCall | None,
        voiced_by: FishAudioModel | None,
    ) -> AsyncIterator[TurnEvent]:
        # The database is read and written on threads all through the turn: waiting on it
        # on the event loop would keep everyone's calls on it from going on meanwhile.
        occasion: Occasion = "typing" if in_call is None else "in_call"
        known = await self._her_now.read(
            conversation.user_id, conversation.character_id, device_timezone, occasion
        )
        read = await self._db.read(self._before_turn, conversation, in_call, self._affinity_on)
        if read.ended:
            yield TurnRejected(ENDED)
            return
        character, record, last_contact, affinity, profile = (
            read.character, read.record, read.last_contact, read.affinity, read.profile,
        )
        bilingual = character.language_mode == "bilingual"
        # Said after reading the record, so an event this turn's prompt does not tell of
        # comes before the turn, and is told of with its words from the next turn on.
        said_at = timestamp()
        messages = [entry for entry in record if isinstance(entry, Message)]
        turns = self._history_turns()
        history = latest_turns(messages, turns)
        timezone = effective_timezone(profile, device_timezone)
        judging = affinity is not None and not affinity.cooling
        judged_apart = None
        if judging and self._retrieval is None and self._affinity_judge:
            judged_apart = asyncio.ensure_future(_judged(
                self._affinity_judge, character, history, text, judging
            ))
        try:
            memory = await self._memory.begin(
                conversation, timezone, llms.background, llms.hold_background
            )
            retrieved = Retrieved(None)
            if self._retrieval:
                recalling = asyncio.Event()
                retrieving = asyncio.ensure_future(self._retrieval.retrieve(
                    character, history, text, memory, judging, False, None, recalling.set,
                ))
                try:
                    recall_begun = asyncio.ensure_future(recalling.wait())
                    await asyncio.wait(
                        {retrieving, recall_begun}, return_when=asyncio.FIRST_COMPLETED
                    )
                    recall_begun.cancel()
                    if recalling.is_set():
                        yield LookingUp(("story",))
                    retrieved = await retrieving
                finally:
                    retrieving.cancel()
            judged = await judged_apart if judged_apart is not None else retrieved.judged
        finally:
            if judged_apart is not None and not judged_apart.done():
                judged_apart.cancel()
        now = self._clock()
        cools = await self._cools(conversation, judged)
        if in_call is not None:
            out_of_line_before, hurt_before = in_call.out_of_line, in_call.hurts
        else:
            # As many as are weighed, so that whether she warns is told against the latest
            # before this one; out of line is counted in the latest with this one among them.
            earlier = await self._store.typed_turns(conversation.id, FED_UP_TURNS)
            out_of_line_before = sum(t.out_of_line for t in earlier[-(FED_UP_TURNS - 1):])
            hurt_before = [t.hurt for t in earlier]
        ending = ends(judged, cools, out_of_line_before, hurt_before)
        way: Parting = "hangs_up" if in_call is not None else "parts"
        affinity_lines = (
            affinity_prompt(
                affinity.tier,
                judged,
                way if ending or cools else None,
                way if warns(judged, cools, out_of_line_before, hurt_before) else None,
            )
            if affinity is not None
            else []
        )
        prompt = self._prompt(
            character, producer_prompt(profile, character.user_address),
            chat_history(messages, turns),
            narrations(record, self._gift_catalog),
            [
                self._now_section(
                    known, occasion, now, timezone, profile, last_contact, affinity_lines,
                ),
            ],
            [p for p in (retrieved.memories_prompt, retrieved.prompt) if p],
            text, voiced_by, bilingual,
        )

        # Offered on every turn, so that what goes before the history (the tools, with
        # many services) opens every turn's prompt alike, for the service to cache it.
        tools: list[Tool] = [RECALL_STORY_TOOL] if self._retrieval else []
        parser = ReplyParser(bilingual=bilingual)
        step, asked_again = 0, False
        try:
            while True:
                # The last round offers the same tools, as some models drop what they thought
                # once the tools change, but forbids calling them; so does a turn that
                # already recalled a passage, its one round its last.
                forbidden = step == MAX_TOOL_ROUNDS or retrieved.recalled
                said = ""
                calls: list[ToolCall] = []
                reasoning: list[Reasoning] = []
                markup = _BeforeMarkup()
                before, shown = deepcopy(parser), False
                stream = llms.chat.stream(prompt, tools, forbid_calls=forbidden)
                try:
                    while (item := await _unless_stopped(stop, anext, stream, None)) is not None:
                        if isinstance(item, ToolCall):
                            calls.append(item)
                            continue
                        if isinstance(item, Reasoning):
                            reasoning.append(item)
                            continue
                        let_through = markup.feed(item)
                        said += let_through
                        for event in parser.feed(let_through):
                            shown = True
                            yield event
                        if markup.found:
                            break
                finally:
                    if (close := getattr(stream, "aclose", None)) is not None:
                        await close()  # a stream left part-way lets go of its connection
                if markup.found:
                    log.warning("the chat model wrote out tool-call markup in conversation %s",
                                conversation.id)
                    if not shown:  # none of the round shown: as if it never was
                        parser = before
                        if not asked_again:
                            asked_again = True
                            continue
                    # What she said before it stands; the round goes no further.
                    calls = []
                else:
                    said += (rest := markup.finish())
                    for event in parser.feed(rest):
                        yield event
                for event in parser.finish():
                    yield event
                # A call to a tool not offered, or made when forbidden, goes unanswered.
                if not calls or not tools or forbidden:
                    break
                offered = {t.name for t in tools}
                looks: list[Look] = []
                for call in calls:
                    if call.name in offered and call.name in LOOKS and LOOKS[call.name] not in looks:
                        looks.append(LOOKS[call.name])
                if looks:
                    yield LookingUp(tuple(looks))
                prompt = [
                    *prompt,
                    ChatMessage("assistant", said, tuple(calls), reasoning=tuple(reasoning)),
                ]
                for call in calls:
                    result = await _unless_stopped(stop, self._call_tool, character, call)
                    if step + 1 == MAX_TOOL_ROUNDS:
                        result = f"{result}\n\n{LAST_ROUND_NOTE}"
                    prompt.append(ChatMessage("tool", result, tool_call_id=call.id))
                step += 1
        except _Stopped:
            pass

        if not parser.complete:
            raise EmptyReply("对话模型没有返回任何内容")
        typed = (
            None if in_call is not None
            else Typed(hurt(judged), judged is not None and judged.out_of_line)
        )
        ends_conversation = typed is not None and ending is not None
        # Once handed in, the turn is recorded whatever becomes of it, and what comes of that
        # is told all the same, should the turn be cancelled meanwhile, the user gone, say:
        # in a task of its own, which carries this one's context, so that a call taking the
        # turn is told it is the one.
        keeping = asyncio.ensure_future(self._keep(
            conversation, text, said_at, parser.complete, judged, affinity, typed,
            ends_conversation,
        ))
        try:
            reply, affinity = await asyncio.shield(keeping)
        except ConversationEnded:  # elsewhere, as the turn was under way
            yield TurnRejected(ENDED)
            return
        memory.write_down(history, text, reply, retrieved.query_vector)
        turn = sum(m.role == "user" for m in messages) + 1
        self._titles.after_turn(conversation, turn, reply.id, llms.background, llms.hold_background)
        ended = await self._store.ended(conversation.id) if ends_conversation else None
        if ended is not None and ending is not None:
            for listener in self._ended_listeners:
                listener(conversation.id, ending)
        if judged is not None and self._affinities is not None:
            yield TurnJudged(
                judged,
                reply.affinity is not None and reply.affinity.cooldown,
                ending if ends_conversation else None,
            )
        if in_call is not None:
            yield CallTurnRecorded(
                judged is not None and judged.out_of_line,
                ending,
                affinity and affinity.cooldown_until,
                hurt(judged),
            )
        yield TurnDone(
            reply.without_cues(), affinity and affinity.shown(), ended and ended.shown(),
        )

    def _before_turn(
        self,
        db: sqlite3.Connection,
        conversation: Conversation,
        in_call: InCall | None,
        affinity_on: bool,
    ) -> _BeforeAsking:
        """What a turn of `conversation` reads before it is asked, through `db`, all in one
        read: `in_call` if it is taken in one, her affinity if `affinity_on`."""
        character = self._characters[conversation.character_id]
        user_id, character_id = conversation.user_id, conversation.character_id
        last_contact = None if in_call is not None else read_last_contact(db, user_id, character_id)
        return _BeforeAsking(
            read_ended(db, conversation.id) is not None,
            character,
            read_record(db, conversation.id),
            last_contact,
            self._affinity(db, conversation) if affinity_on else None,
            read_profile(db, conversation.user_id),
        )

    @property
    def _affinity_on(self) -> bool:
        """Whether turns go by affinity now: the engine has it, and it is on."""
        return self._affinities is not None and self._affinities.on

    def _affinity(self, db: sqlite3.Connection, conversation: Conversation) -> Status:
        """Her affinity with the user as the turn begins, read through `db`, affinity on."""
        assert self._affinities is not None
        return self._affinities.read_status(db, conversation.user_id, conversation.character_id)

    async def _cools(self, conversation: Conversation, judged: Judged | None) -> bool:
        """Whether the turn, as `judged`, would begin a cooldown; never if not judged."""
        if judged is None or self._affinities is None:
            return False
        return await self._affinities.cools(
            conversation.user_id, conversation.character_id, judged
        )

    async def _keep(
        self,
        conversation: Conversation,
        text: str,
        said_at: str,
        reply: list[Segment],
        judged: Judged | None,
        affinity: Status | None,
        typed: Typed | None,
        ends_conversation: bool,
    ) -> tuple[Message, Status | None]:
        """Record the turn (`_record`), and tell what comes of it: should it begin a
        cooldown, those `on_cooled` has. The reply and her affinity after it."""
        message, affinity = await self._db.write(
            self._record,
            conversation, text, said_at, reply, judged, affinity, typed, ends_conversation,
        )
        until = affinity and affinity.cooldown_until
        if message.affinity is not None and message.affinity.cooldown and until is not None:
            # In the turn's context: her calls with the user hang up there and then, one this
            # turn is taken in after it.
            for cooled in self._cooled_listeners:
                cooled(conversation.user_id, conversation.character_id, until)
        return message, affinity

    def _record(
        self,
        db: sqlite3.Connection,
        conversation: Conversation,
        text: str,
        said_at: str,
        reply: list[Segment],
        judged: Judged | None,
        affinity: Status | None,
        typed: Typed | None,
        ends_conversation: bool,
    ) -> tuple[Message, Status | None]:
        """Record the turn, as said at `said_at`, through `db`, in one transaction with all
        it changes: her affinity as `judged` says, if judged, with what a typed turn came to,
        and her ending the conversation after it if she does, all of it or none.
        The reply and her affinity after it (`affinity`, as the turn began, if not judged)."""
        if judged is not None and self._affinities is not None:
            change, affinity = self._affinities.change(
                db, conversation.user_id, conversation.character_id, judged
            )
        else:
            change = None
        message = add_turn(
            db, conversation.id, text, reply, change, said_at, typed, ends_conversation
        )
        return message, affinity

    async def _call_tool(self, character: Character, call: ToolCall) -> str:
        """The tool's result, or what went wrong, for the model to read: what she recalls."""
        if call.name != RECALL_STORY_TOOL.name or self._retrieval is None:
            return f"没有 {call.name} 这个工具。"
        query = (call.arguments or {}).get("query")
        if not isinstance(query, str) or not query.strip():
            return "调用参数有误：需要 query（要回顾的事，一句概括）。"
        return await self._retrieval.recall_story(character, query.strip())

    def _now_section(
        self,
        known: KnownNow,
        occasion: Occasion,
        now: datetime,
        timezone: str,
        profile: ProducerProfile,
        last_contact: datetime | None,
        affinity_lines: Sequence[str],
    ) -> str:
        """The prompt section of what she knows of now on `occasion` (`HerNow.lines`)."""
        return "\n".join(self._her_now.lines(
            known, occasion, now, timezone, profile, last_contact, affinity_lines,
        ))

    def _prompt(
        self,
        character: Character,
        about_user: str,
        history: list[Message],
        narration: dict[int | None, str],
        about_turn: list[str],
        closing: list[str],
        text: str,
        voiced_by: FishAudioModel | None,
        bilingual: bool,
    ) -> list[ChatMessage]:
        """The prompt (ADR-0020): what changes from turn to turn tells first `about_turn`, then
        `closing`: what retrieval found."""
        # What every user's turns with her that day open with, apart, for a service to cache.
        shared = [
            *always_known(character),
            format_instructions(voiced_by, bilingual=bilingual),
        ]
        prompt = [
            ChatMessage("system", "\n\n".join(shared), cache_breakpoint=True),
            ChatMessage("system", about_user),
        ]
        for message in history:
            if message.role == "user":
                told = narration.get(message.id, "")
                prompt.append(ChatMessage("user", f"{told}{message.text or ''}"))
            else:
                prompt.append(ChatMessage("assistant", format_reply(
                    message.segments, bilingual=bilingual,
                )))
        if history:  # what the next turn opens with too, for a service to cache
            prompt[-1] = replace(prompt[-1], cache_breakpoint=True)
        context = [*about_turn, *closing]
        prompt.append(ChatMessage("system", "\n\n".join(context)))
        prompt.append(ChatMessage("user", f"{narration.get(None, '')}{text}"))
        return prompt