"""Deleting all of a user's data: once they confirm, their characters, memories,
conversations, producer profile, sign-in methods, sessions and usage are gone for good,
from every table, and they are signed out everywhere. Signing in again with the same
identity makes a new user; nobody else's data is touched."""

import asyncio
import sqlite3
from pathlib import Path

import httpx
import pytest

import eidolon.data_access
from eidolon.config import Settings
from tests.browser import Browser
from tests.conftest import (
    ClientFactory,
    agree_to_terms,
    character_id,
    github_identity,
    sign_in_with,
)
from tests.fakes import (
    FakeBackgroundLLM,
    FakeClock,
    FakeEmbedder,
    FakeIdentityProvider,
    FakeJudge,
    FakeLLM,
    FakeReranker,
    FakeSpeech,
)
from tests.test_concurrent_calls import another_user
from tests.test_data_access import emptied, log_of, reading
from tests.test_service_status import backend_of
from tests.test_shared_memory import CAT, memorized
from tests.test_text_turn import send_turn, start_conversation

REPLY = ["<ja>はいっ</ja><zh>好的</zh>"]
DELETE = {"confirm": True}


def memory_client(make_client: ClientFactory, user: str | None = "producer") -> httpx.AsyncClient:
    """A client whose turns write down that the user has a cat."""
    return make_client(
        FakeLLM(REPLY, REPLY), user, retrieval_judge=FakeJudge(), embedder=FakeEmbedder(),
        reranker=FakeReranker("制作人"), background_llm=FakeBackgroundLLM(memorized(CAT)),
    )


async def use_everything(client: httpx.AsyncClient, character: str = "mano") -> None:
    """Leave data of every kind: a conversation, a memory, a profile and usage."""
    await client.put("/api/profile", json={"form_of_address": "小林"})
    await send_turn(client, await start_conversation(client, character), "我家的猫叫小白哦")
    assert len((await client.get("/api/memories")).json()) == 1


def rows_mentioning(database: Path, value: str) -> dict[str, int]:
    """How many rows of each table have a column equal to `value`."""
    found = {}
    with sqlite3.connect(database) as db:
        tables = [t for (t,) in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
        for table in tables:
            columns = [c[1] for c in db.execute(f"PRAGMA table_info({table})")]
            where = " OR ".join(f'"{c}" = ?' for c in columns)
            count = db.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {where}", [value] * len(columns)
            ).fetchone()[0]
            if count:
                found[table] = count
    return found


def user_id(database: Path, name: str) -> str:
    with sqlite3.connect(database) as db:
        [(found,)] = db.execute("SELECT id FROM users WHERE name = ?", (name,)).fetchall()
    return found


def files_holding(database: Path, text: str) -> list[Path]:
    """Which of the database file and its write-ahead log hold `text`."""
    return [
        path
        for path in (database, database.with_name(database.name + "-wal"))
        if path.exists() and text.encode() in path.read_bytes()
    ]


async def test_deleting_leaves_nothing_of_the_user_in_any_table(
    make_client: ClientFactory, settings: Settings
):
    client = memory_client(make_client)
    await use_everything(client)
    producer = user_id(settings.database_path, "producer")
    conversation_id = (await client.get(
        "/api/conversations", params={"character_id": "mano"}
    )).json()[0]["id"]
    assert rows_mentioning(settings.database_path, producer)

    res = await client.post("/api/account/delete", json=DELETE)

    assert res.status_code == 204
    assert rows_mentioning(settings.database_path, producer) == {}
    assert rows_mentioning(settings.database_path, conversation_id) == {}  # its messages too
    with sqlite3.connect(settings.database_path) as db:
        assert db.execute("SELECT COUNT(*) FROM messages").fetchone() == (0,)
        assert db.execute("SELECT COUNT(*) FROM memories WHERE text = ?", (CAT,)).fetchone() == (0,)


async def test_deleting_signs_the_user_out_everywhere(make_client: ClientFactory):
    clock = FakeClock()
    desktop = make_client(FakeLLM(), clock=clock)
    phone = make_client(FakeLLM(), clock=clock)
    clock.advance(hours=2)  # The delete request itself is due to renew the cookie.

    res = await desktop.post("/api/account/delete", json=DELETE)

    [cookie] = res.headers.get_list("set-cookie")
    assert 'eidolon_session=""' in cookie
    assert "eidolon_session" not in desktop.cookies
    for client in (desktop, phone):
        assert (await client.get("/api/account")).status_code == 401


