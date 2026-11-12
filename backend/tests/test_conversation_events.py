"""Conversation events (GLOSSARY.md「对话事件」): what happened in a conversation that is not
a turn, here her hanging up on the user (gift records are tested with giving). Reading the
conversation gives them among its messages, in the order things happened, an event written
while her reply is still coming after that turn; the conversation list's last message may
be one. She learns of one from a line before the user's next words in her prompt, which
slides out of it with them; memory and the judge model never see it (tested with her
responding to gifts). Deleting the user deletes them; deleting memories does not.

Driven through the backend's external API; the events are put in the database as the
call that hangs up would write them."""

import sqlite3
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import httpx

from eidolon.config import Settings
from eidolon.llm import ChatMessage, Streamed, Tool
from tests.conftest import ClientFactory
from tests.fakes import FakeLLM
from tests.test_conversation_history import history, told
from tests.test_delete_account import DELETE
from tests.test_text_turn import send_turn, start_conversation

REPLY = ["<ja>はい</ja><zh>好的</zh>"]


def hang_up(database: Path, conversation: str, now: datetime | None = None) -> str:
    """Have her hang up on the user in the conversation, `now` (by default the time it is);
    when it was."""
    at = (now or datetime.now(UTC)).isoformat()
    with sqlite3.connect(database) as db:
        db.execute(
            "INSERT INTO conversation_events (conversation_id, kind, created_at)"
            " VALUES (?, 'hung_up', ?)",
            (conversation, at),
        )
    return at


async def record(client: httpx.AsyncClient, conversation: str) -> list[dict]:
    res = await client.get(f"/api/conversations/{conversation}/messages")
    assert res.status_code == 200
    return res.json()


def shape(record: list[dict]) -> list[str]:
    return [e["kind"] if e.get("type") == "event" else f"{e['role']}:{e['text'] or e['zh']}"
            for e in record]


async def test_the_record_gives_events_among_the_messages_in_the_order_they_happened(
    make_client: ClientFactory, settings: Settings
):
    client = make_client(FakeLLM(REPLY, REPLY))
    conversation = await start_conversation(client)
    await send_turn(client, conversation, "第一句")
    at = hang_up(settings.database_path, conversation)
    await send_turn(client, conversation, "第二句")

    entries = await record(client, conversation)

    assert shape(entries) == ["user:第一句", "character:好的", "hung_up", "user:第二句", "character:好的"]
    assert entries[2] == {"type": "event", "id": entries[2]["id"], "kind": "hung_up",
                          "created_at": at, "affinity": None}


class WritesWhileReplying(FakeLLM):
    """Does `meanwhile` once the reply has begun, before the rest of it comes."""

    def __init__(self, meanwhile: Callable[[], object], *replies: Sequence[str]) -> None:
        super().__init__(*replies)
        self._meanwhile = meanwhile

    async def stream_with(
        self,
        key: str,
        messages: Sequence[ChatMessage],
        tools: Sequence[Tool] = (),
        *,
        forbid_calls: bool = False,
    ) -> AsyncIterator[Streamed]:
        async for chunk in super().stream_with(key, messages, tools, forbid_calls=forbid_calls):
            yield chunk
            self._meanwhile()


async def test_an_event_written_while_she_replies_comes_after_that_turn(
    make_client: ClientFactory, settings: Settings
):
    conversation = ""
    llm = WritesWhileReplying(
        lambda: hang_up(settings.database_path, conversation),
        ["<ja>は", "い</ja><zh>好的</zh>"],
    )
    client = make_client(llm)
    conversation = await start_conversation(client)

    await send_turn(client, conversation, "在吗")

    kinds = shape(await record(client, conversation))
    assert kinds[:2] == ["user:在吗", "character:好的"]
    assert set(kinds[2:]) == {"hung_up"}


