"""Voice calls end to end: a browser calls in over a real WebRTC connection, speaks and
types, and the character answers through the fully assembled backend. Only the outside
services are fakes: Soniox and Fish Audio (FakeSpeech), the chat and background models,
Jev, the embedder and the reranker."""

import asyncio
import json
from contextlib import suppress
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection

import eidolon.call
from eidolon.app import create_app
from eidolon.call import CallOptions, SessionDescription
from eidolon.config import Settings, UsageLimits
from eidolon.own_keys import DeployerLease
from tests.browser import TIMEOUT, Browser, open_browser, until_gone
from tests.conftest import SITE, Characters, ClientFactory, aside, seed_characters, sign_in, store_in
from tests.fakes import (
    FakeBackgroundLLM,
    FakeEmbedder,
    FakeJudge,
    FakeLLM,
    FakeReranker,
    FakeSpeech,
    build_faked,
    context_of,
    system_of,
)
from tests.test_service_status import backend_of
from tests.test_text_turn import start_conversation

MANO_REPLY = ["<ja>ほわっ、", "おはようございます！</ja><zh>哇，早上好！</zh><ja>今日も</ja><zh>今天也</zh>"]
REPLY = ["<ja>はいっ</ja><zh>好的</zh>"]
CAT = "制作人家里养了一只叫小白的猫"


@pytest.fixture
def one_call_an_hour(settings: Settings) -> Settings:
    return replace(settings, usage_limits=UsageLimits(calls_per_hour=1))


async def test_a_call_is_heard_and_voiced_and_lands_in_the_conversation(
    make_client: ClientFactory, speech: FakeSpeech, browser: Browser
):
    llm = FakeLLM(MANO_REPLY, ["<ja>ピーちゃん！</ja><zh>小皮！</zh>"])
    client = make_client(llm, clock=lambda: datetime(2026, 9, 25, 12, 30, tzinfo=UTC))
    client.headers["X-Timezone"] = "Asia/Tokyo"
    conversation_id = await start_conversation(client, "mano")
    assert (await browser.call(client, conversation_id=conversation_id)).status_code == 200
    await browser.connect()

    await speech.stts[-1].hear("早上好")
    spoken = await browser.turn()
    browser.type("鸽子叫什么？")
    typed = await browser.turn()

    assert spoken[0] == {"type": "user", "text": "早上好", "reply": 1}
    assert [(m["segment"], m["lang"], m["text"]) for m in spoken if m["type"] == "delta"] == [
        (0, "ja", "ほわっ、"),
        (0, "ja", "おはようございます！"),
        (0, "zh", "哇，早上好！"),
        (1, "ja", "今日も"),
        (1, "zh", "今天也"),
    ]
    assert spoken[-1]["type"] == "done"
    assert [m["type"] for m in typed] == ["user", "delta", "delta", "done"]
    assert typed[0]["text"] == "鸽子叫什么？"
    [tts] = speech.ttss
    assert tts.voice_id == "mano-voice"
    assert "".join(tts.voiced) == "ほわっ、おはようございます！今日もピーちゃん！"  # Japanese only
    system = system_of(llm.prompts[0])
    assert "21:30" in system and "Asia/Tokyo" in system  # the time on the caller's device
    res = await client.get(f"/api/conversations/{conversation_id}/messages")
    assert [(m["role"], m["text"], m["ja"]) for m in res.json()] == [
        ("user", "早上好", None),
        ("character", None, "ほわっ、おはようございます！今日も"),
        ("user", "鸽子叫什么？", None),
        ("character", None, "ピーちゃん！"),
    ]


async def test_call_turns_look_things_up_and_remember(
    make_client: ClientFactory, speech: FakeSpeech, browser: Browser
):
    llm, jev = FakeLLM(REPLY, REPLY), FakeJudge()
    client = make_client(
        llm, retrieval_judge=jev, embedder=FakeEmbedder(), reranker=FakeReranker("猫"),
        background_llm=FakeBackgroundLLM(json.dumps({"memories": [CAT]}, ensure_ascii=False)),
    )
    assert (await browser.call(client, conversation_id=await start_conversation(client))).status_code == 200
    await browser.connect()

    await speech.stts[-1].hear("我家的猫叫小白哦")
    await browser.turn()
    browser.type("你还记得我家的猫吗？")
    await browser.turn()

    assert jev.asked == [("櫻木真乃", "我家的猫叫小白哦"), ("櫻木真乃", "你还记得我家的猫吗？")]
    context = context_of(llm.prompts[-1])
    assert CAT in context


