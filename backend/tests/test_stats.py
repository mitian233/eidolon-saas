"""Stats (GLOSSARY.md「统计」), the part that does not change with the range: how many days
since the user signed up, the days in a row they have come (now and at the longest), the
hours they come at, and each day of the past 52 weeks. A turn counts. Dates and hours are
the producer profile's time zone's, else the browser's (`X-Timezone`). Only what is still
in their conversations counts: a past conversation deleted, it no longer does, though the
days since they signed up stay. Driven through the backend's external API, the clock moved
by hand and when things were recorded put in the database as if they had happened then."""

import sqlite3
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from eidolon.config import Settings
from tests.conftest import Characters, ClientFactory
from tests.fakes import START, FakeClock, FakeLLM
from tests.test_text_turn import send_turn, start_conversation

REPLY = ["<ja>はい</ja><zh>好的</zh>"]

TODAY = date(2026, 9, 25)
"""START's day in Tokyo (21:00 there), a Friday; the week the heatmap ends in began on
Monday the 21st."""

HEATMAP_FROM = date(2025, 9, 22)
"""The Monday 52 weeks before this week's."""

TOKYO = {"X-Timezone": "Asia/Tokyo"}


async def stats(
    client: httpx.AsyncClient, headers: dict[str, str] = TOKYO, range: str | None = None
) -> dict:
    res = await client.get("/api/stats", headers=headers, params={"range": range} if range else None)
    assert res.status_code == 200, res.text
    return res.json()


def tokyo(day: date, hour: int, minute: int = 0) -> datetime:
    """That time of day in Tokyo, in UTC as the store writes."""
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=UTC) - timedelta(hours=9)


def registered_at(database: Path, when: datetime, name: str = "producer") -> None:
    with sqlite3.connect(database) as db:
        db.execute("UPDATE users SET created_at = ? WHERE name = ?", (when.isoformat(), name))


def said_at(database: Path, text: str, when: datetime) -> None:
    """Have the user's message `text` said at `when`."""
    with sqlite3.connect(database) as db:
        moved = db.execute(
            "UPDATE messages SET created_at = ? WHERE role = 'user' AND text = ?",
            (when.isoformat(), text),
        ).rowcount
    assert moved == 1


async def say(client: httpx.AsyncClient, database: Path, conversation: str, text: str,
              when: datetime) -> None:
    """Take a turn in the conversation, said at `when`."""
    assert (await send_turn(client, conversation, text))[-1]["type"] == "done"
    said_at(database, text, when)


def day(stats: dict, which: date) -> int:
    """The heatmap's count on the day."""
    return stats["heatmap"]["counts"][(which - date.fromisoformat(stats["heatmap"]["from"])).days]


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(START)


@pytest.fixture
def meguru(characters: Characters) -> None:
    """Meguru as well, configured after Kogane but before her in the idols' order, as Kogane
    has no idol number."""
    characters.add("meguru", "八宮めぐる", "# 人设\n你是八宮めぐる。", idol_id=2)


async def test_stats_need_a_session(make_client: ClientFactory):
    client = make_client(FakeLLM(), user=None)

    assert (await client.get("/api/stats")).status_code == 401


async def test_a_new_user_has_known_them_a_day_and_come_on_none(
    make_client: ClientFactory, settings: Settings, clock: FakeClock
):
    client = make_client(FakeLLM(), clock=clock)
    registered_at(settings.database_path, clock.now - timedelta(hours=1))

    got = await stats(client)

    assert got["days_known"] == 1
    assert got["visits"] == {"current": 0, "longest": 0}
    assert got["all_hours"] == [0] * 24
    assert got["heatmap"]["from"] == HEATMAP_FROM.isoformat()
    # 52 whole weeks, and this one up to today, a Friday.
    assert got["heatmap"]["counts"] == [0] * (52 * 7 + 5)
    assert got["range"] == {
        "span": "all", "turns": 0, "by_hour": [0] * 24, "characters": [],
        "calls": {"count": 0, "seconds": 0}, "gifts": None,
    }


