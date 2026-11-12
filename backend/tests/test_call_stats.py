"""Calls in stats (GLOSSARY.md「统计」, ADR-0021): each call that connected is kept in the
conversation it is in, when it connected and how long it lasted once it had, as its activity
record says, whoever hung up and whatever ended it, the conversation ended elsewhere
meanwhile or not; one that never connected is not. The range takes in those that connected
in it, where the user is: how many, how long all told, and each character's. Kept apart
from the conversation's record, they go with it, and with the user. Driven through the
backend's external API, with a browser calling in over a real WebRTC connection and fake
outside services; when a call connected is put in the database as if it had been then."""

import asyncio
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import pytest

from eidolon.config import Settings
from tests.browser import TIMEOUT, Browser, open_browser
from tests.conftest import ClientFactory
from tests.fakes import JUDGED_KEYS, FakeClock, FakeLLM, FakeServiceClients, FakeSpeech
from tests.test_conversation_events import record, shape
from tests.test_delete_account import DELETE
from tests.test_she_hangs_up import OUT_OF_LINE
from tests.test_stats import REPLY, TODAY, stats, tokyo
from tests.test_text_turn import send_turn, start_conversation


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()  # START: 21:00 on TODAY in Tokyo


async def kept(client: httpx.AsyncClient, calls: int) -> dict:
    """The stats' range, once it takes in `calls` calls: a call is kept as it is settled,
    just after the browser is let go of."""
    async with asyncio.timeout(TIMEOUT):
        while (got := (await stats(client))["range"])["calls"]["count"] != calls:
            await asyncio.sleep(0.05)
    return got


async def recorded_calls(database: Path, calls: int) -> list[float | None]:
    """How long each call lasted once connected, as its activity record says, once there are
    `calls` of them, oldest first."""
    async with asyncio.timeout(TIMEOUT):
        while True:
            with sqlite3.connect(database) as db:
                rows = db.execute(
                    "SELECT duration_s FROM activity_records WHERE kind = 'call' ORDER BY id"
                ).fetchall()
            if len(rows) == calls:
                return [duration for (duration,) in rows]
            await asyncio.sleep(0.05)


def connected_at(database: Path, when: datetime) -> None:
    """Have the call kept last have connected at `when`."""
    with sqlite3.connect(database) as db:
        db.execute(
            "UPDATE calls SET connected_at = ? WHERE id = (SELECT MAX(id) FROM calls)",
            (when.isoformat(),),
        )


def calls_kept(database: Path) -> int:
    with sqlite3.connect(database) as db:
        return db.execute("SELECT COUNT(*) FROM calls").fetchone()[0]


async def call(client: httpx.AsyncClient, conversation: str, speech: FakeSpeech) -> None:
    """A call in the conversation that takes a turn, then hung up."""
    async with open_browser() as browser:
        await browser.call(client, conversation_id=conversation)
        await browser.connect()
        await speech.stts[-1].hear("你好")
        await browser.turn()
        await browser.hang_up()


async def test_a_call_that_connected_counts_for_as_long_as_its_record_says_and_one_that_did_not_does_not(
    make_client: ClientFactory, settings: Settings, speech: FakeSpeech, browser: Browser,
    clock: FakeClock,
):
    client = make_client(FakeLLM(REPLY), clock=clock)
    conversation = await start_conversation(client, "kogane")
    await call(client, conversation, speech)
    got = await kept(client, 1)
    [lasted] = await recorded_calls(settings.database_path, 1)

    # Its speech synthesis failing before any turn, the next never really connected.
    await browser.call(client, conversation_id=conversation)
    await browser.connect()
    await speech.ttss[-1].break_down()
    assert (await browser.next_server_message("ended"))["reason"] == "not_connected"
    await recorded_calls(settings.database_path, 2)
    after = (await stats(client))["range"]

    assert lasted is not None and lasted > 0
    assert got["calls"] == {"count": 1, "seconds": lasted}
    assert got["characters"] == [
        {"character_id": "kogane", "turns": 1, "days_known": 1, "call_seconds": lasted}
    ]
    assert after["calls"] == got["calls"]
    # Not in the conversation's record, nor counted as anything else.
    assert shape(await record(client, conversation)) == ["user:你好", "character:好的"]
    assert sum((await stats(client))["all_hours"]) == 1  # its turn alone


