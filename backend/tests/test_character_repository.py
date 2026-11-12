"""Characters kept in the database: a user's own characters, persisted across a restart,
private to their owner, and shown to the browser as plain text without any asset files."""

import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from eidolon.character_repository import CharacterRepository, shown_character
from eidolon.characters import Character
from eidolon.data_access import Database
from eidolon.producer import Birthday
from eidolon.store import Store


@asynccontextmanager
async def database_in(path: Path):
    db = Database(path)
    try:
        yield db
    finally:
        await db.close()


@asynccontextmanager
async def repository_in(path: Path):
    """A store and a character repository on one database, as the backend has them, with the
    shared mapping the engine reads."""
    async with database_in(path) as db:
        store = Store(db)
        characters: dict[str, Character] = {}
        yield db, store, CharacterRepository(db, characters), characters


def _insert_message(conn, conversation_id: str) -> None:
    conn.execute(
        "INSERT INTO messages (conversation_id, role, text, created_at) VALUES (?, ?, ?, ?)",
        (conversation_id, "user", "你好", "2026-11-12T00:00:00+00:00"),
    )


def _count_messages(conn, conversation_id: str) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM messages WHERE conversation_id = ?", (conversation_id,)
    ).fetchone()[0]


async def test_a_plain_text_character_is_created_without_assets_or_birthday(tmp_path: Path):
    async with repository_in(tmp_path / "eidolon.db") as (db, store, repo, characters):
        alice = (await store.create_user("alice")).id

        c = await repo.create(alice, name="小测试", sheet="你是一个温和的助手。")

        assert c.id
        assert c.owner_id == alice
        assert c.language_mode == "single"
        assert c.user_address == "你"
        assert c.birthday is None
        assert c.age is None
        assert c.greeting is None
        assert c.avatar_url is None
        assert c.avatar is None
        assert characters[c.id] is c
        assert shown_character(c) == {
            "id": c.id,
            "name": "小测试",
            "intro": "",
            "sheet": "你是一个温和的助手。",
            "avatar_url": None,
            "greeting": "",
            "voice_id": "",
            "color": "#64748b",
            "user_address": "你",
            "language_mode": "single",
            "birthday": None,
            "age": None,
        }


async def test_create_needs_an_existing_owner(tmp_path: Path):
    async with repository_in(tmp_path / "eidolon.db") as (db, store, repo, characters):
        with pytest.raises(sqlite3.IntegrityError):
            await repo.create("no-such-user", name="A", sheet="s")
        assert characters == {}


async def test_every_setting_survives_a_reopen(tmp_path: Path):
    path = tmp_path / "eidolon.db"
    async with repository_in(path) as (db, store, repo, characters):
        alice = (await store.create_user("alice")).id
        c = await repo.create(
            alice,
            name="灯织",
            sheet="人设",
            intro="简介",
            avatar_url="https://example.com/a.png",
            greeting="你好呀。",
            voice_id="fish-1",
            color="#aabbcc",
            user_address="老师",
            language_mode="bilingual",
            birthday=Birthday(4, 25),
            age=16,
        )

    async with repository_in(path) as (db, store, repo, characters):
        await repo.load()

        loaded = characters[c.id]
        assert loaded == c
        assert loaded.birthday == Birthday(4, 25)
        assert loaded.age == 16
        assert loaded.greeting is not None
        assert loaded.greeting.ja == "你好呀。"
        assert loaded.language_mode == "bilingual"
        shown = shown_character(loaded)
        assert shown["greeting"] == "你好呀。"
        assert shown["birthday"] == "04-25"
        assert shown["age"] == 16
        assert shown["avatar_url"] == "https://example.com/a.png"


async def test_load_refreshes_the_shared_mapping_in_place(tmp_path: Path):
    async with repository_in(tmp_path / "eidolon.db") as (db, store, repo, characters):
        alice = (await store.create_user("alice")).id
        c1 = await repo.create(alice, name="一", sheet="s")
        c2 = await repo.create(alice, name="二", sheet="s")
        held = characters

        await repo.load()
        assert characters is held
        assert set(characters) == {c1.id, c2.id}

        # A row removed elsewhere is gone from the mapping after the next load.
        await db.write(lambda conn: conn.execute("DELETE FROM characters WHERE id = ?", (c2.id,)))
        await repo.load()
        assert set(characters) == {c1.id}


async def test_get_keeps_the_character_in_the_shared_mapping(tmp_path: Path):
    async with repository_in(tmp_path / "eidolon.db") as (db, store, repo, characters):
        alice = (await store.create_user("alice")).id
        c = await repo.create(alice, name="A", sheet="s")
        characters.clear()  # as before a startup load

        found = await repo.get(alice, c.id)

        assert found == c
        assert characters[c.id] == c