async def test_a_call_joins_the_conversation_asked_for_muted_as_asked(
    make_client: ClientFactory, speech: FakeSpeech, browser: Browser
):
    client = make_client(FakeLLM(REPLY))
    conversation_id = await start_conversation(client, "kogane")
    res = await browser.call(client, conversation_id=conversation_id, muted=True)
    assert res.status_code == 200
    answer = res.json()
    assert answer["type"] == "answer" and answer["sdp"].startswith("v=0")
    assert answer["pc_id"]
    await browser.connect()

    await speech.stts[-1].hear("你好")
    messages = await browser.turn()

    assert messages[-1]["type"] == "done"
    assert [tts.voice_id for tts in speech.ttss] == ["kogane-voice"]
    assert speech.ttss[-1].voiced == []
    res = await client.get(f"/api/conversations/{conversation_id}/messages")
    assert [m["text"] for m in res.json()] == ["你好", None]


async def test_a_call_waits_for_a_follow_on_as_long_as_its_speech_recognition_needs(
    make_client: ClientFactory, speech: FakeSpeech, browser: Browser
):
    speech.follow_on_timeout = 0.3
    client = make_client(FakeLLM(["<ja>ほわっ", "</ja><zh>哇</zh>"], REPLY, delay=0.5))
    await browser.call(client, conversation_id=await start_conversation(client))
    await browser.connect()

    await speech.stts[-1].hear("早上好")
    await browser.next_server_message("user")
    await speech.stts[-1].start_talking()  # and never says anything

    async with asyncio.timeout(2):  # well within Soniox's 4 s
        again = await browser.next_server_message("user")
    assert again["text"] == "早上好"