async def test_signing_in_again_after_deleting_is_a_new_user(
    make_client: ClientFactory, github: FakeIdentityProvider
):
    client = memory_client(make_client, user=None)
    await sign_in_with(client, github, github_identity())
    await agree_to_terms(client)
    await use_everything(client)
    await client.post("/api/account/delete", json=DELETE)

    await sign_in_with(client, github, github_identity())

    assert (await client.get("/api/account")).status_code == 428  # agrees afresh
    await agree_to_terms(client)
    assert (await client.get("/api/conversations", params={"character_id": "mano"})).json() == []
    assert (await client.get("/api/memories")).json() == []
    assert (await client.get("/api/profile")).json()["form_of_address"] is None


async def test_other_users_keep_their_data(make_client: ClientFactory, settings: Settings):
    friend = memory_client(make_client, "friend")
    await use_everything(friend, character_id("mano", "friend"))
    before = rows_mentioning(settings.database_path, user_id(settings.database_path, "friend"))
    mine = memory_client(make_client)
    await use_everything(mine)

    await mine.post("/api/account/delete", json=DELETE)

    after = rows_mentioning(settings.database_path, user_id(settings.database_path, "friend"))
    assert after == before
    assert len((await friend.get("/api/memories")).json()) == 1


async def test_deleting_removes_the_users_characters_from_the_shared_mapping(
    make_client: ClientFactory,
):
    mine = make_client(FakeLLM())
    friend = make_client(FakeLLM(), "friend")
    backend = mine._transport.app.state.backend  # pyright: ignore[reportAttributeAccessIssue]
    # Each client has a backend of its own over the one database: refresh mine's shared
    # mapping from it, as the server does at startup, to see the friend's characters too.
    await backend.character_repository.load()
    assert {"mano", "kogane", "mano-friend", "kogane-friend"} <= set(backend.characters)

    assert (await mine.post("/api/account/delete", json=DELETE)).status_code == 204

    assert set(backend.characters) == {"mano-friend", "kogane-friend"}
    assert [c["id"] for c in (await friend.get("/api/characters")).json()] == [
        "mano-friend", "kogane-friend",
    ]


@pytest.mark.parametrize("body", [{}, {"confirm": False}], ids=["unconfirmed", "declined"])
async def test_deleting_needs_confirming(
    make_client: ClientFactory, settings: Settings, body: dict
):
    client = make_client(FakeLLM())

    res = await client.post("/api/account/delete", json=body)

    assert res.status_code == 422
    assert (await client.get("/api/account")).status_code == 200


async def test_a_user_who_has_not_agreed_to_the_terms_can_still_delete(
    make_client: ClientFactory, settings: Settings, github: FakeIdentityProvider
):
    client = make_client(FakeLLM(), user=None)
    await sign_in_with(client, github, github_identity())

    res = await client.post("/api/account/delete", json=DELETE)

    assert res.status_code == 204
    with sqlite3.connect(settings.database_path) as db:
        assert db.execute("SELECT COUNT(*) FROM users").fetchone() == (0,)
        assert db.execute("SELECT COUNT(*) FROM sign_in_methods").fetchone() == (0,)


async def test_deleting_hangs_up_the_users_call(
    make_client: ClientFactory, speech: FakeSpeech, browser: Browser
):
    client = make_client(FakeLLM(REPLY))
    await browser.call(client, conversation_id=await start_conversation(client))
    await browser.connect()

    await client.post("/api/account/delete", json=DELETE)

    await browser.hung_up()


