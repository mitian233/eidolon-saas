"""The deployment's choice of speech recognition (ADR-0010): Soniox or Alibaba Cloud Model
Studio (阿里云百炼), chosen by `STT_PROVIDER`; the deployer's DashScope key tried as the
server starts, which refuses to start on a key that cannot be used; each call heard by
whichever service its key is for, waiting for follow-ons as long as that service needs; and
a user's own key tried on the service they chose before it is kept."""

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import uvicorn
from fastapi import FastAPI
from pipecat.services.soniox.stt import SonioxSTTService

import eidolon.__main__
from eidolon.__main__ import main
from eidolon.assembly import Backend
from eidolon.bailian import BailianSTTService
from eidolon.call import SpeechServices
from eidolon.config import DEFAULT_BAILIAN_STT_MODEL, Settings, SttKey
from eidolon.own_keys import BroughtKeys, OwnKeyRejected
from tests.fakes import FakeDashScope

ENV = (
    "STT_PROVIDER", "SONIOX_API_KEY", "DASHSCOPE_API_KEY", "BAILIAN_STT_MODEL",
    "SILICONFLOW_API_KEY", "AI_GATEWAY_API_KEY", "JEV_API_KEY", "JUDGE_PROVIDER",
)


@pytest.fixture(autouse=True)
def environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    for name in ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CHAT_LLM_BASE_URL", "http://127.0.0.1:9/v1")
    monkeypatch.setenv("CHAT_LLM_API_KEY", "chat-key")
    monkeypatch.setenv("CHAT_LLM_MODEL", "chat-model")
    monkeypatch.setenv("EIDOLON_DATABASE_PATH", str(tmp_path / "eidolon.db"))


def test_soniox_hears_calls_unless_the_deployer_chooses_otherwise(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("SONIOX_API_KEY", "soniox-key")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "dashscope-key")

    settings = Settings.from_env()

    assert settings.stt_provider == "soniox"
    assert settings.stt_key == SttKey("soniox", "soniox-key")


def test_alibaba_cloud_model_studio_hears_calls_on_the_dashscope_key(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("STT_PROVIDER", "bailian")
    monkeypatch.setenv("SONIOX_API_KEY", "soniox-key")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "dashscope-key")

    settings = Settings.from_env()

    assert settings.stt_key == SttKey("bailian", "dashscope-key")
    assert settings.bailian_stt_model == DEFAULT_BAILIAN_STT_MODEL


def test_without_the_chosen_services_key_there_is_no_deployers_key_for_speech_recognition(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("STT_PROVIDER", "bailian")
    monkeypatch.setenv("SONIOX_API_KEY", "soniox-key")

    assert Settings.from_env().stt_key is None


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("STT_PROVIDER", "aliyun"),
        ("BAILIAN_STT_MODEL", "qwen-audio-3.0-asr-flash-streaming"),
        ("BAILIAN_STT_MODEL", "fun-asr-realtime"),
    ],
)
def test_a_speech_recognition_setting_out_of_its_choices_stops_the_start(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], name: str, value: str
):
    monkeypatch.setenv(name, value)

    assert main(["serve"]) == 1
    err = capsys.readouterr().err
    assert name in err and value in err


# The deployer's DashScope key, tried as the server starts.


async def serve() -> int:
    """`eidolon serve`, in a thread of its own: it runs event loops of its own, and the
    fake DashScope answers on this one."""
    return await asyncio.to_thread(main, ["serve"])


@pytest.fixture
async def started(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[list[Backend]]:
    """The backend of each server that would have started, rather than starting it; the
    chat model is taken to pass its check."""

    async def chat_model_fit(settings: Settings) -> None:
        pass

    backends: list[Backend] = []

    def run(app: FastAPI, **_: object) -> None:
        backends.append(app.state.backend)

    monkeypatch.setattr(eidolon.__main__, "_check_chat_llm", chat_model_fit)
    monkeypatch.setattr(uvicorn, "run", run)
    yield backends
    for backend in backends:
        await backend.aclose()


async def test_the_deployers_dashscope_key_is_found_in_its_region_as_the_server_starts(
    monkeypatch: pytest.MonkeyPatch, dashscope: FakeDashScope, started: list[Backend]
):
    monkeypatch.setenv("STT_PROVIDER", "bailian")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "dashscope-key")
    monkeypatch.setenv("FISH_AUDIO_API_KEY", "fish-key")
    dashscope.keys["dashscope-key"] = "singapore"

    assert await serve() == 0

    [backend] = started
    assert backend.own_keys.for_call(BroughtKeys()).stt == SttKey("bailian", "dashscope-key", "singapore")
    [task] = dashscope.tasks
    assert task.region == "singapore" and task.finished


