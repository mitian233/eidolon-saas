"""Rerank protocol and the user's LLM answering retrieval questions."""

import json
from collections.abc import Callable

import httpx
import pytest

from eidolon.characters import Character
from eidolon.config import Settings
from eidolon.producer import Birthday
from eidolon.rerank import RerankError, SiliconFlowReranker
from eidolon.judge import LLMJudge, JudgeError, SAID
from eidolon.retrieval import ModelRetrievalJudge
from eidolon.store import Message
from tests.test_embedding import HANG, Answer, scripted
from tests.fakes import FakeLLM
from eidolon.llm import LLMError

Handler = Callable[[httpx.Request], httpx.Response]


def client(handle: Handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handle))


def recording(requests: list[dict], response: httpx.Response) -> Handler:
    def handle(request: httpx.Request) -> httpx.Response:
        requests.append({"url": str(request.url), "auth": request.headers["Authorization"],
                         **json.loads(request.content)})
        return response

    return handle


async def test_reranker_returns_the_best_documents_first():
    requests: list[dict] = []
    # Not sorted on purpose: the order comes from the scores.
    results = [{"index": 0, "relevance_score": 0.1}, {"index": 2, "relevance_score": 0.9},
               {"index": 1, "relevance_score": 0.5}]
    reranker = SiliconFlowReranker(
        "sk-test", "Qwen/Qwen3-Reranker-0.6B", "http://sf.test/v1",
        client(recording(requests, httpx.Response(200, json={"results": results}))),
    )

    best = await reranker.rerank("鳩の話", ["a", "b", "c"], top_n=2)

    assert best == [(2, 0.9), (1, 0.5)]
    [request] = requests
    assert request["url"] == "http://sf.test/v1/rerank"
    assert request["auth"] == "Bearer sk-test"
    assert (request["model"], request["query"], request["documents"], request["top_n"]) == (
        "Qwen/Qwen3-Reranker-0.6B", "鳩の話", ["a", "b", "c"], 2
    )


@pytest.mark.parametrize(
    "response, error",
    [
        (httpx.Response(401, text="unauthorized"), "401"),
        (httpx.Response(200, json={"oops": []}), "无法解析"),
        (httpx.Response(200, json={"results": [{"index": 7, "relevance_score": 1}]}), "不存在"),
    ],
)
async def test_reranker_errors_are_reported(response: httpx.Response, error: str):
    reranker = SiliconFlowReranker("k", "m", "http://sf.test/v1", client(lambda _: response))

    with pytest.raises(RerankError, match=error):
        await reranker.rerank("q", ["a"], top_n=1)



def ranked(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"results": [{"index": 0, "relevance_score": 0.9}]})


def scripted_reranker(answers: list[Answer]) -> SiliconFlowReranker:
    scripted_client = httpx.AsyncClient(transport=httpx.MockTransport(scripted(answers, ranked)))
    return SiliconFlowReranker("k", "m", "http://sf.test/v1", scripted_client, timeout=0.05)


@pytest.mark.parametrize(
    "failure",
    [
        HANG,
        httpx.ReadError("connection reset"),
        httpx.Response(429, text="rate limited"),
        httpx.Response(500, text="internal error"),
    ],
)
async def test_a_rerank_failing_in_passing_is_asked_again_at_once(failure: Answer):
    answers = [failure]

    assert await scripted_reranker(answers).rerank("q", ["a"], top_n=1) == [(0, 0.9)]
    assert answers == []


@pytest.mark.parametrize(
    "answers, error",
    [
        ([HANG, HANG], "没有回应"),
        ([HANG, httpx.Response(503, text="unavailable")], "503"),
        ([httpx.Response(403, text="forbidden")], "403"),
        ([httpx.Response(200, json={"oops": []})], "无法解析"),
    ],
)
async def test_a_rerank_failing_again_or_refused_is_reported(answers: list[Answer], error: str):
    answers = [*answers, httpx.Response(200)]

    with pytest.raises(RerankError, match=error):
        await scripted_reranker(answers).rerank("q", ["a"], top_n=1)
    assert len(answers) == 1  # never asked a third time, nor a second when refused