async def test_deleting_waits_for_an_unanswered_offer_to_be_cancelled(
    make_client: ClientFactory, browser: Browser, monkeypatch: pytest.MonkeyPatch,
):
    phone = make_client(FakeLLM())
    desktop = httpx.AsyncClient(transport=phone._transport, base_url=phone.base_url, headers=phone.headers)
    conversation_id = await start_conversation(phone)
    calls = backend_of(phone).calls
    answer = calls._answer
    answering, finish = asyncio.Event(), asyncio.Event()

    async def held_answer(*args):
        answering.set()
        await finish.wait()
        return await answer(*args)

    monkeypatch.setattr(calls, "_answer", held_answer)
    async with desktop, asyncio.TaskGroup() as tasks:
        assert (await desktop.post("/api/auth/dev-login", json={"name": "producer"})).status_code == 204
        placing = tasks.create_task(browser.call(phone, conversation_id=conversation_id))
        try:
            await asyncio.wait_for(answering.wait(), 5)
            deleting = tasks.create_task(desktop.post("/api/account/delete", json=DELETE))
            early, _ = await asyncio.wait({deleting}, timeout=0.5)
        finally:
            finish.set()
    assert not early, "account deletion returned while the offer could still be answered"
    assert deleting.result().status_code == 204
    assert placing.result().status_code == 500
    assert (await phone.get("/api/account")).status_code == 401


@pytest.mark.parametrize("separate_api", [False, True], ids=["same-api", "separate-api"])
async def test_an_offer_already_authorized_is_refused_after_account_deletion(
    make_client: ClientFactory, browser: Browser, monkeypatch: pytest.MonkeyPatch, separate_api: bool,
):
    client = make_client(FakeLLM())
    deleting = make_client(FakeLLM()) if separate_api else client
    conversation_id = await start_conversation(client)
    store = backend_of(client).store
    ended = store.ended
    checking, finish = asyncio.Event(), asyncio.Event()

    async def held_ended(conversation_id: str):
        checking.set()
        await finish.wait()
        return await ended(conversation_id)

    monkeypatch.setattr(store, "ended", held_ended)
    async with asyncio.TaskGroup() as tasks:
        offer = tasks.create_task(browser.call(client, conversation_id=conversation_id))
        try:
            await asyncio.wait_for(checking.wait(), 5)
            assert (await deleting.post("/api/account/delete", json=DELETE)).status_code == 204
        finally:
            finish.set()
    assert offer.result().status_code == 404


async def test_deleted_data_is_gone_from_the_database_files_too(
    make_client: ClientFactory, settings: Settings
):
    client = memory_client(make_client)
    await use_everything(client)

    await client.post("/api/account/delete", json=DELETE)

    database = settings.database_path
    await emptied(database)  # soon after
    for path in (database, database.with_name(database.name + "-wal")):
        if path.exists():
            assert CAT.encode() not in path.read_bytes(), path


async def test_a_reader_meanwhile_holds_up_no_one_elses_turn_and_the_log_is_emptied_after_it(
    make_client: ClientFactory, settings: Settings, monkeypatch: pytest.MonkeyPatch
):
    """As when a backup is being copied: deleting waits for it no longer than a moment,
    and the pages as they were leave the write-ahead log once it is done."""
    monkeypatch.setattr(eidolon.data_access, "CHECKPOINT_RETRY", 0.1)
    client = make_client(FakeLLM(REPLY, REPLY))
    friend = another_user(client, "friend")
    friends = await start_conversation(friend, character_id("mano", "friend"))
    await send_turn(client, await start_conversation(client), "早上好")
    database = settings.database_path
    reader = reading(database)
    try:
        async with asyncio.timeout(5):
            assert (await client.post("/api/account/delete", json=DELETE)).status_code == 204
            await send_turn(friend, friends, "在吗")
        assert log_of(database)  # held up by the reader
    finally:
        reader.close()

    await emptied(database)
    assert len((await friend.get(f"/api/conversations/{friends}/messages")).json()) == 2


async def test_memories_cleared_before_deleting_are_gone_from_the_database_files_too(
    make_client: ClientFactory, settings: Settings
):
    client = memory_client(make_client)
    await use_everything(client)
    assert (await client.delete("/api/memories")).status_code == 204

    await client.post("/api/account/delete", json=DELETE)

    await emptied(settings.database_path)  # soon after
    assert files_holding(settings.database_path, CAT) == []


async def test_a_memory_deleted_before_deleting_is_gone_from_the_database_files_too(
    make_client: ClientFactory, settings: Settings
):
    client = memory_client(make_client)
    await use_everything(client)
    [cat] = (await client.get("/api/memories")).json()
    assert (await client.delete(f"/api/memories/{cat['id']}")).status_code == 204

    await client.post("/api/account/delete", json=DELETE)

    await emptied(settings.database_path)  # soon after
    assert files_holding(settings.database_path, CAT) == []
