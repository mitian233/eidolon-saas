"""A user's recent usage in the admin console: how many turns and calls they took in the
last 24 hours, 7 days and 30 days, and how many were rejected, on the deployer's keys and
on their own apart, from the activity records; the list shows the last 24 hours' and is
sorted by them on request, before it is cut into pages. Nothing anyone said shows: that
the user's details hold none of it is test_admin_users.py's to check. Driven through the
backend's external API with a clock the tests control."""

import asyncio
from dataclasses import replace

import httpx
import pytest

from eidolon.config import Settings, UsageLimits
from tests.browser import TIMEOUT, open_browser
from tests.conftest import ClientFactory, character_id
from tests.fakes import FakeClock, FakeIdentityProvider, FakeLLM, FakeLLMService, FakeSpeech
from tests.test_admin_users import ADMIN, admin_client, details, find, users
from tests.test_own_speech_keys import MY_LLM, own_keys
from tests.test_rate_limit import REPLY, post_turn
from tests.test_text_turn import send_turn, start_conversation


@pytest.fixture
def settings(settings: Settings) -> Settings:
    """With an admin, and the deployment's limits: 2 turns and 1 call an hour."""
    return replace(
        settings,
        admins=frozenset({ADMIN}),
        usage_limits=UsageLimits(turns_per_hour=2, calls_per_hour=1),
    )


async def call(
    client: httpx.AsyncClient, conversation_id: str, speech: FakeSpeech, **request_data
) -> int:
    """Place a call and, if it is let through, take a turn in it and hang up; the status
    placing it was answered with."""
    async with open_browser() as browser:
        res = await browser.call(client, conversation_id=conversation_id, **request_data)
        if res.status_code != 200:
            return res.status_code
        await browser.connect()
        await speech.stts[-1].hear("你好")
        await browser.turn()
        await browser.hang_up()
    return res.status_code


async def calls_recorded(admin: httpx.AsyncClient, user_id: str, count: int) -> dict:
    """The user's details, once the last 30 days hold `count` calls: a call is recorded
    just after it hangs up."""
    async with asyncio.timeout(TIMEOUT):
        while True:
            found = await details(admin, user_id)
            month = found["usage"]["30d"]["calls"]
            if month["deployer"] + month["own_keys"] >= count:
                return found
            await asyncio.sleep(0.05)


async def test_the_users_turns_calls_and_rejections_in_each_range_on_whose_keys(
    make_client: ClientFactory,
    github: FakeIdentityProvider,
    speech: FakeSpeech,
    own_llm: FakeLLMService,
):
    clock = FakeClock()
    own_llm.llm = FakeLLM(REPLY, REPLY)
    producer = make_client(FakeLLM(REPLY, REPLY, REPLY, REPLY), clock=clock)
    conversation_id = await start_conversation(producer)

    await send_turn(producer, conversation_id, "早上好")  # 35 days ago, out of every range
    clock.advance(days=10)
    await send_turn(producer, conversation_id, "在吗")  # 25 days ago
    await send_turn(producer, conversation_id, "在吗")
    assert (await post_turn(producer, conversation_id)).status_code == 429
    clock.advance(days=20)
    assert await call(producer, conversation_id, speech) == 200  # 5 days ago
    assert await call(producer, conversation_id, speech) == 429
    clock.advance(days=5)
    await send_turn(producer, conversation_id, "在吗", own_llm=MY_LLM)  # now, on the user's own keys
    brought = own_keys("llm", "stt", "tts")
    assert await call(producer, conversation_id, speech, own_keys=brought) == 200
    admin = await admin_client(make_client, github, clock=clock)
    found = await calls_recorded(admin, (await find(admin, "producer"))["id"], 2)

    def counted(deployer: int, own_keys: int) -> dict:
        return {"deployer": deployer, "own_keys": own_keys}

    # The turns taken in the calls are turns too; a rejection is not counted as a turn
    # or a call.
    assert found["usage"] == {
        "24h": {"turns": counted(0, 2), "calls": counted(0, 1), "rejected": counted(0, 0)},
        "7d": {"turns": counted(1, 2), "calls": counted(1, 1), "rejected": counted(1, 0)},
        "30d": {"turns": counted(3, 2), "calls": counted(1, 1), "rejected": counted(2, 0)},
    }
    assert (await find(admin, "producer"))["usage_24h"] == {"turns": 2, "calls": 1}


async def take_turns(client: httpx.AsyncClient, turns: int, character: str) -> None:
    conversation_id = await start_conversation(client, character)
    for _ in range(turns):
        await send_turn(client, conversation_id, "在吗")


async def test_the_list_is_sorted_by_the_last_24_hours_turns_or_calls_before_its_pages(
    make_client: ClientFactory, github: FakeIdentityProvider, speech: FakeSpeech
):
    clock = FakeClock()
    admin = await admin_client(make_client, github, clock=clock)
    busy = make_client(FakeLLM(REPLY, REPLY), "busy-yesterday", clock=clock)
    mano = make_client(FakeLLM(REPLY), "mano-fan", clock=clock)
    kogane = make_client(FakeLLM(REPLY, REPLY), "kogane-fan", clock=clock)
    caller = make_client(FakeLLM(REPLY), "caller", clock=clock)
    await take_turns(busy, 2, character_id("mano", "busy-yesterday"))
    clock.advance(hours=25)
    await take_turns(mano, 1, character_id("mano", "mano-fan"))
    await take_turns(kogane, 2, character_id("mano", "kogane-fan"))
    assert await call(caller, await start_conversation(caller, character_id("mano", "caller")), speech) == 200
    await calls_recorded(admin, (await find(admin, "caller"))["id"], 1)

    def named(page: dict) -> list[str]:
        return [u["name"] for u in page["users"]]

    by_turns = await users(admin, sort="turns", limit=2)

    # Equal in turns, newest first; the caller's one turn was in the call.
    assert named(by_turns) == ["kogane-fan", "caller"]
    assert by_turns["total"] == 5
    assert named(await users(admin, sort="turns", offset=2)) == [
        "mano-fan", "busy-yesterday", "boss"
    ]
    assert named(await users(admin, sort="turns", q="-fan")) == ["kogane-fan", "mano-fan"]
    assert named(await users(admin, sort="calls", limit=1)) == ["caller"]
    assert [(u["name"], u["usage_24h"]) for u in (await users(admin, limit=2))["users"]] == [
        ("caller", {"turns": 1, "calls": 1}), ("kogane-fan", {"turns": 2, "calls": 0}),
    ]
