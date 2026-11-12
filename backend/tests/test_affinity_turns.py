"""What the user says changes her affinity (GLOSSARY.md「好感度」), as the deployer's judge
model judges each turn before she replies: by a step for each of five levels, from hurting
her (−1.5) to making her very happy (+0.2), the likeliest level taken and two as likely as each
other changing nothing; by −10 for what is out of line, whatever the level; never up for
what tries to dictate it. Turns raise it by 0.6 a day at most, the day in Beijing wherever
the user is, the last of it as far as it goes; nothing limits how far they lower it. It falls no lower than
0, where a cooldown begins.

It changes as the turn is recorded, and the change is recorded with her reply: up or down,
to which tier, whether that is another, whether a cooldown began; nothing where nothing
changed. `done` tells it and where her affinity is left; reading the conversation's
messages tells it again. A turn not recorded changes nothing, nor one the judge model
cannot judge. Where retrieval is on its judge asks the questions in the same request;
otherwise they are asked apart. Off, the judge model is never asked them.

Driven through the backend's external API, the judge model faked turn by turn; what is
kept is read from the database for the exact steps."""

import sqlite3
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import httpx
import pytest

from eidolon.config import Settings
from eidolon.llm import LLMError
from tests.conftest import ClientFactory
from tests.fakes import (
    JUDGED_KEYS,
    FakeClock,
    FakeEmbedder,
    FakeIdentityProvider,
    FakeLLM,
    FakeReranker,
    FakeServiceClients,
    Judging,
    level,
)
from tests.test_admin_users import admin_beside
from tests.test_affinity import AFFINITY, keep, status
from tests.test_delete_account import user_id
from tests.test_text_turn import leave_turn, send_turn, start_conversation
from tests.fakes import RETRIEVAL_KEYS

REPLY = ["<ja>はい</ja><zh>好的</zh>"]
TRUST = {"tier": "trust", "cooldown_until": None}


@pytest.fixture
def settings(settings: Settings) -> Settings:
    """With an admin, the judge model, and affinity on in `.env`."""
    return replace(settings, admins=frozenset({("github", "9001")}), affinity_and_gifts=True,)


def value(database: Path, user: str = "producer", character: str = "mano") -> float | None:
    """Her affinity with the user as last kept; None if never."""
    with sqlite3.connect(database) as db:
        row = db.execute(
            "SELECT value FROM affinities WHERE user_id = ? AND character_id = ?",
            (user_id(database, user), character),
        ).fetchone()
    return row and row[0]


def judge_calls(database: Path) -> int:
    with sqlite3.connect(database) as db:
        return db.execute("SELECT COUNT(*) FROM service_calls WHERE service = 'judge'").fetchone()[0]


def change(up: bool, tier: str, *, tier_changed: bool = False, cooldown: bool = False) -> dict:
    return {"up": up, "tier_changed": tier_changed, "tier": tier, "cooldown": cooldown,
            "thawed": False}


async def turns(
    client: httpx.AsyncClient, database: Path, conversation: str, count: int, keys: dict = JUDGED_KEYS
) -> list[tuple[float | None, dict]]:
    """Take `count` turns: the value each leaves, and its `done`."""
    taken = []
    for i in range(count):
        events = await send_turn(client, conversation, f"第{i}句", own_keys=keys)
        taken.append((value(database), events[-1]))
    return taken