async def test_the_server_does_not_start_on_a_dashscope_key_neither_region_takes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    dashscope: FakeDashScope, started: list[Backend],
):
    monkeypatch.setenv("STT_PROVIDER", "bailian")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "dashscope-key")

    assert await serve() == 1

    err = capsys.readouterr().err
    assert "DASHSCOPE_API_KEY" in err and "北京、新加坡" in err
    assert started == []


async def test_the_server_does_not_start_without_the_model_enabled(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    dashscope: FakeDashScope, started: list[Backend],
):
    monkeypatch.setenv("STT_PROVIDER", "bailian")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "dashscope-key")
    dashscope.keys["dashscope-key"] = "beijing"
    dashscope.not_enabled.add(DEFAULT_BAILIAN_STT_MODEL)

    assert await serve() == 1

    assert f"去阿里云百炼控制台开通 {DEFAULT_BAILIAN_STT_MODEL}" in capsys.readouterr().err
    assert started == []


async def test_without_a_dashscope_key_the_server_starts_without_trying_it(
    monkeypatch: pytest.MonkeyPatch, dashscope: FakeDashScope, started: list[Backend]
):
    monkeypatch.setenv("STT_PROVIDER", "bailian")

    assert await serve() == 0

    assert dashscope.handshakes == []
    [backend] = started
    assert backend.settings.stt_key is None


# Each call is heard by the service its key is for.


def test_a_call_on_a_soniox_key_is_heard_by_soniox():
    hearing = SpeechServices().stt(SttKey("soniox", "soniox-key"), own=False)

    assert isinstance(hearing.stt, SonioxSTTService)
    assert hearing.follow_on_timeout == 4.0


def test_a_call_on_a_dashscope_key_is_heard_by_alibaba_cloud_model_studio():
    speech = SpeechServices(DEFAULT_BAILIAN_STT_MODEL)

    hearing = speech.stt(SttKey("bailian", "dashscope-key", "beijing"), own=False)

    assert isinstance(hearing.stt, BailianSTTService)
    assert hearing.follow_on_timeout == 3.0


# A user's own key is tried, before it is kept, on the service they chose.


async def test_a_users_dashscope_key_is_tried_with_the_deployers_model_and_found_its_region(
    dashscope: FakeDashScope,
):
    dashscope.keys["my-dashscope-key"] = "singapore"
    speech = SpeechServices(DEFAULT_BAILIAN_STT_MODEL)

    key = await speech.check_stt("bailian", "my-dashscope-key", own=True)

    assert key == SttKey("bailian", "my-dashscope-key", "singapore")
    [task] = dashscope.tasks
    assert task.run_task["payload"]["model"] == DEFAULT_BAILIAN_STT_MODEL
    assert task.finished and task.audio == []


async def test_a_users_dashscope_key_refused_in_both_regions_is_said_to_be_invalid(
    dashscope: FakeDashScope,
):
    with pytest.raises(OwnKeyRejected, match="key 无效") as caught:
        await SpeechServices().check_stt("bailian", "not-a-dashscope-key", own=True)

    assert "北京、新加坡" in str(caught.value)


async def test_a_users_dashscope_key_without_the_model_enabled_says_where_to_enable_it(
    dashscope: FakeDashScope,
):
    dashscope.keys["my-dashscope-key"] = "beijing"
    dashscope.not_enabled.add(DEFAULT_BAILIAN_STT_MODEL)

    with pytest.raises(OwnKeyRejected) as caught:
        await SpeechServices().check_stt("bailian", "my-dashscope-key", own=True)

    assert f"去阿里云百炼控制台开通 {DEFAULT_BAILIAN_STT_MODEL}" in str(caught.value)