async def test_a_call_she_hangs_up_as_she_ends_the_conversation_elsewhere_counts(
    make_client: ClientFactory, settings: Settings, speech: FakeSpeech, clock: FakeClock
):
    clients = FakeServiceClients()
    clients.user_judge.judgings = [OUT_OF_LINE, OUT_OF_LINE]
    client = make_client(
        FakeLLM(REPLY, REPLY), clients=clients, clock=clock,
        settings=replace(settings, affinity_and_gifts=True),
    )
    conversation = await start_conversation(client)

    async with open_browser() as browser:
        await browser.call(client, conversation_id=conversation)
        await browser.connect()
        for text in ("第一句", "第二句"):
            await send_turn(client, conversation, text, own_keys=JUDGED_KEYS)
        assert (await browser.next_server_message("ended"))["reason"] == "she_hung_up"
        await browser.hung_up()

    got = await kept(client, 1)
    assert got["calls"]["seconds"] > 0
    assert shape(await record(client, conversation))[-1] == "ended"


async def test_she_is_known_from_a_call_in_which_nothing_was_said(
    make_client: ClientFactory, settings: Settings, browser: Browser, clock: FakeClock
):
    client = make_client(FakeLLM(), clock=clock)
    await browser.call(client, conversation_id=await start_conversation(client))
    await browser.connect()
    await browser.hang_up()
    await kept(client, 1)
    connected_at(settings.database_path, tokyo(TODAY - timedelta(days=9), 12))

    got = await stats(client)

    [mano] = got["range"]["characters"]
    assert (mano["character_id"], mano["turns"], mano["days_known"]) == ("mano", 0, 10)
    assert mano["call_seconds"] == got["range"]["calls"]["seconds"] > 0
    assert sum(got["all_hours"]) == 0  # not a day she came


async def test_calls_count_in_the_range_by_when_they_connected_where_the_user_is(
    make_client: ClientFactory, settings: Settings, speech: FakeSpeech, clock: FakeClock
):
    database = settings.database_path
    client = make_client(FakeLLM(*[REPLY] * 3), clock=clock)
    conversation = await start_conversation(client)
    # The 30th day back counting today, just past midnight in Tokyo, still the 31st in UTC.
    for n, when in enumerate(
        (tokyo(TODAY - timedelta(days=29), 0, 30), tokyo(TODAY - timedelta(days=30), 23),
         tokyo(TODAY - timedelta(days=365), 12)),
        start=1,
    ):
        await call(client, conversation, speech)
        await kept(client, n)
        connected_at(database, when)
    lasted = await recorded_calls(database, 3)

    got = {span: (await stats(client, range=span))["range"]["calls"] for span in ("30d", "1y", "all")}
    in_utc = (await stats(client, {"X-Timezone": "UTC"}, "30d"))["range"]["calls"]

    assert {span: c["count"] for span, c in got.items()} == {"30d": 1, "1y": 2, "all": 3}
    assert got["1y"]["seconds"] == pytest.approx(sum(d or 0 for d in lasted[:2]))
    assert in_utc["count"] == 0


async def test_calls_go_with_their_conversation_and_with_the_user(
    make_client: ClientFactory, settings: Settings, speech: FakeSpeech, clock: FakeClock
):
    database = settings.database_path
    client = make_client(FakeLLM(*[REPLY] * 3), clock=clock)
    past = await start_conversation(client)
    await call(client, past, speech)
    current = await start_conversation(client)
    await call(client, current, speech)
    await kept(client, 2)

    assert (await client.delete(f"/api/conversations/{past}")).status_code == 204
    after = (await stats(client))["range"]
    assert after["calls"]["count"] == 1 and calls_kept(database) == 1
    assert after["characters"][0]["call_seconds"] == after["calls"]["seconds"]

    assert (await client.post("/api/account/delete", json=DELETE)).status_code == 204
    assert calls_kept(database) == 0


async def test_a_user_sees_only_their_own_calls(
    make_client: ClientFactory, speech: FakeSpeech, clock: FakeClock
):
    producer = make_client(FakeLLM(REPLY), clock=clock)
    friend = make_client(FakeLLM(), "friend", clock=clock)
    await call(producer, await start_conversation(producer), speech)
    await kept(producer, 1)

    theirs = (await stats(friend))["range"]

    assert theirs["calls"] == {"count": 0, "seconds": 0}
    assert theirs["characters"] == []
