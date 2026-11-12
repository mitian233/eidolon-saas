"""The database: every connection to it is opened the same way, and every table in it
is either a user's data, deleted with the user, or not."""

import asyncio
import sqlite3
from pathlib import Path
import threading

import pytest

from eidolon import database
from eidolon.config import Settings
from eidolon.data_access import Database
from eidolon.store import Store
from tests.conftest import ClientFactory
from tests.fakes import FakeEmbedder, FakeJudge, FakeLLM, FakeReranker

SOURCE = Path(database.__file__).parent


def test_a_connection_keeps_a_log_overwrites_what_is_deleted_and_checks_references(
    tmp_path: Path,
):
    db = database.connect(tmp_path / "eidolon.db")

    assert db.execute("PRAGMA journal_mode").fetchone() == ("wal",)
    assert db.execute("PRAGMA synchronous").fetchone() == (1,)  # NORMAL: no fsync a commit
    assert db.execute("PRAGMA secure_delete").fetchone() == (1,)
    assert db.execute("PRAGMA foreign_keys").fetchone() == (1,)
    assert db.execute("PRAGMA busy_timeout").fetchone() == (30000,)
    db.close()


def test_connecting_makes_the_directory_the_database_is_in(tmp_path: Path):
    path = tmp_path / "data" / "eidolon.db"

    database.connect(path).close()

    assert path.exists()


async def test_every_table_is_either_a_users_data_or_not(
    make_client: ClientFactory, settings: Settings
):
    make_client(FakeLLM(), retrieval_judge=FakeJudge(), embedder=FakeEmbedder(), reranker=FakeReranker())

    with sqlite3.connect(settings.database_path) as db:
        tables = {
            name
            for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            if not name.startswith("sqlite_")
        }
    users = {table for table, _ in database.USER_DATA}
    users |= {table for table, *_ in database.ANONYMIZED_USER_DATA}
    assert not users & database.NOT_USER_DATA
    assert tables <= users | database.NOT_USER_DATA


def test_only_the_database_module_connects_to_the_database():
    connecting = [
        path.relative_to(SOURCE).as_posix()
        for path in SOURCE.rglob("*.py")
        if "sqlite3.connect(" in path.read_text(encoding="utf-8")
    ]

    assert connecting == ["database.py"]


async def test_two_concurrent_connections_see_each_others_commits(database_target: Path | str):
    first, second = Database(database_target), Database(database_target)
    try:
        left, right = Store(first), Store(second)
        alice, bob = await asyncio.gather(left.create_user("Alice"), right.create_user("Bob"))

        assert (await left.get_user(bob.id)).name == "Bob"
        assert (await right.get_user(alice.id)).name == "Alice"
        a, b = await asyncio.gather(
            left.create_conversation(alice.id, "alice-character"),
            right.create_conversation(bob.id, "bob-character"),
        )
        def say(conn, conversation, text):
            conn.execute("INSERT INTO messages (conversation_id, role, text, created_at)"
                         " VALUES (?, 'user', ?, '2026-11-12')", (conversation, text))

        await asyncio.gather(first.write(say, a.id, "Alice only"),
                             second.write(say, b.id, "Bob only"))
        assert [m.text for m in await right.list_messages(a.id)] == ["Alice only"]
        assert [m.text for m in await left.list_messages(b.id)] == ["Bob only"]
    finally:
        await asyncio.gather(first.close(), second.close())


async def test_write_failure_rolls_back_without_poisoning_next_write(database_target: Path | str):
    db = Database(database_target)
    try:
        store = Store(db)
        user = await store.create_user("Before")

        def fails(conn):
            conn.execute("UPDATE users SET name = ? WHERE id = ?", ("Discarded", user.id))
            raise ValueError("discard this write")

        with pytest.raises(ValueError, match="discard this write"):
            await db.write(fails)
        assert (await store.get_user(user.id)).name == "Before"
        assert (await store.create_user("After")).name == "After"
    finally:
        await db.close()


