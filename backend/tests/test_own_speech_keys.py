"""Bringing your own speech keys, and what bringing your own keys exempts from the limits.

Fish Audio (speech synthesis) and Soniox or Alibaba Cloud Model Studio (speech recognition,
whichever the user chose) keys are tried once, without being kept, before the browser keeps
them. Before a call, the browser says which services it will bring its own keys for
(`own`), and is told whether the call would count; the call itself brings the keys
(`own_keys` in the offer's request data), which decide whose services it runs on and
whether it counts, whatever was said before. One that fails ends the call saying which,
without falling back to the deployer's. Calls count towards the hourly limit unless the
LLM, synthesis and recognition are all the user's own (text turns on their own LLM: see
test_admission). How long a call may last and how many turns it may take is the same for
everyone."""

import asyncio
from dataclasses import replace
from typing import Any

import httpx
import pytest

from eidolon.call import FishTTS, SpeechServices
from eidolon.config import Settings, SttKey, UsageLimits
from tests.browser import Browser, open_browser
from tests.conftest import ClientFactory
from tests.fakes import (
    DEPLOYER_FISH_KEY,
    DEPLOYER_SONIOX_KEY,
    FakeClock,
    FakeLLM,
    FakeLLMService,
    FakeSpeech,
)
from tests.test_delete_account import rows_mentioning
from tests.test_fish_segments import FakeFish, FakeFishSocket
from tests.test_text_turn import start_conversation

REPLY = ["<ja>はいっ</ja><zh>好的</zh>"]
MY_FISH = "fish-my-own-key-aaaa"
MY_SONIOX = "soniox-my-own-key-bbbb"
MY_DASHSCOPE = "sk-my-own-dashscope-dddd"
MY_LLM = {
    "base_url": "https://llm.example.com/v1", "api_key": "sk-my-own-llm-cccc", "model": "m",
    "protocol": "chat-completions",
}
OWN_KEYS = {
    "llm": MY_LLM,
    "tts": {"api_key": MY_FISH},
    "stt": {"api_key": MY_SONIOX, "provider": "soniox"},
}


def own_keys(*services: str) -> dict:
    """The user's own keys for `services`, as the browser brings them with a call."""
    return {service: OWN_KEYS[service] for service in services}


async def ask_before_calling(client: httpx.AsyncClient, *services: str) -> httpx.Response:
    """Ask before a call, saying it will bring the user's own keys for `services`."""
    return await client.get("/api/ice-servers", params={"own": ",".join(services)})


def limited(settings: Settings, **limits: int | None) -> Settings:
    return replace(settings, usage_limits=UsageLimits(**limits))  # pyright: ignore[reportArgumentType]


async def test_speech_keys_are_tried_and_not_kept(
    make_client: ClientFactory, speech: FakeSpeech, settings: Settings
):
    client = make_client(FakeLLM())

    tts = await client.post("/api/account/keys/tts/check", json={"api_key": MY_FISH})
    stt = await client.post("/api/account/keys/stt/check", json={"api_key": MY_SONIOX})

    assert (tts.status_code, stt.status_code) == (200, 200)
    assert stt.json() == {"region": None}
    assert speech.checked == [("tts", MY_FISH), ("soniox", MY_SONIOX)]
    assert MY_FISH not in tts.text and MY_SONIOX not in stt.text
    assert rows_mentioning(settings.database_path, "aaaa") == {}
    assert rows_mentioning(settings.database_path, "bbbb") == {}


async def test_a_dashscope_key_is_tried_in_both_regions_and_the_call_hears_in_the_one_it_works_in(
    make_client: ClientFactory, speech: FakeSpeech, browser: Browser
):
    speech.regions[MY_DASHSCOPE] = "singapore"
    client = make_client(FakeLLM())

    checked = await client.post(
        "/api/account/keys/stt/check", json={"api_key": MY_DASHSCOPE, "provider": "bailian"}
    )
    assert checked.status_code == 200, checked.text
    assert checked.json() == {"region": "singapore"}
    assert speech.checked == [("bailian", MY_DASHSCOPE)]

    stt = {"api_key": MY_DASHSCOPE, "provider": "bailian", "region": "singapore"}
    await browser.call(
        client, conversation_id=await start_conversation(client), own_keys={"stt": stt}
    )
    await browser.connect()

    assert [stt.key for stt in speech.stts] == [SttKey("bailian", MY_DASHSCOPE, "singapore")]

    await speech.stts[-1].break_down()

    ended = await browser.next_server_message("ended")
    assert "你的语音识别（阿里云百炼）密钥调用失败" in ended["message"]


async def test_a_call_hears_and_speaks_on_the_keys_it_brings(
    make_client: ClientFactory, speech: FakeSpeech, browser: Browser
):
    client = make_client(FakeLLM(REPLY))

    await browser.call(
        client,
        conversation_id=await start_conversation(client, "kogane"),
        own_keys=own_keys("tts", "stt"),
    )
    await browser.connect()

    assert [stt.key for stt in speech.stts] == [SttKey("soniox", MY_SONIOX)]
    assert [(tts.api_key, tts.voice_id) for tts in speech.ttss] == [(MY_FISH, "kogane-voice")]


