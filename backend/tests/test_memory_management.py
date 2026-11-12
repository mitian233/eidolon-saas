"""Memory management, driven through the memories API: users see every memory the
characters keep about them, labelled with the character it was told to, and can delete
one or all of them; nobody sees or touches another user's memories. What deleting and
clearing do to later turns is tested on the memories module (test_memories)."""

import httpx

from tests.conftest import ClientFactory
from tests.fakes import FakeBackgroundLLM, FakeEmbedder, FakeJudge, FakeLLM, FakeReranker
from tests.test_shared_memory import (
    CAT,
    REPLY,
    TRIP,
    memorized,
    turn,
)
from tests.test_memories import OSAKA, TOKYO, superseding
from tests.test_text_turn import start_conversation
from tests.conftest import character_id


def memory_client(
    make_client: ClientFactory, llm: FakeLLM, *memories: str, **options: object
) -> httpx.AsyncClient:
    """A client whose background model writes down each of `memories` in turn, one per
    turn, and whose reranker finds every memory relevant."""
    return make_client(
        llm, retrieval_judge=FakeJudge(), embedder=FakeEmbedder(), reranker=FakeReranker("制作人"),
        background_llm=FakeBackgroundLLM(*(memorized(m) for m in memories)), **options,
    )


async def memories(client: httpx.AsyncClient) -> list[dict]:
    res = await client.get("/api/memories")
    assert res.status_code == 200, res.text
    return res.json()


async def test_lists_every_memory_with_the_character_it_was_told_to(
    make_client: ClientFactory,
):
    client = memory_client(make_client, FakeLLM(REPLY, REPLY), CAT, TRIP)

    await turn(client, await start_conversation(client, "mano"), "我家的猫叫小白哦")
    await turn(client, await start_conversation(client, "kogane"), "下周六我要去北海道出差")

    listed = await memories(client)  # right away: what was just said is already there
    assert [(m["text"], m["source_character_id"], m["source_character_name"])
            for m in listed] == [
        (TRIP, "kogane", "月岡恋鐘"),  # newest first
        (CAT, "mano", "櫻木真乃"),
    ]
    assert all(set(m) == {"id", "text", "source_character_id", "source_character_name",
                          "created_at", "superseded"} for m in listed)


async def test_deleting_a_memory_that_is_gone_is_not_found(make_client: ClientFactory):
    client = memory_client(make_client, FakeLLM(REPLY), CAT)
    await turn(client, await start_conversation(client, "mano"), "我家的猫叫小白哦")
    [cat] = await memories(client)

    assert (await client.delete(f"/api/memories/{cat['id']}")).status_code == 204
    res = await client.delete(f"/api/memories/{cat['id']}")

    assert res.status_code == 404
    assert res.json()["detail"] == "记忆不存在"


async def test_users_see_and_touch_only_their_own_memories(
    make_client: ClientFactory,
):
    producer = memory_client(make_client, FakeLLM(REPLY), CAT)
    friend = memory_client(make_client, FakeLLM(REPLY), "制作人喜欢狗", user="friend")
    await turn(producer, await start_conversation(producer, "mano"), "我家的猫叫小白")
    await turn(friend, await start_conversation(friend, character_id("mano", "friend")), "我喜欢狗")
    [cat] = await memories(producer)

    assert [m["text"] for m in await memories(friend)] == ["制作人喜欢狗"]
    res = await friend.delete(f"/api/memories/{cat['id']}")
    assert res.status_code == 404
    assert (await friend.delete("/api/memories")).status_code == 204

    assert [m["text"] for m in await memories(producer)] == [CAT]


async def test_the_memories_api_needs_a_session(make_client: ClientFactory):
    client = make_client(FakeLLM(), user=None)

    for method, path in [("GET", "/api/memories"), ("DELETE", "/api/memories"),
                         ("DELETE", "/api/memories/1")]:
        res = await client.request(method, path)
        assert res.status_code == 401, (method, path)


async def test_without_memory_there_is_nothing_to_list(make_client: ClientFactory):
    """Memory is off without retrieval; the page still works, empty."""
    client = make_client(FakeLLM(REPLY))
    await turn(client, await start_conversation(client, "mano"), "我家的猫叫小白哦")

    assert await memories(client) == []
    assert (await client.delete("/api/memories")).status_code == 204


async def test_superseded_memories_are_listed_as_such_until_what_superseded_them_goes(
    make_client: ClientFactory,
):
    client = make_client(
        FakeLLM(REPLY, REPLY), retrieval_judge=FakeJudge(), embedder=FakeEmbedder(),
        reranker=FakeReranker("制作人"),
        background_llm=FakeBackgroundLLM(memorized(OSAKA), superseding(TOKYO, OSAKA)),
    )
    await turn(client, await start_conversation(client, "mano"), "我住在大阪")
    await turn(client, await start_conversation(client, "kogane"), "我搬到东京了")

    listed = await memories(client)
    assert [(m["text"], m["superseded"]) for m in listed] == [(TOKYO, False), (OSAKA, True)]

    assert (await client.delete(f"/api/memories/{listed[0]['id']}")).status_code == 204
    assert [(m["text"], m["superseded"]) for m in await memories(client)] == [(OSAKA, False)]
