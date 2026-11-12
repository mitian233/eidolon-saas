"""She hangs up (GLOSSARY.md「通话」「冷却」「不该说的话」): in a call, the turn that takes her
affinity to 0, the second time in that call the user is out of line, or the turn that has
how much the call's latest turns hurt her add up to too much, has her told to hang
up once she has said it; once it is recorded and what is on its way to her voice is voiced,
the browser is told `ended`, why (`cooldown`, with when it ends, or `she_hung_up`) and that
the call counted, along with the「挂断了电话」event, written into the conversation there and
then. Halfway there, she warns the user first, once till it eases. The call is a success,
ended by her (「角色挂断」). What is out of line, and what hurt her, is counted in that call
alone; a turn that fails is not counted, nor does she hang up after it. Her
hanging up comes before the call's limits, reached by the same turn. A follow-on has the
whole of what the user said judged afresh; her last line cut short, she hangs up all the
same.

Driven through the backend's external API, with a browser calling in over a real WebRTC
connection and the judge model faked turn by turn; what needs its timing held exactly, at
the Pipecat stage that takes the call's turns (see `test_call_turns.py`)."""

from dataclasses import replace
from datetime import timedelta

import asyncio

import pytest
from pipecat.frames.frames import InterruptionFrame
from pipecat.tests.utils import SleepFrame

from eidolon.call_outcome import CallLimits
from eidolon.config import Settings
from tests.browser import TIMEOUT, Browser, open_browser
from tests.conftest import ClientFactory
from tests.fakes import (
    JUDGED_KEYS,
    START,
    FakeClock,
    FakeIdentityProvider,
    FakeLLM,
    FakeServiceClients,
    FakeSpeech,
    level,
)
from tests.test_activity_records import dashboard
from tests.test_admin_users import ADMIN, admin_beside
from tests.test_affinity import keep
from tests.test_call_records import call_recorded
from tests.test_call_turns import (  # noqa: F401
    INTERRUPTED_REPLY,
    INTERRUPTING,
    MANO_REPLY,
    NOW,
    SLOW_REPLY,
    CallUnderTest,
    kinds,
    mano_call,
    spoken,
    without_emotions,
)
from tests.test_conversation_events import record, shape
from tests.test_text_turn import start_conversation

REPLY = ["<ja>はい</ja><zh>好的</zh>"]
UNTIL = (START + timedelta(days=1)).isoformat()
"""When a cooldown begun at 0 as the tests begin ends."""
OUT_OF_LINE = level(1, out_of_line=True)


@pytest.fixture
def settings(settings: Settings) -> Settings:
    """With an admin, the judge model, and affinity on in `.env`."""
    return replace(settings, admins=frozenset({ADMIN}), affinity_and_gifts=True)


async def say(speech: FakeSpeech, browser: Browser, text: str) -> list[dict]:
    """Say `text` in the call; the turn's server messages."""
    await speech.stts[-1].hear(text)
    return await browser.turn()


async def test_the_turn_that_cools_her_has_her_hang_up_once_she_has_said_it(
    make_client: ClientFactory,
    settings: Settings,
    github: FakeIdentityProvider,
    speech: FakeSpeech,
):
    clock = FakeClock()
    clients = FakeServiceClients()
    clients.user_judge.judgings = [level(0)]
    llm = FakeLLM(REPLY)
    client = make_client(llm, clients=clients, clock=clock)
    conversation = await start_conversation(client)
    keep(settings.database_path, "producer", 1, clock.now)

    async with admin_beside(client, github) as admin, open_browser() as browser:
        await browser.call(client, conversation_id=conversation, own_keys=JUDGED_KEYS)
        await browser.connect()
        turn = await say(speech, browser, "随便你")
        ended = await browser.next_server_message("ended")
        await browser.hung_up()
        board = await call_recorded(admin)
    recorded = await record(client, conversation)

    assert turn[-1]["type"] == "done"
    assert ended["reason"] == "cooldown"
    assert ended["cooldown_until"] == UNTIL
    assert ended["counts"] is True
    assert shape(recorded) == ["user:随便你", "character:好的", "hung_up"]
    assert ended["event"] == recorded[-1]
    calls = board["calls"]
    assert {r: n for r, n in calls["by_result"].items() if n} == {"success": 1}
    assert {r: n for r, n in calls["end_reasons"].items() if n} == {"character_hung_up": 1}
    [mano] = board["affinity"]["characters"]
    assert (mano["judged"], mano["cooldowns"], mano["she_ended"]) == (1, 1, 1)