async def test_each_level_changes_it_by_its_step_and_two_as_likely_change_nothing(
    make_client: ClientFactory, settings: Settings
):
    clients = FakeServiceClients()
    clients.user_judge.judgings = [
        level(0), level(1), level(2), level(3), level(4), Judging({1: 0.4, 3: 0.4, 2: 0.2}),
    ]
    client = make_client(FakeLLM(*[REPLY] * 6), clients=clients, clock=FakeClock())
    conversation = await start_conversation(client)

    taken = await turns(client, settings.database_path, conversation, 6)
    messages = (await client.get(f"/api/conversations/{conversation}/messages")).json()

    assert [v for v, _ in taken] == pytest.approx([48.5, 48, 48, 48.1, 48.3, 48.3])
    assert [done["message"]["affinity"] for _, done in taken] == [
        change(False, "trust"), change(False, "trust"), None,
        change(True, "trust"), change(True, "trust"), None,
    ]
    assert all(done["affinity"] == TRUST for _, done in taken)
    assert [m["affinity"] for m in messages if m["role"] == "character"] == [
        done["message"]["affinity"] for _, done in taken
    ]
    assert [m["affinity"] for m in messages if m["role"] == "user"] == [None] * 6
    # Retrieval off: each turn's questions in a request of their own, recorded as one.
    assert [kind for _, kind in clients.user_judge.asked] == ["affinity"] * 6
    assert clients.user_judge.affinity_asked == [f"第{i}句" for i in range(6)]
    assert judge_calls(settings.database_path) == 6


async def test_out_of_line_lowers_it_by_ten_and_dictating_it_never_raises_it(
    make_client: ClientFactory, settings: Settings
):
    clients = FakeServiceClients()
    clients.user_judge.judgings = [
        level(4, out_of_line=True), level(4, manipulation=True), level(1, manipulation=True),
    ]
    client = make_client(FakeLLM(*[REPLY] * 3), clients=clients, clock=FakeClock())
    conversation = await start_conversation(client)

    taken = await turns(client, settings.database_path, conversation, 3)

    assert [v for v, _ in taken] == pytest.approx([40, 40, 39.5])
    assert [done["message"]["affinity"] for _, done in taken] == [
        change(False, "trust"), None, change(False, "distant", tier_changed=True),
    ]
    assert taken[-1][1]["affinity"] == {"tier": "distant", "cooldown_until": None}


async def test_turns_raise_it_by_0_6_a_day_at_most_the_day_in_beijing(
    make_client: ClientFactory, settings: Settings
):
    clock = FakeClock()  # 12:00 UTC, 20:00 in Beijing, 21:00 in Tokyo
    clients = FakeServiceClients()
    clients.user_judge.judgings = [
        level(4), level(4), level(3), level(4), level(3), level(0),
        level(4), level(4), level(4), level(4),
    ]
    client = make_client(FakeLLM(*[REPLY] * 10), clients=clients, clock=clock)
    await client.put("/api/profile", json={"timezone": "Asia/Tokyo"})
    conversation = await start_conversation(client)
    keep(settings.database_path, "producer", 60, clock.now)  # above the normal value, not recovering

    today = await turns(client, settings.database_path, conversation, 6)
    clock.advance(hours=3, minutes=30)  # 00:30 the next day in Tokyo, 23:30 in Beijing
    in_tokyo = await turns(client, settings.database_path, conversation, 2)
    clock.advance(hours=1)  # 00:30 the next day in Beijing
    tomorrow = await turns(client, settings.database_path, conversation, 2)

    # The fourth turn raises it by the 0.1 left of the day's 0.6; lowering it gives none back.
    assert [v for v, _ in today] == pytest.approx([60.2, 60.4, 60.5, 60.6, 60.6, 59.1])
    assert today[4][1]["message"]["affinity"] is None
    assert [v for v, _ in in_tokyo] == pytest.approx([59.1, 59.1])
    assert [v for v, _ in tomorrow] == pytest.approx([59.3, 59.5])


async def test_what_the_steps_fractions_leave_of_the_day_is_no_sliver_to_raise_it_by(
    make_client: ClientFactory, settings: Settings
):
    clock = FakeClock()
    clients = FakeServiceClients()
    clients.user_judge.judgings = [level(3)] * 7
    client = make_client(FakeLLM(*[REPLY] * 7), clients=clients, clock=clock)
    conversation = await start_conversation(client)
    keep(settings.database_path, "producer", 63.7, clock.now)  # six 0.1s from it leave one

    taken = await turns(client, settings.database_path, conversation, 7)

    assert taken[-1][0] == pytest.approx(64.3)
    assert taken[-1][1]["message"]["affinity"] is None