async def test_custom_characters_voice_and_own_key_reach_fish(
    make_client: ClientFactory, speech: FakeSpeech, browser: Browser, monkeypatch: pytest.MonkeyPatch
):
    fish = FakeFish()
    headers: list[dict[str, str]] = []
    started = asyncio.Event()
    send = FakeFishSocket.send

    async def connect(self: FishTTS, uri: str, **kwargs: Any) -> Any:
        headers.append(kwargs["additional_headers"])
        return await fish.connect()

    async def record_start(self: FakeFishSocket, data: bytes) -> None:
        await send(self, data)
        if fish.starts:
            started.set()

    monkeypatch.setattr(FishTTS, "_websocket_connect", connect)
    monkeypatch.setattr(FakeFishSocket, "send", record_start)
    monkeypatch.setattr(SpeechServices, "stt", lambda self, key, *, own: speech.stt(key, own=own))
    client = make_client(FakeLLM(REPLY), speech=SpeechServices())

    created = await client.post("/api/characters", json={
        "name": "向导", "sheet": "你是山间向导。", "voice_id": "custom-fish-voice",
        "language_mode": "bilingual",
    })
    assert created.status_code == 201, created.text
    character = created.json()
    assert character["voice_id"] == "custom-fish-voice"
    conversation_id = await start_conversation(client, character["id"])
    called = await browser.call(client, conversation_id=conversation_id, own_keys=own_keys("tts"))
    assert called.status_code == 200, called.text
    await browser.connect()
    browser.type("你好")
    turn = await browser.turn()
    await asyncio.wait_for(started.wait(), 10)

    assert turn[0]["text"] == "你好" and turn[-1]["type"] == "done"
    assert fish.starts and all(start["reference_id"] == "custom-fish-voice" for start in fish.starts)
    assert headers and all(header["Authorization"] == f"Bearer {MY_FISH}" for header in headers)


async def test_the_deployers_keys_serve_what_the_call_did_not_bring(
    make_client: ClientFactory, speech: FakeSpeech, browser: Browser
):
    client = make_client(FakeLLM())

    await browser.call(
        client, conversation_id=await start_conversation(client), own_keys=own_keys("stt")
    )

    assert [stt.api_key for stt in speech.stts] == [MY_SONIOX]
    assert [tts.api_key for tts in speech.ttss] == [DEPLOYER_FISH_KEY]
    assert DEPLOYER_SONIOX_KEY not in {stt.api_key for stt in speech.stts}


async def test_the_users_own_keys_let_them_call_where_the_deployer_has_none(
    make_client: ClientFactory, browser: Browser
):
    client = make_client(FakeLLM(), voice_configured=False)
    conversation_id = await start_conversation(client)

    assert (await ask_before_calling(client)).status_code == 503
    assert (await ask_before_calling(client, "tts")).status_code == 503
    assert (await ask_before_calling(client, "tts", "stt")).status_code == 200
    assert (await browser.call(client, conversation_id=conversation_id)).status_code == 503
    called = await browser.call(
        client, conversation_id=conversation_id, own_keys=own_keys("tts", "stt")
    )
    assert called.status_code == 200


async def test_asking_before_a_call_needs_services_there_are(make_client: ClientFactory):
    client = make_client(FakeLLM())

    assert (await ask_before_calling(client, "llm", "gpu")).status_code == 422


async def test_a_failing_own_speech_key_ends_the_call_saying_which(
    make_client: ClientFactory, speech: FakeSpeech, browser: Browser
):
    client = make_client(FakeLLM())
    await browser.call(
        client, conversation_id=await start_conversation(client), own_keys=own_keys("stt")
    )
    await browser.connect()

    await speech.stts[-1].break_down()

    ended = await browser.next_server_message("ended")
    assert "你的语音识别（Soniox）密钥调用失败" in ended["message"]
    assert (ended["reason"], ended["counts"]) == ("own_key", False)  # before any turn
    await browser.hung_up()
    assert [stt.api_key for stt in speech.stts] == [MY_SONIOX]  # no second try on the deployer's


# Calls count unless they bring all three; what is said before only answers whether it
# would, and the call goes by what it brings.
@pytest.mark.parametrize(
    ("said", "brought", "counted"),
    [(("llm", "tts", "stt"), ("llm", "tts"), True), ((), ("llm", "tts", "stt"), False)],
)
async def test_whether_a_call_counts_is_what_it_brings_not_what_was_said_before(
    make_client: ClientFactory,
    settings: Settings,
    said: tuple[str, ...],
    brought: tuple[str, ...],
    counted: bool,
):
    client = make_client(FakeLLM(), settings=limited(settings, calls_per_hour=1), clock=FakeClock())
    conversation_id = await start_conversation(client)

    said_exempt = (await ask_before_calling(client, *said)).json()["callExempt"]
    assert said_exempt is (set(said) == {"llm", "tts", "stt"})
    async with open_browser() as first:
        called = await first.call(
            client, conversation_id=conversation_id, own_keys=own_keys(*brought)
        )
        assert called.status_code == 200
        await first.connect()
    async with open_browser() as second:
        called = await second.call(client, conversation_id=conversation_id)
        assert (called.status_code == 429) is counted


async def test_a_calls_own_limits_hold_for_everyone(
    make_client: ClientFactory,
    settings: Settings,
    own_llm: FakeLLMService,
    speech: FakeSpeech,
    browser: Browser,
):
    own_llm.llm = FakeLLM(REPLY)
    client = make_client(FakeLLM(), settings=limited(settings, turns_per_call=1))
    await browser.call(
        client,
        conversation_id=await start_conversation(client),
        own_keys=own_keys("llm", "tts", "stt"),
    )
    await browser.connect()

    await speech.stts[-1].hear("你好")
    await browser.turn()

    assert "1 轮" in (await browser.next_server_message("ended"))["message"]