async def test_a_call_that_never_connects_does_not_count(
    make_client: ClientFactory, one_call_an_hour: Settings, browser: Browser,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(eidolon.call, "CONNECT_TIMEOUT", timedelta(seconds=0.2))
    client = make_client(FakeLLM(), settings=one_call_an_hour)
    conversation_id = await start_conversation(client)

    assert (await browser.call(client, conversation_id=conversation_id)).status_code == 200
    assert browser.pc_id is not None
    await until_gone(client, browser.pc_id)  # the answer was never taken up

    async with open_browser() as again:
        assert (await again.call(client, conversation_id=conversation_id)).status_code == 200


async def test_a_call_whose_voice_services_cannot_be_made_is_refused_and_does_not_count(
    make_client: ClientFactory, one_call_an_hour: Settings, speech: FakeSpeech, browser: Browser
):
    client = make_client(FakeLLM(), settings=one_call_an_hour)
    conversation_id = await start_conversation(client)
    speech.down = True

    res = await browser.call(client, conversation_id=conversation_id)

    assert res.status_code == 500
    assert res.json()["detail"] == "无法建立通话"
    speech.down = False
    async with open_browser() as again:
        assert (await again.call(client, conversation_id=conversation_id)).status_code == 200


async def test_a_call_failing_as_it_is_answered_never_connected_and_lets_go_of_its_keys(
    one_call_an_hour: Settings, speech: FakeSpeech, monkeypatch: pytest.MonkeyPatch,
    characters: Characters,
):
    """Answering the offer is replaced, raising: whatever fails in Pipecat as it answers is
    caught there, so no fake can make it raise."""
    backend = build_faked(
        one_call_an_hour, FakeLLM(), background_llm=FakeBackgroundLLM(), speech=speech,
        characters=characters,
    )
    try:
        user = (await backend.store.create_user("producer")).id
        conversation = await backend.store.create_conversation(user, "mano")
        released: list[None] = []
        lease = backend.config.lease

        def counted_lease() -> DeployerLease:
            held = lease()

            def release() -> None:
                released.append(None)
                held.release()

            return DeployerLease(held.keys, release)

        async def answer(request: object, serve: object) -> dict | None:
            raise RuntimeError("the offer could not be answered")

        monkeypatch.setattr(backend.config, "lease", counted_lease)
        monkeypatch.setattr(backend.calls, "_answer", answer)

        with pytest.raises(RuntimeError):
            await backend.calls.start(
                user, conversation, backend.characters["mano"], CallOptions(),
                SessionDescription("v=0", "offer"),
            )

        records, _ = await backend.activity.since(backend.clock() - timedelta(hours=1))
        assert [(r.kind, r.result) for r in records] == [("call", "not_connected")]
        assert released == [None]
        await backend.usage.take(user, "call")  # given back: the hour's one call is still there
    finally:
        await backend.aclose()


async def test_a_call_whose_voice_service_fails_before_any_turn_does_not_count(
    make_client: ClientFactory, one_call_an_hour: Settings, speech: FakeSpeech, browser: Browser
):
    client = make_client(FakeLLM(), settings=one_call_an_hour)
    conversation_id = await start_conversation(client)
    await browser.call(client, conversation_id=conversation_id)
    await browser.connect()
    assert browser.pc_id is not None

    await speech.stts[-1].break_down()
    ended = await browser.next_server_message("ended")
    await until_gone(client, browser.pc_id)

    # GLOSSARY.md「接通」: ending on a failing voice service before any turn is not connecting.
    assert (ended["reason"], ended["counts"]) == ("not_connected", False)
    async with open_browser() as again:
        assert (await again.call(client, conversation_id=conversation_id)).status_code == 200


async def test_a_call_that_took_a_turn_counts_even_if_a_service_fails_later(
    make_client: ClientFactory, one_call_an_hour: Settings, speech: FakeSpeech, browser: Browser
):
    client = make_client(FakeLLM(REPLY), settings=one_call_an_hour)
    conversation_id = await start_conversation(client)
    await browser.call(client, conversation_id=conversation_id)
    await browser.connect()
    assert browser.pc_id is not None
    await speech.stts[-1].hear("你好")
    await browser.turn()

    await speech.stts[-1].break_down()
    ended = await browser.next_server_message("ended")
    await until_gone(client, browser.pc_id)

    assert (ended["reason"], ended["counts"]) == ("dropped", True)
    async with open_browser() as again:
        assert (await again.call(client, conversation_id=conversation_id)).status_code == 429


async def test_a_call_hung_up_by_the_user_counts(
    make_client: ClientFactory, one_call_an_hour: Settings, browser: Browser
):
    client = make_client(FakeLLM(), settings=one_call_an_hour)
    conversation_id = await start_conversation(client)
    await browser.call(client, conversation_id=conversation_id)
    await browser.connect()
    assert browser.pc_id is not None

    await browser.close()
    await until_gone(client, browser.pc_id)

    async with open_browser() as again:
        assert (await again.call(client, conversation_id=conversation_id)).status_code == 429


async def test_shutting_down_hangs_up_calls_and_drops_the_reply_in_progress(
    settings: Settings, speech: FakeSpeech, browser: Browser, characters: Characters
):
    slow = FakeLLM(["<ja>ほわっ</ja><zh>哇</zh>", "<ja>今日も</ja><zh>今天也</zh>"], delay=60)
    backend = build_faked(
        settings, slow, background_llm=FakeBackgroundLLM(), speech=speech, characters=characters
    )
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(backend)),
            base_url="http://test",
            headers=SITE,
            cookies=sign_in(backend.store, "producer", backend.clock()),
        ) as client:
            user = aside(backend.store.first_user_named("producer"))
            assert user is not None
            aside(seed_characters(backend, user.id, characters))
            conversation_id = await start_conversation(client)
            await browser.call(client, conversation_id=conversation_id)
            await browser.connect()
            await speech.stts[-1].hear("你好")
            await browser.next_server_message("delta")  # the reply is under way

            await asyncio.wait_for(backend.aclose(), TIMEOUT)
            await browser.hung_up()
    finally:
        await backend.calls.aclose()  # should shutting down leave a call behind

    async with store_in(settings.database_path) as store:
        assert await store.list_messages(conversation_id) == []


async def test_a_connection_that_will_not_close_is_given_up_and_the_call_still_ends(
    settings: Settings, speech: FakeSpeech, browser: Browser, characters: Characters,
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
):
    disconnect = SmallWebRTCConnection.disconnect
    stuck: list[SmallWebRTCConnection] = []

    async def never_closes(connection: SmallWebRTCConnection) -> None:
        stuck.append(connection)
        await asyncio.Event().wait()

    monkeypatch.setattr(SmallWebRTCConnection, "disconnect", never_closes)
    monkeypatch.setattr(eidolon.call, "CONNECT_TIMEOUT", timedelta(seconds=0.2))
    monkeypatch.setattr(eidolon.call, "DISCONNECT_TIMEOUT", 0.2)
    backend = build_faked(
        settings, FakeLLM(), background_llm=FakeBackgroundLLM(), speech=speech,
        characters=characters,
    )
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(backend)),
            base_url="http://test",
            headers=SITE,
            cookies=sign_in(backend.store, "producer", backend.clock()),
        ) as client:
            user = aside(backend.store.first_user_named("producer"))
            assert user is not None
            aside(seed_characters(backend, user.id, characters))
            conversation_id = await start_conversation(client)
            # never connects, as when the browser left first: only the call closes it
            assert (await browser.call(client, conversation_id=conversation_id)).status_code == 200

            async with asyncio.timeout(TIMEOUT):
                while backend.calls.in_progress:
                    await asyncio.sleep(0.05)
            await asyncio.wait_for(backend.aclose(), TIMEOUT)  # the connection is still there

        assert stuck
        assert [r.levelname for r in caplog.records if r.name == "eidolon.call"].count(
            "WARNING"
        ) == 2
    finally:
        for connection in set(stuck):  # close them after all, so nothing is left running
            await disconnect(connection)