async def test_it_falls_no_lower_than_0_where_a_cooldown_begins(
    make_client: ClientFactory, settings: Settings
):
    clock = FakeClock()
    clients = FakeServiceClients()
    clients.user_judge.judgings = [level(0)]
    client = make_client(FakeLLM(REPLY), clients=clients, clock=clock)
    keep(settings.database_path, "producer", 1, clock.now)
    conversation = await start_conversation(client)

    [(fell, done)] = await turns(client, settings.database_path, conversation, 1)

    assert fell == 0
    assert done["message"]["affinity"] == change(False, "cold", cooldown=True)
    assert done["affinity"] == {
        "tier": "cold", "cooldown_until": (clock.now + timedelta(days=1)).isoformat()
    }


async def test_a_turn_the_judge_model_cannot_judge_changes_nothing_and_goes_on(
    make_client: ClientFactory, settings: Settings
):
    clients = FakeServiceClients()
    clients.user_judge.judgings = [Judging(fails=True)]
    client = make_client(FakeLLM(REPLY), clients=clients)
    conversation = await start_conversation(client)

    [(kept, done)] = await turns(client, settings.database_path, conversation, 1)

    assert kept is None
    assert done["type"] == "done"
    assert done["message"]["affinity"] is None
    assert done["affinity"] == TRUST


async def test_a_turn_not_recorded_changes_nothing(
    make_client: ClientFactory, settings: Settings
):
    clients = FakeServiceClients()
    clients.user_judge.judgings = [level(0), level(0)]
    client = make_client(
        FakeLLM(LLMError("model is down"), ["<ja>は", "い</ja><zh>好的</zh>"], delay=0.05),
        clients=clients,
    )
    conversation = await start_conversation(client)

    failed = await send_turn(client, conversation, "你好", own_keys=JUDGED_KEYS)
    left = await leave_turn(client, conversation, "你好", after="delta", own_keys=JUDGED_KEYS)
    rejected = await send_turn(client, conversation, " ", own_keys=JUDGED_KEYS)

    assert [failed[-1]["type"], rejected[-1]["type"]] == ["error", "error"]
    assert left[-1]["type"] == "delta"
    assert clients.user_judge.affinity_asked == ["你好", "你好"]  # judged, never changed
    assert value(settings.database_path) is None
    assert (await status(client)).json() == TRUST


async def test_with_retrieval_on_the_questions_go_in_its_request_and_fail_with_it(
    make_client: ClientFactory, settings: Settings
):
    clients = FakeServiceClients()
    clients.user_judge.judgings = [level(4), Judging(fails=True)]
    client = make_client(
        FakeLLM(REPLY, REPLY), clients=clients, embedder=FakeEmbedder(),
        reranker=FakeReranker(), clock=FakeClock(),
    )
    conversation = await start_conversation(client)

    taken = await turns(client, settings.database_path, conversation, 2, RETRIEVAL_KEYS)

    assert [v for v, _ in taken] == pytest.approx([50.2, 50.2])
    assert taken[1][1]["type"] == "done"
    assert [kind for _, kind in clients.user_judge.asked] == ["turn", "turn"]
    assert judge_calls(settings.database_path) == 2


async def test_off_the_judge_model_is_never_asked_and_on_again_it_is_from_the_next_turn(
    make_client: ClientFactory, settings: Settings, github: FakeIdentityProvider
):
    clients = FakeServiceClients()
    clients.user_judge.judgings = [level(0)]
    client = make_client(
        FakeLLM(REPLY, REPLY),
        clients=clients,
        settings=replace(settings, affinity_and_gifts=False),
        clock=FakeClock(),
    )
    conversation = await start_conversation(client)

    [(off, done_off)] = await turns(client, settings.database_path, conversation, 1)
    async with admin_beside(client, github) as admin:
        assert (await admin.put(AFFINITY, json={"enabled": True})).status_code == 200
    [(on, done_on)] = await turns(client, settings.database_path, conversation, 1)

    assert off is None
    assert done_off["affinity"] is None
    assert done_off["message"]["affinity"] is None
    assert len(clients.user_judge.affinity_asked) == 1  # only once on
    assert on == 48.5
    assert done_on["affinity"] == TRUST
