"""`eidolon doctor`: each service tried as `.env` routes it, and the other way if it could
not be reached or was refused for the region; every failure put down to what it most
likely comes down to; what `EIDOLON_PROXY_SERVICES` should say for what worked only the
other way."""

import asyncio
import json
import sqlite3
from pathlib import Path

import httpx
import pytest

from eidolon.__main__ import main
from eidolon.config import ProxySettings
from eidolon.doctor import (
    Check,
    classify,
    diagnose,
    proxy_failure,
    story_episodes,
    suggested_proxy_services,
)
from eidolon.llm import LLMError

PROXY = "http://127.0.0.1:7890"


def unreachable(message: str) -> LLMError:
    """As the services raise not reaching their provider: over httpx's error, `from None`."""
    try:
        raise httpx.ConnectError("[Errno 111] Connection refused")
    except httpx.ConnectError:
        try:
            raise LLMError(message) from None
        except LLMError as e:
            return e


def works_only(way: str | None, failure: Exception) -> tuple[Check, list[str | None]]:
    """A check that works through `way` only (None for direct), and the ways it was tried."""
    tried: list[str | None] = []

    async def check(proxy: str | None) -> None:
        tried.append(proxy)
        if proxy != way:
            raise failure

    return check, tried


async def test_a_service_reached_only_the_other_way_is_moved_that_way_and_the_rest_stay():
    proxy = ProxySettings(PROXY, True, frozenset({"rerank", "own_llm"}))
    to_proxy, tried_chat = works_only(PROXY, unreachable("请求模型失败: ConnectError()"))
    to_direct, tried_rerank = works_only(None, unreachable("连不上 api.siliconflow.cn"))
    found = await diagnose({"chat_llm": to_proxy, "rerank": to_direct}, proxy)

    chat, rerank = found
    assert (chat.ok, chat.route, chat.move, chat.problem) == (True, "proxy", "proxy", "network")
    assert tried_chat == [None, PROXY]
    assert (rerank.ok, rerank.route, rerank.move) == (True, "direct", "direct")
    assert tried_rerank == [PROXY, None]
    assert suggested_proxy_services(proxy, found) == "chat_llm,own_llm"


async def test_a_service_refused_otherwise_than_for_the_region_is_tried_once():
    check, tried = works_only(PROXY, LLMError("模型返回 401: invalid api key"))
    [finding] = await diagnose({"chat_llm": check}, ProxySettings(PROXY, True, frozenset()))

    assert (finding.ok, finding.problem, finding.move) == (False, "key", None)
    assert tried == [None]
    assert "401" in finding.detail and "重新复制" in finding.hint


async def test_without_a_proxy_to_try_a_service_out_of_reach_is_told_to_have_one():
    for proxy, reachable in ((ProxySettings(), True), (ProxySettings(PROXY, True), False)):
        check, tried = works_only(PROXY, unreachable("连不上 api.openai.com"))
        [finding] = await diagnose({"chat_llm": check}, proxy, proxy_reachable=reachable)

        assert (finding.ok, finding.problem) == (False, "network"), proxy
        assert tried == [None], proxy
        assert "EIDOLON_PROXY_URL" in finding.hint, proxy
        assert suggested_proxy_services(proxy, [finding]) is None, proxy


def test_each_failure_is_put_down_to_what_it_most_likely_comes_down_to():
    cases = {
        "region": LLMError("模型返回 400: User location is not supported for the API use."),
        "network": unreachable("请求模型失败"),
        "balance": RuntimeError("402 {\"message\": \"Insufficient Balance\"}"),
        "key": LLMError("模型返回 401: Unauthorized"),
        "model": LLMError("模型返回 404: The model `gpt-9` does not exist"),
        "other": LLMError("模型的流式输出无法解析（12 字）"),
    }
    for problem, failure in cases.items():
        assert classify(failure) == problem, problem


async def test_the_proxy_is_told_apart_as_out_of_reach_or_not():
    server = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    async with server:
        assert await proxy_failure(f"http://127.0.0.1:{port}") is None
    failure = await proxy_failure(f"http://127.0.0.1:{port}")
    assert failure is not None and f"127.0.0.1:{port}" in failure


def test_the_story_corpus_is_counted_from_the_database(tmp_path: Path):
    database = tmp_path / "eidolon.db"
    assert story_episodes(database) is None
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE other (id TEXT)")
    assert story_episodes(database) == 0
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE episodes (id TEXT)")
        db.executemany("INSERT INTO episodes VALUES (?)", [("a",), ("b",)])
    assert story_episodes(database) == 2


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> pytest.MonkeyPatch:
    for name in (
        "BACKGROUND_LLM_MODEL", "BACKGROUND_LLM_BASE_URL", "JEV_API_KEY", "JUDGE_PROVIDER",
        "SILICONFLOW_API_KEY", "GEMINI_API_KEY", "FISH_AUDIO_API_KEY", "SONIOX_API_KEY",
        "DASHSCOPE_API_KEY", "STT_PROVIDER", "NOVELAI_API_KEY", "EIDOLON_PROXY_URL",
        "EIDOLON_PROXY_SERVICES", "EIDOLON_ADMINS", "EIDOLON_STAND_ASSETS_URL",
        "EIDOLON_REGISTRATION", "EIDOLON_DEV_LOGIN", "DATABASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CHAT_LLM_BASE_URL", "http://127.0.0.1:9/v1")  # nothing listens there
    monkeypatch.setenv("CHAT_LLM_API_KEY", "chat-key")
    monkeypatch.setenv("CHAT_LLM_MODEL", "chat-model")
    monkeypatch.setenv("EIDOLON_DATABASE_PATH", str(tmp_path / "eidolon.db"))
    return monkeypatch


def test_the_doctor_reports_a_chat_model_out_of_reach_and_what_is_missing(
    env: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    assert main(["doctor", "--json"]) == 1
    report = json.loads(capsys.readouterr().out)

    [chat] = report["services"]
    assert (chat["service"], chat["ok"], chat["problem"]) == ("chat_llm", False, "network")
    assert report["story_episodes"] is None and report["stand_assets_url"] is None


def test_the_doctor_says_what_in_env_keeps_the_server_from_starting(
    env: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    env.setenv("EIDOLON_PROXY_SERVICES", "chat")

    assert main(["doctor"]) == 1
    assert "EIDOLON_PROXY_SERVICES" in capsys.readouterr().out


def test_the_doctor_warns_about_invite_registration_without_admins(
    env: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], database_target: Path | str,
):
    if isinstance(database_target, str):
        env.setenv("DATABASE_URL", database_target)
    env.setenv("EIDOLON_REGISTRATION", "invite")
    main(["doctor"])
    assert "EIDOLON_ADMINS" in capsys.readouterr().out

    main(["doctor", "--json"])
    without_admins = json.loads(capsys.readouterr().out)["invite_without_admins"]
    env.setenv("EIDOLON_ADMINS", "github:9001")
    main(["doctor", "--json"])
    with_admins = json.loads(capsys.readouterr().out)["invite_without_admins"]

    assert (without_admins, with_admins) == (True, False)


def test_the_doctor_says_everyone_is_an_admin_with_dev_login_and_no_admins(
    env: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    env.setenv("EIDOLON_REGISTRATION", "invite")
    env.setenv("EIDOLON_DEV_LOGIN", "1")

    main(["doctor"])
    said = capsys.readouterr().out
    main(["doctor", "--json"])
    report = json.loads(capsys.readouterr().out)

    assert "开发登录：所有人都能进后台" in said
    assert report["invite_without_admins"] is False
