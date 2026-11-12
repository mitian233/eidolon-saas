"""Cloudflare's Clef on Workers AI as the judge model: what it is asked over the REST API,
how its envelope is read, how it is chosen and configured, and how its credentials are
tried as the server starts."""

import json
import logging

import httpx
import pytest

from eidolon.config import CloudflareJudgeSettings, JevSettings, judge_from_env
from eidolon.judge import CloudflareJudge, JudgeError, SAID, check_judge
from eidolon.retrieval import ModelRetrievalJudge
from tests.test_retrieval_services import MANO, Handler, client, recording

URL = "https://api.cloudflare.com/client/v4/accounts/acc-id/ai/run/@cf/cloudflare/clef-flash"
SETTINGS = CloudflareJudgeSettings("cf-token", "acc-id")


def envelope(answers: dict) -> dict:
    """Workers AI's REST answer: the model's, wrapped in Cloudflare's envelope."""
    result = {"model": "clef-flash", "answers": answers,
              "usage": {"input_tokens": 395, "output_tokens": 0}}
    return {"result": result, "success": True, "errors": [], "messages": []}


def refused(status: int, code: int, message: str) -> httpx.Response:
    return httpx.Response(status, json={
        "result": None, "success": False, "errors": [{"code": code, "message": message}],
        "messages": [],
    })


def clef(handle: Handler) -> CloudflareJudge:
    return CloudflareJudge("cf-token", "acc-id", "clef-flash", client(handle))


async def test_clef_is_asked_by_its_bare_name_and_answers_from_the_envelope():
    requests: list[dict] = []
    answers = {
        "needs_retrieval": {"type": "noul", "noul": 0.2},
        "recall": {"type": "noul", "noul": 0.1},
        "about_producer": {"type": "noul", "noul": 0.9},
    }
    judge = ModelRetrievalJudge(clef(recording(requests, httpx.Response(200, json=envelope(answers)))))

    assert await judge.judge(MANO, [], "我家的猫今天生病了") == ("memories", None, False)

    [request] = requests
    assert request["url"] == URL
    assert request["auth"] == "Bearer cf-token"
    assert request["model"] == "clef-flash"
    assert request["state"][SAID] == "我家的猫今天生病了"
    assert request["questions"].keys() == answers.keys()


@pytest.mark.parametrize(
    "response, error",
    [
        (httpx.Response(502, text="<html>bad gateway</html>"), "502"),
        (refused(400, 5006, "Type mismatch of '/model'"), "5006.*Type mismatch"),
        (refused(429, 4006, "you have used up your daily free allocation of 10,000 neurons"),
         "免费额度.*已用完"),
        (httpx.Response(200, text="not json"), "无法解析"),
        (httpx.Response(200, json={"result": {}, "success": True}), "无法解析"),
    ],
    ids=["http error", "success false", "quota used up", "not json", "no answers"],
)
async def test_workers_ai_failures_are_reported(response: httpx.Response, error: str):
    with pytest.raises(JudgeError, match=error):
        await clef(lambda _: response).ask({"测试": "x"}, {"q": {"type": "noul"}})


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for name in ("JUDGE_PROVIDER", "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID",
                 "CLOUDFLARE_JUDGE_MODEL", "JEV_API_KEY", "JEV_MODEL", "JEV_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CHAT_LLM_BASE_URL", "http://llm.invalid/v1")
    monkeypatch.setenv("CHAT_LLM_API_KEY", "chat-key")
    monkeypatch.setenv("CHAT_LLM_MODEL", "chat-model")
    return monkeypatch


def test_legacy_judge_config_selects_the_requested_provider(env: pytest.MonkeyPatch):
    env.setenv("JEV_API_KEY", "or-key")
    assert judge_from_env() == JevSettings("or-key")

    env.setenv("JUDGE_PROVIDER", "cloudflare")
    env.setenv("CLOUDFLARE_API_TOKEN", "cf-token")
    env.setenv("CLOUDFLARE_ACCOUNT_ID", "acc-id")
    assert judge_from_env() == CloudflareJudgeSettings("cf-token", "acc-id", "clef-flash")

    env.setenv("CLOUDFLARE_JUDGE_MODEL", "clef")
    assert judge_from_env() == CloudflareJudgeSettings("cf-token", "acc-id", "clef")