async def test_out_of_line_twice_in_a_call_she_hangs_up_and_the_next_call_starts_over(
    make_client: ClientFactory,
    settings: Settings,
    github: FakeIdentityProvider,
    speech: FakeSpeech,
):
    clients = FakeServiceClients()
    clients.user_judge.judgings = [OUT_OF_LINE] * 3
    llm = FakeLLM(REPLY, REPLY, REPLY)
    client = make_client(llm, clients=clients, clock=FakeClock())
    conversation = await start_conversation(client)

    async with admin_beside(client, github) as admin:
        async with open_browser() as first:
            await first.call(client, conversation_id=conversation, own_keys=JUDGED_KEYS)
            await first.connect()
            await say(speech, first, "你这个废物")
            await say(speech, first, "废物")
            ended = await first.next_server_message("ended")
            await first.hung_up()
        async with open_browser() as second:
            await second.call(client, conversation_id=conversation, own_keys=JUDGED_KEYS)
            await second.connect()
            again = await say(speech, second, "废物")
            await second.hang_up()
        async with asyncio.timeout(TIMEOUT):
            while sum((board := await dashboard(admin))["calls"]["end_reasons"].values()) < 2:
                await asyncio.sleep(0.05)
    recorded = await record(client, conversation)

    assert ended["reason"] == "she_hung_up"
    assert "cooldown_until" not in ended
    assert again[-1]["type"] == "done"
    assert shape(recorded).count("hung_up") == 1
    assert shape(recorded)[4] == "hung_up"
    reasons = board["calls"]["end_reasons"]
    assert {r: n for r, n in reasons.items() if n} == {"character_hung_up": 1, "hung_up": 1}


def one_by_one(n: int) -> list:
    """`n` things said in a call, each once the turn before is over."""
    return [frame for i in range(n) for frame in (spoken(f"第{i}句"), SleepFrame(0.5))]


async def test_hurt_turn_after_turn_she_warns_the_user_once_then_hangs_up(mano_call: CallUnderTest):
    llm = FakeLLM(*[MANO_REPLY] * 6)

    _, messages = await mano_call.run(llm, one_by_one(6), affinity=[level(1)] * 6)

    assert messages[-1]["type"] == "ended"
    assert messages[-1]["reason"] == "she_hung_up"
    assert "cooldown_until" not in messages[-1]
    assert shape(await record_of(mano_call))[-1] == "hung_up"


async def test_only_the_latest_turns_count_so_now_and_then_she_never_hangs_up(
    mano_call: CallUnderTest,
):
    # Hurt every other turn: twelve in all, but never more than eight in eight turns.
    llm = FakeLLM(*[MANO_REPLY] * 11)

    _, messages = await mano_call.run(
        llm, one_by_one(11), affinity=[level(1 if n % 2 == 0 else 2) for n in range(11)]
    )

    assert "ended" not in kinds(messages)


async def test_hanging_up_comes_before_the_turn_limit_the_same_turn_reaches(
    mano_call: CallUnderTest, settings: Settings
):
    keep(settings.database_path, "producer", 1, NOW)

    _, messages = await mano_call.run(
        FakeLLM(MANO_REPLY), [spoken("随便你")], limits=CallLimits(turns=1), affinity=[level(0)]
    )

    assert kinds(without_emotions(messages)) == ["user", "done", "ended"]
    assert messages[-1]["reason"] == "cooldown"


async def test_a_turn_that_fails_neither_has_her_hang_up_nor_counts(mano_call: CallUnderTest):
    llm = FakeLLM(MANO_REPLY, ["  "], MANO_REPLY, MANO_REPLY)

    _, messages = await mano_call.run(
        llm,
        # 每句隔开到上一回合说完：只隔 50 毫秒时，慢的机器上下一句会当成补充并进上一回合。
        [frame for n in range(4) for frame in (spoken(f"废物{n}"), SleepFrame(0.5))],
        affinity=[OUT_OF_LINE, OUT_OF_LINE, level(2), OUT_OF_LINE],
    )

    assert kinds(without_emotions(messages)) == [
        "user", "done", "user", "error", "user", "done", "user", "done", "ended"
    ]
    assert messages[-1]["reason"] == "she_hung_up"
    assert shape(await record_of(mano_call))[-1] == "hung_up"


async def test_a_follow_on_has_the_whole_judged_afresh_and_she_hangs_up_only_if_it_still_calls_for_it(
    mano_call: CallUnderTest,
):
    llm = FakeLLM(MANO_REPLY, SLOW_REPLY, MANO_REPLY, delay=0.3)

    _, messages = await mano_call.run(
        llm,
        [
            spoken("你这个废物"), SleepFrame(1.5),
            spoken("废物"), SleepFrame(0.1), InterruptionFrame(), SleepFrame(0.1),
            spoken("开玩笑的，对不起"), SleepFrame(1.5),
        ],
        affinity=[OUT_OF_LINE, OUT_OF_LINE, level(2)],
    )

    assert "ended" not in kinds(messages)
    assert "hung_up" not in shape(await record_of(mano_call))


async def test_her_last_line_cut_short_she_hangs_up_all_the_same(
    mano_call: CallUnderTest, settings: Settings
):
    keep(settings.database_path, "producer", 1, NOW)

    _, messages = await mano_call.run(
        FakeLLM(INTERRUPTED_REPLY, delay=0.3), [spoken("随便你"), *INTERRUPTING],
        affinity=[level(0)],
    )

    assert kinds(without_emotions(messages)) == ["user", "done", "ended"]
    assert messages[-1]["reason"] == "cooldown"


async def record_of(call: CallUnderTest) -> list[dict]:
    return await record(call._client, call.conversation.id)