async def test_the_days_since_signing_up_count_from_that_day_in_their_time_zone(
    make_client: ClientFactory, settings: Settings, clock: FakeClock
):
    client = make_client(FakeLLM(), clock=clock)
    # The 16th at 1:00 in Tokyo, still the 15th in UTC.
    registered_at(settings.database_path, tokyo(date(2026, 9, 16), 1))

    assert (await stats(client))["days_known"] == 10
    assert (await stats(client, {"X-Timezone": "UTC"}))["days_known"] == 11


async def test_a_turn_counts_on_the_day_and_at_the_hour_it_was_where_the_user_is(
    make_client: ClientFactory, settings: Settings, clock: FakeClock
):
    client = make_client(FakeLLM(REPLY), clock=clock)
    conversation = await start_conversation(client)
    # Just past midnight on the 25th in Tokyo: 15:30 on the 24th in UTC.
    await say(client, settings.database_path, conversation, "晚安", tokyo(TODAY, 0, 30))

    in_tokyo = await stats(client)
    in_utc = await stats(client, {"X-Timezone": "UTC"})
    assert (await client.put("/api/profile", json={"timezone": "UTC"})).status_code == 200
    profile_first = await stats(client)  # the browser still says Tokyo

    assert in_tokyo["all_hours"][0] == 1 and sum(in_tokyo["all_hours"]) == 1
    assert day(in_tokyo, TODAY) == 1 and sum(in_tokyo["heatmap"]["counts"]) == 1
    for got in (in_utc, profile_first):
        assert got["all_hours"][15] == 1
        assert day(got, TODAY - timedelta(days=1)) == 1


async def test_only_the_past_52_weeks_and_this_one_are_in_the_heatmap_but_every_hour_counts(
    make_client: ClientFactory, settings: Settings, clock: FakeClock
):
    database = settings.database_path
    client = make_client(FakeLLM(REPLY, REPLY), clock=clock)
    conversation = await start_conversation(client)
    await say(client, database, conversation, "第一句", tokyo(HEATMAP_FROM, 10))
    await say(client, database, conversation, "更早", tokyo(HEATMAP_FROM - timedelta(days=1), 22))

    got = await stats(client)

    assert got["heatmap"]["counts"][0] == 1
    assert sum(got["heatmap"]["counts"]) == 1
    assert got["all_hours"][10] == 1 and got["all_hours"][22] == 1


async def test_not_having_come_yet_today_does_not_break_the_days_in_a_row(
    make_client: ClientFactory, settings: Settings, clock: FakeClock
):
    database = settings.database_path
    client = make_client(FakeLLM(*[REPLY] * 4), clock=clock)
    conversation = await start_conversation(client)
    for ago in (5, 2, 1):
        await say(client, database, conversation, f"{ago}天前", tokyo(TODAY - timedelta(days=ago), 12))

    assert (await stats(client))["visits"] == {"current": 2, "longest": 2}

    await say(client, database, conversation, "今天", tokyo(TODAY, 12))

    assert (await stats(client))["visits"] == {"current": 3, "longest": 3}


async def test_a_deleted_past_conversation_no_longer_counts_but_the_days_known_stay(
    make_client: ClientFactory, settings: Settings, clock: FakeClock
):
    database = settings.database_path
    client = make_client(FakeLLM(REPLY, REPLY), clock=clock)
    registered_at(database, tokyo(TODAY - timedelta(days=30), 12))
    past = await start_conversation(client)
    await say(client, database, past, "上周", tokyo(TODAY - timedelta(days=1), 23))
    current = await start_conversation(client)
    await say(client, database, current, "今天", tokyo(TODAY, 9))
    before = await stats(client)

    assert (await client.delete(f"/api/conversations/{past}")).status_code == 204
    after = await stats(client)

    assert before["visits"] == {"current": 2, "longest": 2}
    assert after["visits"] == {"current": 1, "longest": 1}
    assert (day(before, TODAY - timedelta(days=1)), day(after, TODAY - timedelta(days=1))) == (1, 0)
    assert (before["all_hours"][23], after["all_hours"][23]) == (1, 0)
    assert after["all_hours"][9] == 1
    assert before["days_known"] == after["days_known"] == 31


