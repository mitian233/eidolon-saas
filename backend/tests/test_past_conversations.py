"""Her conversations with the user, for the past conversations panel (GLOSSARY.md「当前对话」
「历史对话」): every one, newest first, the first her current one, each with the last thing
in it as the conversation list shows it (her ending it passed over; null while it has none)
and whether she has ended it. Driven through the backend's external API, her ending one and
hanging up put in the database as recorded elsewhere."""

import httpx

from eidolon.config import Settings
from tests.conftest import ClientFactory
from tests.fakes import FakeLLM
from tests.test_conversation_events import hang_up
from tests.test_she_ends_conversation import end
from tests.test_text_turn import send_turn, start_conversation


async def hers(client: httpx.AsyncClient, character: str = "mano") -> list[dict]:
    res = await client.get("/api/conversations", params={"character_id": character})
    assert res.status_code == 200
    return res.json()


async def test_each_of_her_conversations_comes_with_its_last_message_and_whether_she_ended_it(
    make_client: ClientFactory, settings: Settings
):
    client = make_client(FakeLLM(["<ja>また明日</ja><zh>明天见</zh>"]))
    said = await start_conversation(client)
    await send_turn(client, said, "晚安")
    ended = await start_conversation(client)
    at = hang_up(settings.database_path, ended)
    end(settings.database_path, ended)
    current = await start_conversation(client)
    await start_conversation(client, "kogane")

    listed = await hers(client)

    assert [c["id"] for c in listed] == [current, ended, said]
    assert [c["ended"] for c in listed] == [False, True, False]
    assert listed[0]["last_message"] is None
    last_event = listed[1]["last_message"]
    assert (last_event["type"], last_event["kind"], last_event["created_at"]) == (
        "event", "hung_up", at,
    )
    last = listed[2]["last_message"]
    assert (last["role"], last["text"], last["ja"], last["zh"]) == (
        "character", None, "また明日", "明天见"
    )
    assert last["created_at"]