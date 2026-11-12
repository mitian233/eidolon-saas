"""Alibaba Cloud Model Studio's (百炼) decision model as the judge model: asked as Jev is,
over System One, at the workspace's own endpoint; how it is chosen and configured, and how
its credentials are tried as the server starts."""

import json
import logging

import httpx
import pytest

from eidolon.activity import judge_origin
from eidolon.config import BailianJudgeSettings, judge_from_env
from eidolon.judge import BailianJudge, JudgeError, check_judge, open_judge
from eidolon.retrieval import ModelRetrievalJudge
from tests.test_retrieval_services import MANO, Handler, client, recording

URL = "https://llm-ws1.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/systemone"
SETTINGS = BailianJudgeSettings("sk-bl", "llm-ws1")


def answered(answers: dict) -> httpx.Response:
    return httpx.Response(200, json={
        "model": "decision-model-preview", "request_id": "r", "answers": answers,
        "usage": {"input_tokens": 312}, "latency_ms": 180,
    })


def refused(status: int, code: str, message: str) -> httpx.Response:
    return httpx.Response(status, json={
        "error": {"message": message, "id": "e", "type": "invalid_request_error", "code": code},
    })


def bailian(handle: Handler) -> BailianJudge:
    judge = open_judge(SETTINGS, client(handle))
    assert isinstance(judge, BailianJudge)
    return judge


async def test_the_decision_model_is_asked_at_the_workspace_endpoint():
    requests: list[dict] = []
    answers = {
        "needs_retrieval": {"type": "noul", "noul": 0.2},
        "recall": {"type": "noul", "noul": 0.1},
        "about_producer": {"type": "noul", "noul": 0.9},
    }
    judge = ModelRetrievalJudge(bailian(recording(requests, answered(answers))))

    assert await judge.judge(MANO, [], "我家的猫今天生病了") == ("memories", None, False)

    [request] = requests
    assert request["url"] == URL
    assert request["auth"] == "Bearer sk-bl"
    assert request["model"] == "decision-model-preview"
    assert request["questions"].keys() == answers.keys()


def test_singapore_is_its_own_endpoint_and_either_is_recorded_without_the_workspace():
    singapore = BailianJudgeSettings("sk-bl", "llm-ws1", "singapore")

    assert singapore.base_url == "https://llm-ws1.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1"
    assert judge_origin(SETTINGS).provider == "cn-beijing.maas.aliyuncs.com"
    assert judge_origin(singapore).provider == "ap-southeast-1.maas.aliyuncs.com"


async def test_a_refusal_is_reported_as_bailian_s():
    response = refused(429, "Throttling", "Requests rate limit exceeded")
    with pytest.raises(JudgeError, match="百炼 返回 429.*rate limit"):
        await bailian(lambda _: response).ask({"测试": "x"}, {"q": {"type": "noul"}})


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for name in ("JUDGE_PROVIDER", "BAILIAN_JUDGE_API_KEY", "BAILIAN_JUDGE_WORKSPACE_ID",
                 "BAILIAN_JUDGE_REGION", "BAILIAN_JUDGE_MODEL", "JEV_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CHAT_LLM_BASE_URL", "http://llm.invalid/v1")
    monkeypatch.setenv("CHAT_LLM_API_KEY", "chat-key")
    monkeypatch.setenv("CHAT_LLM_MODEL", "chat-model")
    monkeypatch.setenv("JUDGE_PROVIDER", "bailian")
    monkeypatch.setenv("BAILIAN_JUDGE_API_KEY", "sk-bl")
    monkeypatch.setenv("BAILIAN_JUDGE_WORKSPACE_ID", "llm-ws1")
    return monkeypatch


def test_legacy_bailian_config_has_its_own_key_and_workspace(env: pytest.MonkeyPatch):
    env.setenv("JEV_API_KEY", "or-key")  # ignored
    assert judge_from_env() == SETTINGS

    env.setenv("BAILIAN_JUDGE_REGION", "singapore")
    env.setenv("BAILIAN_JUDGE_MODEL", "decision-model")
    assert judge_from_env() == BailianJudgeSettings(
        "sk-bl", "llm-ws1", "singapore", "decision-model"
    )


@pytest.mark.parametrize(
    "unset, overrides, named",
    [
        (("BAILIAN_JUDGE_WORKSPACE_ID",), {}, "BAILIAN_JUDGE_WORKSPACE_ID"),
        ((), {"BAILIAN_JUDGE_REGION": "hangzhou"}, "BAILIAN_JUDGE_REGION"),
    ],
)
def test_invalid_legacy_bailian_config_is_refused(
    env: pytest.MonkeyPatch, unset: tuple[str, ...], overrides: dict[str, str], named: str
):
    for name in unset:
        env.delenv(name)
    for name, value in overrides.items():
        env.setenv(name, value)

    with pytest.raises(RuntimeError, match=named):
        judge_from_env()


@pytest.mark.parametrize(
    "response, refusal",
    [
        # As Model Studio answered on 2026-10-18.
        (refused(401, "invalid_api_key", "Invalid API-key provided."), "BAILIAN_JUDGE_API_KEY 无效"),
        # Malformed, it is "Workspace endpoint is invalid." (400), taken alike.
        (refused(403, "access_denied", "Workspace endpoint access denied."),
         "BAILIAN_JUDGE_WORKSPACE_ID 不对.*不属于"),
        (refused(404, "model_not_found", "Model not exist."), "BAILIAN_JUDGE_MODEL 不对"),
    ],
    ids=["bad key", "another workspace", "bad model"],
)
async def test_what_bailian_refuses_stops_the_start(response: httpx.Response, refusal: str):
    asked: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        asked.append(request)
        return response

    with pytest.raises(RuntimeError, match=refusal):
        await check_judge(SETTINGS, client(handle))

    [request] = asked
    assert str(request.url) == URL and len(json.loads(request.content)["questions"]) == 1


def unreachable(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectTimeout("timed out", request=request)


@pytest.mark.parametrize(
    "handle",
    [lambda _: refused(429, "Throttling", "Requests rate limit exceeded"), unreachable],
    ids=["throttled", "unreachable"],
)
async def test_bailian_busy_or_out_of_reach_only_warns_as_the_server_starts(
    caplog: pytest.LogCaptureFixture, handle: Handler
):
    with caplog.at_level(logging.WARNING):
        await check_judge(SETTINGS, client(handle))

    assert "starting anyway" in caplog.text


async def test_bailian_answering_starts_without_a_word(caplog: pytest.LogCaptureFixture):
    with caplog.at_level(logging.WARNING):
        await check_judge(SETTINGS, client(lambda _: answered({"check": {"type": "noul", "noul": 0.3}})))

    assert caplog.text == ""