MANO = Character("mano", "櫻木真乃", "", "voice", "sheet", None, "#ffbad6", Birthday(4, 25), 16)


def message(role: str, text: str) -> Message:
    if role == "user":
        return Message(1, "user", text, None, None, "2026-09-25T00:00:00+00:00")
    return Message(2, "character", None, text, "", "2026-09-25T00:00:00+00:00")


class RecordingLLM(FakeLLM):
    def __init__(self, requests: list[dict], answers: dict) -> None:
        super().__init__([json.dumps(answers, ensure_ascii=False)])
        self.requests = requests

    async def stream(self, messages, tools=(), *, forbid_calls=False):
        self.requests.append(json.loads(messages[-1].content))
        async for chunk in super().stream(messages, tools, forbid_calls=forbid_calls):
            yield chunk


def judge_answering(
    requests: list[dict], retrieve: float, recall: float = 0.01, about_producer: float = 0.02
) -> ModelRetrievalJudge:
    answers = {
        "needs_retrieval": {"noul": retrieve},
        "recall": {"noul": recall},
        "about_producer": {"noul": about_producer},
    }
    return ModelRetrievalJudge(LLMJudge(RecordingLLM(requests, answers)))


@pytest.mark.parametrize(
    "retrieve, recall, about_producer, expected",
    [
        (0.5, 0.2, 0.1, "references"),
        (0.89, 0.03, 0.95, "references"),  # which carries memories too
        (0.21, 0.01, 0.1, "nothing"),
        (0.21, 0.01, 0.95, "memories"),
        (0.91, 0.96, 0.95, "recall"),
        (0.4, 0.5, 0.1, "recall"),
    ],
)
async def test_jev_answers_what_the_turn_needs(
    retrieve: float, recall: float, about_producer: float, expected: str
):
    requests: list[dict] = []

    judge = judge_answering(requests, retrieve, recall, about_producer)
    assert await judge.judge(MANO, [], "那次比赛") == (expected, None, False)
    [request] = requests  # all questions in one call
    assert set(request) == {"state", "questions"}
    for question in request["questions"].values():
        assert question["type"] == "noul"
        assert question["criteria"].keys() == {"true", "false"}  # System One wants both


async def test_jev_sees_the_latest_messages_and_what_was_just_said():
    requests: list[dict] = []
    history = [message("user", f"old {i}") for i in range(5)] + [message("character", "ほわっ")]

    await judge_answering(requests, 0.1).judge(MANO, history, "那次比赛")

    state = requests[0]["state"]
    assert state["角色"] == "櫻木真乃"
    assert state["上文"][-1] == "櫻木真乃：ほわっ" and "用户：old 4" in state["上文"]
    assert "用户：old 1" not in state["上文"]
    assert state[SAID] == "那次比赛"


async def test_user_model_errors_are_reported():
    judge = ModelRetrievalJudge(LLMJudge(FakeLLM(LLMError("503 busy"))))
    with pytest.raises(JudgeError, match="用户判断模型"):
        await judge.judge(MANO, [], "在吗")


async def test_unparsable_user_model_answers_are_reported():
    judge = ModelRetrievalJudge(LLMJudge(FakeLLM(["{}"])))
    with pytest.raises(JudgeError, match="用户判断模型"):
        await judge.judge(MANO, [], "在吗")




def test_the_old_gateway_key_does_not_require_a_platform_judge(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("JEV_API_KEY", raising=False)
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "gw-key")
    monkeypatch.setenv("CHAT_LLM_BASE_URL", "http://llm.invalid/v1")
    monkeypatch.setenv("CHAT_LLM_API_KEY", "chat-key")
    monkeypatch.setenv("CHAT_LLM_MODEL", "chat-model")

    assert not hasattr(Settings.from_env(), "judge")
