"""The generic embedder speaks the OpenAI-compatible embeddings protocol. A query,
which holds up a turn, is given a few seconds and asked again once if it fails in
passing; documents are given longer."""

import asyncio
import json
from collections.abc import Callable, Coroutine
from typing import Any

import httpx
import pytest

from eidolon.embedding import Document, EmbeddingError, OpenAIEmbedder

Handler = Callable[[httpx.Request], Coroutine[Any, Any, httpx.Response]]


def embedder(requests: list[dict], status: int = 200) -> OpenAIEmbedder:
    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append({"auth": request.headers["Authorization"], **body})
        # Out of order on purpose: the index says which input each vector belongs to.
        data = [{"index": i, "embedding": [float(i), 1.0]} for i in range(len(body["input"]))]
        return httpx.Response(status, json={"data": data[::-1]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    return OpenAIEmbedder("sk-test", "Qwen/Qwen3-Embedding-0.6B", "http://sf.test/v1", client)


async def test_documents_are_embedded_in_batches_and_kept_in_order():
    requests: list[dict] = []

    vectors = await embedder(requests).embed_documents(
        [Document(f"doc {i}", "W.I.N.G.編「公園の歌声」") for i in range(20)]
    )

    assert [len(r["input"]) for r in requests] == [16, 4]
    assert requests[0]["model"] == "Qwen/Qwen3-Embedding-0.6B"
    assert requests[0]["auth"] == "Bearer sk-test"
    assert requests[0]["input"][0] == "doc 0"  # Qwen is not given the title
    assert [v[0] for v in vectors] == [float(i) for i in range(16)] + [0.0, 1.0, 2.0, 3.0]


async def test_queries_are_sent_without_provider_specific_instructions():
    requests: list[dict] = []

    await embedder(requests).embed_query("那次拍写真集是怎么回事")

    assert requests[0]["input"] == ["那次拍写真集是怎么回事"]


async def test_a_service_error_is_reported():
    with pytest.raises(EmbeddingError, match="401"):
        await embedder([], status=401).embed_documents([Document("doc")])


async def test_an_unreachable_service_is_reported():
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = httpx.AsyncClient(transport=httpx.MockTransport(refuse))
    embedder = OpenAIEmbedder("sk-test", "m", "http://sf.test/v1", client)

    with pytest.raises(EmbeddingError, match="无法连接"):
        await embedder.embed_query("在吗")


HANG = object()
"""A scripted answer: the service never answers."""
Answer = httpx.Response | Exception | object


def scripted(answers: list[Answer], answer: Callable[[httpx.Request], httpx.Response]) -> Handler:
    """A service answering with `answers` in turn (a response, an error to raise, or `HANG`),
    then as `answer` does; each request it is sent is taken off `answers`."""

    async def handle(request: httpx.Request) -> httpx.Response:
        if not answers:
            return answer(request)
        scripted = answers.pop(0)
        if scripted is HANG:
            await asyncio.Event().wait()
        if isinstance(scripted, Exception):
            raise scripted
        assert isinstance(scripted, httpx.Response)
        # A copy, as the same answer may be scripted more than once.
        return httpx.Response(scripted.status_code, content=scripted.content)

    return handle


def vectors(request: httpx.Request) -> httpx.Response:
    count = len(json.loads(request.content)["input"])
    return httpx.Response(200, json={"data": [{"index": i, "embedding": [1.0]} for i in range(count)]})


def scripted_embedder(answers: list[Answer], query_timeout: float = 0.05) -> OpenAIEmbedder:
    client = httpx.AsyncClient(transport=httpx.MockTransport(scripted(answers, vectors)))
    return OpenAIEmbedder(
        "sk-test", "m", "http://sf.test/v1", client, query_timeout=query_timeout
    )


@pytest.mark.parametrize(
    "failure",
    [
        HANG,
        httpx.ConnectError("connection refused"),
        httpx.Response(429, text="rate limited"),
        httpx.Response(503, text="unavailable"),
    ],
)
async def test_a_query_failing_in_passing_is_asked_again_at_once(failure: Answer):
    answers = [failure]

    assert await scripted_embedder(answers).embed_query("在吗") == [1.0]
    assert answers == []


@pytest.mark.parametrize(
    "failure, error",
    [
        (HANG, "没有回应"),
        (httpx.ConnectError("connection refused"), "无法连接"),
        (httpx.Response(502, text="bad gateway"), "502"),
    ],
)
async def test_a_query_failing_twice_is_reported(failure: Answer, error: str):
    answers = [failure, failure, httpx.Response(200)]

    with pytest.raises(EmbeddingError, match=error):
        await scripted_embedder(answers).embed_query("在吗")
    assert len(answers) == 1  # asked twice, no more


@pytest.mark.parametrize(
    "failure, error",
    [
        (httpx.Response(401, text="unauthorized"), "401"),
        (httpx.Response(400, text="bad request"), "400"),
        (httpx.Response(200, json={"oops": []}), "无法解析"),
    ],
)
async def test_a_query_refused_or_unreadable_is_not_asked_again(failure: Answer, error: str):
    answers = [failure, httpx.Response(200)]

    with pytest.raises(EmbeddingError, match=error):
        await scripted_embedder(answers).embed_query("在吗")
    assert len(answers) == 1


async def test_documents_take_longer_than_a_query_may():
    async def slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.2)
        return vectors(request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(slow))
    embedder = OpenAIEmbedder("sk-test", "m", "http://sf.test/v1", client, query_timeout=0.05)

    assert await embedder.embed_documents([Document("doc")]) == [[1.0]]
    with pytest.raises(EmbeddingError, match="没有回应"):
        await embedder.embed_query("在吗")