async def test_she_learns_of_it_before_the_users_next_words_which_are_kept_as_said(
    make_client: ClientFactory, settings: Settings
):
    llm = FakeLLM(REPLY, REPLY, REPLY)
    client = make_client(llm)  # affinity off, as it is by default: she learns of it all the same
    conversation = await start_conversation(client)
    await send_turn(client, conversation, "第一句")
    hang_up(settings.database_path, conversation)

    await send_turn(client, conversation, "刚才怎么了")
    # Not after the user's words now, so before the latest of them.
    role, text = history(llm)[-1]
    assert role == "user"
    event_line, said = text.split("\n", 1)
    assert said == "刚才怎么了"
    assert event_line  # told of the event before the words

    await send_turn(client, conversation, "第三句")
    assert history(llm)[-3:] == [
        ("user", f"{event_line}\n刚才怎么了"), ("assistant", "<ja>はい</ja><zh>好的</zh>"),
        ("user", "第三句"),
    ]
    assert [e["text"] for e in await record(client, conversation) if e.get("role") == "user"] == [
        "第一句", "刚才怎么了", "第三句",
    ]


async def test_it_slides_out_of_her_prompt_with_the_users_words_after_it(
    make_client: ClientFactory, settings: Settings
):
    llm = FakeLLM(REPLY, REPLY, REPLY, REPLY)
    client = make_client(llm, settings=replace(settings, history_turns=1))
    conversation = await start_conversation(client)
    await send_turn(client, conversation, "第一句")
    hang_up(settings.database_path, conversation)
    await send_turn(client, conversation, "第二句")
    await send_turn(client, conversation, "第三句")
    role, text = history(llm)[0]
    assert role == "user"
    event_line, said = text.split("\n", 1)
    assert said == "第二句"
    assert event_line

    await send_turn(client, conversation, "第四句")

    assert event_line not in told(llm)


async def test_the_conversation_lists_last_message_can_be_an_event_until_the_next_turn(
    make_client: ClientFactory, settings: Settings
):
    client = make_client(FakeLLM(REPLY, REPLY))
    conversation = await start_conversation(client)
    await send_turn(client, conversation, "第一句")

    at = hang_up(settings.database_path, conversation)

    [latest] = (await client.get("/api/conversations/latest")).json()
    last = latest["last_message"]
    assert (last["type"], last["kind"], last["created_at"]) == ("event", "hung_up", at)

    await send_turn(client, conversation, "第二句")

    [latest] = (await client.get("/api/conversations/latest")).json()
    assert (latest["last_message"]["role"], latest["last_message"]["zh"]) == ("character", "好的")


def events(database: Path) -> int:
    with sqlite3.connect(database) as db:
        return db.execute("SELECT COUNT(*) FROM conversation_events").fetchone()[0]


async def test_deleting_memories_keeps_them_and_deleting_the_user_deletes_them(
    make_client: ClientFactory, settings: Settings
):
    client = make_client(FakeLLM(REPLY))
    conversation = await start_conversation(client)
    await send_turn(client, conversation, "第一句")
    hang_up(settings.database_path, conversation)

    assert (await client.delete("/api/memories")).status_code == 204
    assert events(settings.database_path) == 1

    assert (await client.post("/api/account/delete", json=DELETE)).status_code == 204
    assert events(settings.database_path) == 0


async def test_a_database_that_kept_whether_she_responded_drops_it_and_keeps_its_events(
    make_client: ClientFactory, settings: Settings
):
    client = make_client(FakeLLM(REPLY))
    conversation = await start_conversation(client)
    with sqlite3.connect(settings.database_path) as db:  # as the table was before gifts
        db.execute(
            "ALTER TABLE conversation_events ADD COLUMN responded INTEGER NOT NULL DEFAULT 0"
        )
    hang_up(settings.database_path, conversation)

    reopened = make_client(FakeLLM())

    assert shape(await record(reopened, conversation)) == ["hung_up"]
    with sqlite3.connect(settings.database_path) as db:
        columns = {row[1] for row in db.execute("PRAGMA table_info(conversation_events)")}
    assert "responded" not in columns