async def test_deleting_a_character_hangs_up_her_call_and_leaves_the_other_characters(
    make_client: ClientFactory, speech: FakeSpeech, browser: Browser
):
    """Kogane is deleted with no call of her own: Mano's goes on, heard and voiced; then
    Mano is deleted, and her call ends."""
    client = make_client(FakeLLM(REPLY))
    conversation_id = await start_conversation(client)
    await browser.call(client, conversation_id=conversation_id)
    await browser.connect()
    assert browser.pc_id is not None

    assert (await client.delete("/api/characters/kogane")).status_code == 204
    await speech.stts[-1].hear("你好")
    await browser.turn()  # Mano's call is still under way

    assert (await client.delete("/api/characters/mano")).status_code == 204
    await browser.hung_up()
    await until_gone(client, browser.pc_id)


async def test_deleting_a_character_leaves_another_characters_call_being_placed(
    make_client: ClientFactory, monkeypatch: pytest.MonkeyPatch
):
    """Kogane's call is held being placed as Mano is deleted: it is let in and served all
    the same."""
    client = make_client(FakeLLM())
    conversation_id = await start_conversation(client, "kogane")
    admissions = backend_of(client).admissions
    let_in = admissions.call
    letting_in, may_go_on = asyncio.Event(), asyncio.Event()

    async def call(*args: Any) -> Any:
        """The call is held being placed, until it may go on."""
        if not letting_in.is_set():
            letting_in.set()
            await may_go_on.wait()
        return await let_in(*args)

    monkeypatch.setattr(admissions, "call", call)
    async with open_browser() as browser:
        placing = asyncio.create_task(browser.call(client, conversation_id=conversation_id))
        try:
            await asyncio.wait_for(letting_in.wait(), TIMEOUT)
            assert (await client.delete("/api/characters/mano")).status_code == 204
            may_go_on.set()
            assert (await placing).status_code == 200
            await browser.connect()
        finally:  # however it went, the call is let go of, not left being placed
            may_go_on.set()
            await placing


async def test_deleting_a_character_cancels_her_own_call_being_placed(
    make_client: ClientFactory, monkeypatch: pytest.MonkeyPatch
):
    """Kogane's call is held being placed as she is deleted: once let in it is never
    served, and the deletion waits for it to fail before it returns."""
    client = make_client(FakeLLM())
    conversation_id = await start_conversation(client, "kogane")
    backend = backend_of(client)
    let_in = backend.admissions.call
    letting_in, may_go_on = asyncio.Event(), asyncio.Event()

    async def call(*args: Any) -> Any:
        """The call is held being placed, until it may go on."""
        if not letting_in.is_set():
            letting_in.set()
            await may_go_on.wait()
        return await let_in(*args)

    hang_up = backend.calls.hang_up
    hanging_up = asyncio.Event()

    async def deleting_her(*args: Any, **kwargs: Any) -> None:
        if kwargs.get("character_id") is not None:
            hanging_up.set()  # the deletion has reached the calls, the placing still held
        await hang_up(*args, **kwargs)

    monkeypatch.setattr(backend.admissions, "call", call)
    monkeypatch.setattr(backend.calls, "hang_up", deleting_her)
    async with open_browser() as browser:
        placing = asyncio.create_task(browser.call(client, conversation_id=conversation_id))
        deleted: asyncio.Task[httpx.Response] | None = None
        try:
            await asyncio.wait_for(letting_in.wait(), TIMEOUT)
            deleted = asyncio.create_task(client.delete("/api/characters/kogane"))
            await asyncio.wait_for(hanging_up.wait(), TIMEOUT)
            may_go_on.set()
            assert (await deleted).status_code == 204
            assert placing.done()  # settled before the deletion returned, never served
            res = await placing
        finally:  # however it went, nothing is left being placed or deleting
            may_go_on.set()
            await placing
            if deleted is not None:
                await deleted

    assert res.status_code == 500
    assert res.json()["detail"] == "无法建立通话"
    assert backend.calls.in_progress == 0


