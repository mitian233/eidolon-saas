"""A user's own key never reaches the server's logs, the deployer's to read and pass on,
whether the turn it is brought with goes well, fails, or fails to write down memories, and
whether the request bringing it is well-formed or not. A key that fails a turn, or its try
before the browser keeps it, is refused with what the service said; where that repeats the
key, it is masked there as `***`, before the message is cut short, so that no part of it
is left."""

import logging
from collections.abc import Callable, Iterator

import pytest
from loguru import logger

from eidolon.llm import LLMError
from eidolon.own_keys import MAX_CAUSE_LENGTH, OwnRetrievalService
from tests.browser import Browser
from tests.conftest import ClientFactory
from tests.fakes import (
    FakeBackgroundLLM,
    FakeEmbedder,
    FakeJudge,
    FakeLLM,
    FakeLLMService,
    FakeReranker,
    FakeSpeech,
)
from tests.test_text_turn import send_turn, start_conversation
from tests.test_own_llm import EMBEDDING

KEY = "sk-CANARY-7f3a9c2e5b1d"
PREFIX = KEY[:9]
"""As much of the key as is left if it were cut short before being masked."""
LLM = {"base_url": "https://llm.example.com/v1", "api_key": KEY, "model": "my-model"}
REPLY = ["<ja>はいっ</ja><zh>好的</zh>"]


def echoing(status: str) -> str:
    """A service's error message repeating the key across where the reason the user is
    shown is cut short."""
    padding = "x" * (MAX_CAUSE_LENGTH - 10 - len(f"{status}:  invalid api key "))
    return f"{status}: {padding} invalid api key {KEY}"


@pytest.fixture
def logged(caplog: pytest.LogCaptureFixture) -> Iterator[Callable[[], list[str]]]:
    """What has been logged so far, through Python's logging and through loguru
    (Pipecat's), loguru's from INFO up as the server shows it (`__main__`): Pipecat's
    DEBUG lines show what calls send to services, and are never shown."""
    caplog.set_level(logging.DEBUG)
    lines: list[str] = []
    sink = logger.add(lambda message: lines.append(str(message)), level="INFO")
    yield lambda: [*lines, caplog.text]
    logger.remove(sink)


async def test_own_keys_stay_out_of_the_logs_and_are_masked_in_what_the_user_is_shown(
    make_client: ClientFactory,
    own_llm: FakeLLMService,
    speech: FakeSpeech,
    logged: Callable[[], list[str]],
    own_vectors: OwnRetrievalService,
):
    own_llm.llm = FakeLLM(
        REPLY,  # the turn goes well,
        LLMError(echoing("401 Unauthorized")),  # writing down its memories does not;
        LLMError(echoing("401 Unauthorized")),  # its one retry fails too;
        LLMError(echoing("402 Payment Required")),  # the next turn fails
    )
    client = make_client(
        FakeLLM(), retrieval_judge=FakeJudge(), embedder=FakeEmbedder(), reranker=FakeReranker(),
        background_llm=FakeBackgroundLLM(),
        own_retrieval_service=own_vectors,
    )
    conversation_id = await start_conversation(client)

    done = await send_turn(client, conversation_id, "我家的猫叫小白哦", own_keys={"llm": LLM, "embedding": EMBEDDING})
    await client.get("/api/memories")  # both failed attempts finish before the next turn
    failed = await send_turn(client, conversation_id, "在吗", own_llm=LLM)
    await client.post(  # refused, its key unchecked
        f"/api/conversations/{conversation_id}/turns",
        json={"text": "在吗", "own_keys": {"llm": LLM | {"api_key": f"{KEY} with spaces"}}},
    )
    own_llm.rejects[KEY] = echoing("401 Unauthorized")
    speech.rejects[KEY] = echoing("401 Unauthorized")
    checks = {
        "llm": await client.post("/api/account/keys/llm/check", json=LLM),
        "tts": await client.post("/api/account/keys/tts/check", json={"api_key": KEY}),
        "stt": await client.post("/api/account/keys/stt/check", json={"api_key": KEY}),
    }

    assert done[-1]["type"] == "done"
    assert any("memory job" in line and "failed: OwnKeyFailed" in line for line in logged())
    assert failed[-1]["message"].endswith("***")
    assert PREFIX not in failed[-1]["message"]
    for service, res in checks.items():
        assert res.status_code == 422, service
        assert res.json()["detail"].startswith("试调失败：401 Unauthorized: "), service
        assert res.json()["detail"].endswith("***"), service
        assert PREFIX not in res.json()["detail"], service
    for line in logged():
        assert PREFIX not in line, line


@pytest.mark.parametrize(
    ("service", "own_keys"),
    [
        ("tts", {"tts": {"api_key": KEY}}),
        ("stt", {"stt": {"api_key": KEY, "provider": "soniox"}}),
    ],
)
async def test_an_own_speech_key_failing_in_a_call_stays_out_of_the_logs_and_the_reason_given(
    make_client: ClientFactory,
    speech: FakeSpeech,
    browser: Browser,
    logged: Callable[[], list[str]],
    service: str,
    own_keys: dict,
):
    client = make_client(FakeLLM())
    await browser.call(
        client, conversation_id=await start_conversation(client), own_keys=own_keys
    )
    await browser.connect()

    failing = speech.ttss[-1] if service == "tts" else speech.stts[-1]
    await failing.break_down(echoing("401 Unauthorized"))
    ended = await browser.next_server_message("ended")
    await browser.hung_up()

    assert PREFIX not in ended["message"]
    assert any("401 Unauthorized" in line for line in logged())  # it was logged,
    for line in logged():  # its key masked
        assert PREFIX not in line, line