async def test_a_user_sees_only_their_own(
    make_client: ClientFactory, settings: Settings, clock: FakeClock
):
    producer = make_client(FakeLLM(REPLY), clock=clock)
    friend = make_client(FakeLLM(), "friend", clock=clock)
    conversation = await start_conversation(producer)
    await say(producer, settings.database_path, conversation, "你好", tokyo(TODAY, 9))

    theirs = await stats(friend)

    assert theirs["all_hours"] == [0] * 24
    assert theirs["visits"] == {"current": 0, "longest": 0}
    assert (await stats(producer))["all_hours"][9] == 1


async def test_the_range_is_the_past_30_or_365_days_where_the_user_is_or_all_of_it(
    make_client: ClientFactory, settings: Settings, clock: FakeClock
):
    database = settings.database_path
    client = make_client(FakeLLM(*[REPLY] * 4), clock=clock)
    conversation = await start_conversation(client)
    # The 30th day back counting today, just past midnight in Tokyo, still the 31st in UTC.
    await say(client, database, conversation, "三十天", tokyo(TODAY - timedelta(days=29), 0, 30))
    await say(client, database, conversation, "三十一天", tokyo(TODAY - timedelta(days=30), 23))
    await say(client, database, conversation, "一年", tokyo(TODAY - timedelta(days=364), 12))
    await say(client, database, conversation, "一年多", tokyo(TODAY - timedelta(days=365), 12))

    got = {span: await stats(client, range=span) for span in ("30d", "1y", "all")}
    by_default = await stats(client)
    in_utc = await stats(client, {"X-Timezone": "UTC"}, "30d")

    assert {span: s["range"]["turns"] for span, s in got.items()} == {"30d": 1, "1y": 3, "all": 4}
    assert [s["range"]["span"] for s in got.values()] == ["30d", "1y", "all"]
    assert by_default == got["all"]
    assert got["30d"]["range"]["by_hour"][0] == 1 and sum(got["30d"]["range"]["by_hour"]) == 1
    assert got["1y"]["range"]["by_hour"][12] == 1 and got["all"]["range"]["by_hour"][12] == 2
    assert in_utc["range"]["turns"] == 0
    # What does not change with the range does not.
    upper = ("days_known", "visits", "all_hours", "heatmap")
    assert all({k: s[k] for k in upper} == {k: by_default[k] for k in upper} for s in got.values())


async def test_each_character_has_her_turns_and_the_days_since_the_first_thing_left_with_her(
    make_client: ClientFactory, settings: Settings, clock: FakeClock, meguru: None,
):
    database = settings.database_path
    client = make_client(FakeLLM(*[REPLY] * 5), clock=clock)
    past = await start_conversation(client)
    await say(client, database, past, "很久以前", tokyo(TODAY - timedelta(days=99), 12))
    await say(client, database, past, "上个月", tokyo(TODAY - timedelta(days=40), 12))
    current = await start_conversation(client)
    await say(client, database, current, "这周", tokyo(TODAY - timedelta(days=4), 12))
    with_kogane = await start_conversation(client, "kogane")
    await say(client, database, with_kogane, "恋鐘", tokyo(TODAY - timedelta(days=2), 12))
    with_meguru = await start_conversation(client, "meguru")
    await say(client, database, with_meguru, "めぐる", tokyo(TODAY, 12))

    everything = (await stats(client))["range"]["characters"]
    recent = (await stats(client, range="30d"))["range"]["characters"]
    assert (await client.delete(f"/api/conversations/{past}")).status_code == 204
    after = (await stats(client))["range"]["characters"]

    # In the order the user made them.
    assert everything == [
        {"character_id": "mano", "turns": 3, "days_known": 100, "call_seconds": 0},
        {"character_id": "kogane", "turns": 1, "days_known": 3, "call_seconds": 0},
        {"character_id": "meguru", "turns": 1, "days_known": 1, "call_seconds": 0},
    ]
    assert [(c["character_id"], c["turns"], c["days_known"]) for c in recent] == [
        ("mano", 1, 100), ("kogane", 1, 3), ("meguru", 1, 1),
    ]
    assert after[0] == {"character_id": "mano", "turns": 1, "days_known": 5, "call_seconds": 0}