async def test_deleting_a_character_while_her_offer_is_being_answered_cancels_the_call(
    make_client: ClientFactory, monkeypatch: pytest.MonkeyPatch
):
    """Kogane's call is held being answered as she is deleted: the connection made for it
    is let go of, and the call is never served."""
    client = make_client(FakeLLM())
    conversation_id = await start_conversation(client, "kogane")
    backend = backend_of(client)
    disconnect = SmallWebRTCConnection.disconnect
    closed: list[SmallWebRTCConnection] = []

    async def watched(connection: SmallWebRTCConnection) -> None:
        closed.append(connection)
        await disconnect(connection)

    answer = backend.calls._answer
    answering, may_answer = asyncio.Event(), asyncio.Event()

    async def held_answer(request: Any, serve: Any) -> dict | None:
        answering.set()
        await may_answer.wait()
        return await answer(request, serve)

    hang_up = backend.calls.hang_up
    hanging_up = asyncio.Event()

    async def deleting_her(*args: Any, **kwargs: Any) -> None:
        if kwargs.get("character_id") is not None:
            hanging_up.set()
        await hang_up(*args, **kwargs)

    monkeypatch.setattr(SmallWebRTCConnection, "disconnect", watched)
    monkeypatch.setattr(backend.calls, "_answer", held_answer)
    monkeypatch.setattr(backend.calls, "hang_up", deleting_her)
    async with open_browser() as browser:
        placing = asyncio.create_task(browser.call(client, conversation_id=conversation_id))
        deleted: asyncio.Task[httpx.Response] | None = None
        try:
            await asyncio.wait_for(answering.wait(), TIMEOUT)
            deleted = asyncio.create_task(client.delete("/api/characters/kogane"))
            await asyncio.wait_for(hanging_up.wait(), TIMEOUT)
            may_answer.set()
            assert (await deleted).status_code == 204
            assert placing.done()  # settled before the deletion returned, never served
            res = await placing
        finally:  # however it went, nothing is left being placed or deleting
            may_answer.set()
            await placing
            if deleted is not None:
                await deleted

    assert res.status_code == 500
    assert res.json()["detail"] == "无法建立通话"
    assert backend.calls.in_progress == 0
    assert len(closed) == 1  # the connection made for the cancelled call was let go of


async def test_a_call_cancelled_just_after_being_answered_lets_go_of_the_connection(
    make_client: ClientFactory, monkeypatch: pytest.MonkeyPatch
):
    """The request is cancelled just after the offer was answered, for a role deleted
    meanwhile: the connection made for it is let go of all the same."""
    client = make_client(FakeLLM())
    conversation_id = await start_conversation(client, "kogane")
    backend = backend_of(client)
    disconnect = SmallWebRTCConnection.disconnect
    closed: list[SmallWebRTCConnection] = []

    async def watched(connection: SmallWebRTCConnection) -> None:
        closed.append(connection)
        await disconnect(connection)

    answer = backend.calls._answer
    answering, may_answer, answered = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def held_answer(request: Any, serve: Any) -> dict | None:
        answering.set()
        await may_answer.wait()
        res = await answer(request, serve)
        answered.set()
        await asyncio.Event().wait()  # held after answering, until the request is cancelled
        return res

    hang_up = backend.calls.hang_up
    hanging_up = asyncio.Event()

    async def deleting_her(*args: Any, **kwargs: Any) -> None:
        if kwargs.get("character_id") is not None:
            hanging_up.set()
        await hang_up(*args, **kwargs)

    monkeypatch.setattr(SmallWebRTCConnection, "disconnect", watched)
    monkeypatch.setattr(backend.calls, "_answer", held_answer)
    monkeypatch.setattr(backend.calls, "hang_up", deleting_her)
    async with open_browser() as browser:
        placing = asyncio.create_task(browser.call(client, conversation_id=conversation_id))
        deleted: asyncio.Task[httpx.Response] | None = None
        try:
            await asyncio.wait_for(answering.wait(), TIMEOUT)
            deleted = asyncio.create_task(client.delete("/api/characters/kogane"))
            await asyncio.wait_for(hanging_up.wait(), TIMEOUT)
            may_answer.set()
            await asyncio.wait_for(answered.wait(), TIMEOUT)
            placing.cancel()  # the browser left just after the offer was answered
            with pytest.raises(asyncio.CancelledError):
                await placing
            assert (await deleted).status_code == 204
        finally:  # however it went, nothing is left being placed or deleting
            may_answer.set()
            if not placing.done():
                placing.cancel()
            with suppress(asyncio.CancelledError):
                await placing
            if deleted is not None:
                await deleted

    assert backend.calls.in_progress == 0
    assert len(closed) == 1  # the connection made for it was let go of as it was cancelled