async def test_read_keeps_one_view_and_rejects_writes(database_target: Path | str):
    first, second = Database(database_target), Database(database_target)
    reading, finish = threading.Event(), threading.Event()
    try:
        left, right = Store(first), Store(second)
        user = await left.create_user("Before")

        def twice(conn):
            query = "SELECT name FROM users WHERE id = ?"
            before = conn.execute(query, (user.id,)).fetchone()[0]
            reading.set()
            assert finish.wait(10)
            return before, conn.execute(query, (user.id,)).fetchone()[0]

        task = asyncio.create_task(first.read(twice))
        await asyncio.to_thread(reading.wait, 10)
        await second.write(lambda conn: conn.execute("UPDATE users SET name = 'After'"))
        finish.set()
        assert await task == ("Before", "Before")
        assert (await left.get_user(user.id)).name == "After"
        with pytest.raises(sqlite3.OperationalError):
            await first.read(lambda conn: conn.execute("DELETE FROM users"))
        assert (await right.get_user(user.id)).name == "After"
    finally:
        finish.set()
        await asyncio.gather(first.close(), second.close())


async def test_database_url_routes_existing_path_callers_to_postgres(
    postgres_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("DATABASE_URL", postgres_url)
    path = tmp_path / "unused.db"
    db = Database(path)
    try:
        user = await Store(db).create_user("Remote")
        assert (await Store(db).get_user(user.id)).name == "Remote"
        assert database.readable(path)
        assert not path.exists()
    finally:
        await db.close()


async def test_two_api_instances_keep_their_users_turns_separate(
    database_target: Path | str, monkeypatch: pytest.MonkeyPatch, make_client: ClientFactory,
    settings: Settings,
):
    from tests.test_text_turn import send_turn, start_conversation

    if isinstance(database_target, str):
        monkeypatch.setenv("DATABASE_URL", database_target)
    alice = make_client(FakeLLM("<ja>Alice reply</ja><zh>A</zh>"), "alice")
    bob = make_client(FakeLLM("<ja>Bob reply</ja><zh>B</zh>"), "bob")
    a = await start_conversation(alice, "mano-alice")
    b = await start_conversation(bob, "mano-bob")
    a_events, b_events = await asyncio.gather(
        send_turn(alice, a, "Alice only"), send_turn(bob, b, "Bob only")
    )
    assert a_events[-1]["type"] == b_events[-1]["type"] == "done"
    assert a_events[-1]["message"]["ja"] == "Alice reply"
    assert b_events[-1]["message"]["ja"] == "Bob reply"
    a_messages = (await alice.get(f"/api/conversations/{a}/messages")).json()
    b_messages = (await bob.get(f"/api/conversations/{b}/messages")).json()
    assert [m["text"] for m in a_messages if m["role"] == "user"] == ["Alice only"]
    assert [m["text"] for m in b_messages if m["role"] == "user"] == ["Bob only"]
    assert (await alice.get(f"/api/conversations/{b}/messages")).status_code == 404
    assert (await bob.get(f"/api/conversations/{a}/messages")).status_code == 404


def test_storage_queries_keep_ids_values_and_conflicts(database_target: Path | str):
    conn = database.connect(database_target)
    try:
        conn.executescript("""
            CREATE TABLE things (id INTEGER PRIMARY KEY AUTOINCREMENT,
                                 name TEXT UNIQUE NOT NULL, payload BLOB);
            CREATE TABLE counters (scope TEXT, name TEXT, count INTEGER NOT NULL,
                                   PRIMARY KEY (scope, name)) WITHOUT ROWID;
        """)
        with conn:
            first = conn.execute("INSERT INTO things (name, payload) VALUES (?, ?)",
                                 ("100% ? :quoted", b"\x00\xff"))
            assert first.lastrowid == 1
            assert first.rowcount == 1
            ignored = conn.execute("INSERT OR IGNORE INTO things (name) VALUES (?)", ("100% ? :quoted",))
            assert ignored.rowcount == 0
            conn.execute("INSERT OR REPLACE INTO counters VALUES (?, ?, ?)", ("a", "b", 2))
            conn.execute("INSERT OR REPLACE INTO counters VALUES (?, ?, ?)", ("a", "b", 7))
            conn.execute("INSERT INTO counters VALUES ('a', 'b', 3)"
                         " ON CONFLICT DO UPDATE SET count = count + excluded.count")
        assert conn.execute("SELECT * FROM counters").fetchall() == [("a", "b", 10)]
        rows = conn.execute("SELECT name, payload FROM things WHERE name LIKE '%' || ? || '%'", ("?",)).fetchall()
        assert rows == [("100% ? :quoted", b"\x00\xff")]
        named = database.by_name(conn).execute("SELECT name, payload FROM things WHERE id = :id", {"id": 1}).fetchone()
        assert dict(named) == {"name": "100% ? :quoted", "payload": b"\x00\xff"}
        info = database.by_name(conn).execute("PRAGMA table_info(counters)").fetchall()
        assert [(row["name"], row["pk"]) for row in info] == [("scope", 1), ("name", 2), ("count", 0)]
        with conn:
            try:
                conn.execute("INSERT INTO things (name) VALUES (?)", ("100% ? :quoted",))
            except sqlite3.IntegrityError:
                conn.execute("INSERT INTO things (name) VALUES (:name)", {"name": "after error"})
        assert conn.execute("SELECT COUNT(*) FROM things").fetchone() == (2,)
    finally:
        conn.close()


async def test_activity_records_and_rollups_match_sqlite(
    database_target: Path | str, tmp_path: Path
):
    import random
    from datetime import timedelta
    from typing import cast

    from eidolon.activity import ActivityLog
    from tests.fakes import START, FakeClock
    from tests.test_activity_rollups import USERS, _fill

    reference_path = tmp_path / "reference.db"
    databases = [Database(database_target), Database(reference_path)]
    logs = []
    try:
        for db in databases:
            Store(db)
            await db.write(lambda conn: conn.executemany(
                "INSERT INTO users (id, name, created_at) VALUES (?, ?, '2026-11-12')",
                # Both engines get the same successful inserts: Postgres sequences
                # deliberately consume ids even when an INSERT fails.
                [(user, user) for user in [*USERS, "gone"]],
            ))
        for db, path in zip(databases, [database_target, reference_path]):
            clock = FakeClock(START - timedelta(days=1))
            log = ActivityLog(db, clock)
            logs.append(log)
            await _fill(log, cast(Path, path), clock, random.Random(11))
        starts = [START - timedelta(days=1), START - timedelta(hours=12), START]
        actual, expected = [await log.tally(START - timedelta(days=1), starts) for log in logs]
        assert sorted(actual.records, key=repr) == sorted(expected.records, key=repr)
        assert sorted(actual.calls, key=repr) == sorted(expected.calls, key=repr)
        assert actual.users == expected.users
        assert actual.stretches == expected.stretches
        assert actual.lasted_within == expected.lasted_within
        assert actual.latency == expected.latency
        assert actual.first_token == expected.first_token
        assert await logs[0].billed_models(starts[0]) == await logs[1].billed_models(starts[0])
        assert await logs[0].deployer_calls_since(starts[0]) == await logs[1].deployer_calls_since(starts[0])
    finally:
        await asyncio.gather(*(log.aclose() for log in logs))
        await asyncio.gather(*(db.close() for db in databases))


async def test_updating_users_preserves_their_insertion_order(database_target: Path | str):
    db = Database(database_target)
    try:
        store = Store(db)
        await db.write(lambda conn: conn.executemany(
            "INSERT INTO users (id, name, created_at) VALUES (?, ?, '2026-11-12')",
            [("z", "first"), ("a", "second")],
        ))
        await db.write(lambda conn: conn.execute("UPDATE users SET name = 'updated' WHERE id = 'z'"))
        assert [user.name for user in await store.list_users()] == ["updated", "second"]
    finally:
        await db.close()