async def test_get_and_list_only_see_the_owners_characters(tmp_path: Path):
    async with repository_in(tmp_path / "eidolon.db") as (db, store, repo, characters):
        alice = (await store.create_user("alice")).id
        bob = (await store.create_user("bob")).id
        a = await repo.create(alice, name="A", sheet="s")
        b = await repo.create(bob, name="B", sheet="s")

        assert [c.id for c in await repo.list(alice)] == [a.id]
        assert [c.id for c in await repo.list(bob)] == [b.id]
        found = await repo.get(alice, a.id)
        assert found is not None
        assert found.id == a.id
        assert await repo.get(alice, b.id) is None
        assert await repo.get(bob, a.id) is None
        assert await repo.list("nobody") == []


async def test_update_changes_the_owners_character_and_persists(tmp_path: Path):
    path = tmp_path / "eidolon.db"
    async with repository_in(path) as (db, store, repo, characters):
        alice = (await store.create_user("alice")).id
        bob = (await store.create_user("bob")).id
        c = await repo.create(alice, name="旧", sheet="旧人设")

        updated = await repo.update(
            alice,
            c.id,
            name="新",
            sheet="新人设",
            intro="i",
            greeting="嗨。",
            language_mode="bilingual",
            birthday=Birthday(2, 29),
            age=17,
            user_address="前辈",
            avatar_url="https://x/y.png",
            voice_id="v",
            color="#000000",
        )

        assert updated is not None
        assert updated.name == "新"
        assert updated.birthday == Birthday(2, 29)
        assert updated.age == 17
        assert updated.user_address == "前辈"
        assert characters[c.id] is updated
        assert await repo.update(bob, c.id, name="劫持") is None
        found = await repo.get(alice, c.id)
        assert found is not None
        assert found.name == "新"

    async with repository_in(path) as (db, store, repo, characters):
        again = await repo.get(alice, c.id)
        assert again is not None
        assert again.name == "新"
        assert again.greeting is not None
        assert again.greeting.ja == "嗨。"
        assert again.birthday == Birthday(2, 29)


async def test_update_rejects_an_unknown_setting(tmp_path: Path):
    async with repository_in(tmp_path / "eidolon.db") as (db, store, repo, characters):
        alice = (await store.create_user("alice")).id
        c = await repo.create(alice, name="A", sheet="s")

        with pytest.raises(ValueError):
            await repo.update(alice, c.id, idol_id=5)

        found = await repo.get(alice, c.id)
        assert found is not None
        assert found.name == "A"


async def test_create_rejects_invalid_settings(tmp_path: Path):
    async with repository_in(tmp_path / "eidolon.db") as (db, store, repo, characters):
        alice = (await store.create_user("alice")).id

        with pytest.raises(ValueError):
            await repo.create(alice, name="A", sheet="s", language_mode="tri")
        with pytest.raises(ValueError):
            await repo.create(alice, name="A", sheet="s", birthday=Birthday(13, 1))
        with pytest.raises(ValueError):
            await repo.create(alice, name="A", sheet="s", age=0)
        with pytest.raises(ValueError):
            await repo.create(alice, name="A", sheet="s", age=True)

        assert await repo.list(alice) == []


async def test_delete_removes_the_character_and_its_owners_conversations(tmp_path: Path):
    async with repository_in(tmp_path / "eidolon.db") as (db, store, repo, characters):
        alice = (await store.create_user("alice")).id
        bob = (await store.create_user("bob")).id
        a = await repo.create(alice, name="A", sheet="s")
        a2 = await repo.create(alice, name="A2", sheet="s")
        b = await repo.create(bob, name="B", sheet="s")
        conv_a = await store.create_conversation(alice, a.id)
        conv_a2 = await store.create_conversation(alice, a2.id)
        conv_b = await store.create_conversation(bob, b.id)
        await db.write(_insert_message, conv_a.id)

        assert await repo.delete(bob, a.id) is False
        assert await repo.get(alice, a.id) is not None

        assert await repo.delete(alice, a.id) is True
        assert a.id not in characters
        assert await repo.get(alice, a.id) is None
        assert await store.get_conversation(conv_a.id) is None
        assert await db.read(_count_messages, conv_a.id) == 0

        # The owner's other character and conversation, and the other user's, are untouched.
        assert await store.get_conversation(conv_a2.id) is not None
        assert await repo.get(alice, a2.id) is not None
        assert await store.get_conversation(conv_b.id) is not None
        assert await repo.get(bob, b.id) is not None
        assert await repo.delete(alice, a.id) is False


async def test_delete_works_before_the_store_is_opened(tmp_path: Path):
    async with database_in(tmp_path / "eidolon.db") as db:
        # Only the users table exists (the store has not been opened): no conversations yet.
        db.prepare(
            lambda conn: conn.executescript(
                "CREATE TABLE users (id TEXT PRIMARY KEY, name TEXT NOT NULL,"
                " created_at TEXT NOT NULL);"
                "INSERT INTO users (id, name, created_at)"
                " VALUES ('alice', 'alice', '2026-11-12T00:00:00+00:00');"
            )
        )
        characters: dict[str, Character] = {}
        repo = CharacterRepository(db, characters)
        c = await repo.create("alice", name="A", sheet="s")

        assert await repo.delete("alice", c.id) is True
        assert characters == {}