@pytest.mark.parametrize(
    "unset, overrides, named",
    [
        ((), {"JUDGE_PROVIDER": "openai"}, "JUDGE_PROVIDER"),
        ((), {"CLOUDFLARE_JUDGE_MODEL": "clef-pro"}, "CLOUDFLARE_JUDGE_MODEL"),
        (("CLOUDFLARE_API_TOKEN",), {}, "CLOUDFLARE_API_TOKEN"),
    ],
)
def test_invalid_legacy_judge_config_is_refused(
    env: pytest.MonkeyPatch, unset: tuple[str, ...], overrides: dict[str, str], named: str
):
    configured = {"JUDGE_PROVIDER": "cloudflare", "CLOUDFLARE_API_TOKEN": "cf-token",
                  "CLOUDFLARE_ACCOUNT_ID": "acc-id"}
    for name, value in (configured | overrides).items():
        if name not in unset:
            env.setenv(name, value)

    with pytest.raises(RuntimeError, match=named):
        judge_from_env()


VERIFY_URL = "https://api.cloudflare.com/client/v4/user/tokens/verify"
ACTIVE = httpx.Response(200, json={
    "result": {"id": "t", "status": "active"}, "success": True, "errors": [],
    "messages": [{"code": 10000, "message": "This API Token is valid and active"}],
})
INVALID = refused(401, 1000, "Invalid API Token")


@pytest.mark.parametrize(
    "response, verified, refusal",
    [
        # Workers AI says only "Authentication error" for a wrong token and a wrong account
        # id alike; whether the token itself is good tells them apart.
        (refused(401, 10000, "Authentication error"), INVALID, "CLOUDFLARE_API_TOKEN 无效"),
        (refused(401, 10000, "Authentication error"), ACTIVE, "CLOUDFLARE_ACCOUNT_ID 不对"),
        (refused(403, 10000, "Authentication error"), None, "CLOUDFLARE_API_TOKEN 无效.*或者"),
        (httpx.Response(404, text="Not Found"), None, "CLOUDFLARE_ACCOUNT_ID 不对"),
        (refused(400, 7003, "perhaps your object identifier is invalid?"), None,
         "CLOUDFLARE_ACCOUNT_ID 不对"),
    ],
    ids=["bad token", "bad account id", "token not verifiable", "404", "7003"],
)
async def test_credentials_cloudflare_refuses_stop_the_start(
    response: httpx.Response, verified: httpx.Response | None, refusal: str
):
    asked: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        asked.append(request)
        if str(request.url) == VERIFY_URL:
            assert request.headers["Authorization"] == "Bearer cf-token"
            if verified is None:
                raise httpx.ConnectError("unreachable", request=request)
            return verified
        return response

    with pytest.raises(RuntimeError, match=refusal):
        await check_judge(SETTINGS, client(handle))

    assert str(asked[0].url) == URL and len(json.loads(asked[0].content)["questions"]) == 1


async def test_cloudflare_out_of_reach_only_warns_as_the_server_starts(
    caplog: pytest.LogCaptureFixture,
):
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    with caplog.at_level(logging.WARNING):
        await check_judge(SETTINGS, client(timeout))

    assert "starting anyway" in caplog.text


async def test_good_credentials_and_jev_start_without_a_word(caplog: pytest.LogCaptureFixture):
    answered = envelope({"check": {"type": "noul", "noul": 0.7}})
    requests: list[dict] = []

    with caplog.at_level(logging.WARNING):
        await check_judge(SETTINGS, client(lambda _: httpx.Response(200, json=answered)))
        await check_judge(JevSettings("or-key"), client(recording(requests, httpx.Response(500))))

    assert caplog.text == ""
    assert requests == []  # Jev is not tried

