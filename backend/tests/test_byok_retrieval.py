"""User vector endpoints and the user's LLM belong to the current turn only."""

import json
from dataclasses import replace

import httpx
import pytest
from pydantic import ValidationError

from eidolon.account_api import OwnKeysInput
from eidolon.config import Settings
from eidolon.judge import JudgeError
from eidolon.llm import LLMError
from tests.fakes import FakeLLM, FakeLLMService, FakeSpeech, build_faked


def payload(**extra):
    return {
        "llm": {"base_url": "https://llm.example/v1", "api_key": "own-llm-secret", "model": "user-model"},
        "embedding": {"base_url": "https://openrouter.ai/api/v1", "api_key": "own-vector-secret", "model": "qwen/embedding", "dimensions": 128},
        "judge_enabled": True,
        "rerank": {"base_url": "https://rerank.example/v1", "api_key": "own-rank-secret", "model": "user-reranker"},
        **extra,
    }


def test_turn_input_keeps_vector_endpoints_and_judge_switch():
    brought = OwnKeysInput.model_validate(payload(judge_enabled=False)).brought()
    assert brought.services == {"llm", "embedding", "rerank"}
    assert brought.embedding is not None and brought.rerank is not None
    assert brought.embedding.base_url == "https://openrouter.ai/api/v1"
    assert brought.embedding.api_key == "own-vector-secret"
    assert brought.embedding.dimensions == 128
    assert brought.rerank.base_url == "https://rerank.example/v1"
    assert brought.judge_enabled is False


@pytest.mark.parametrize("field,value", [("model", " "), ("base_url", "bad-address")])
def test_bad_vector_settings_are_refused(field, value):
    body = payload()
    body["embedding"][field] = value
    with pytest.raises(ValidationError):
        OwnKeysInput.model_validate(body)


async def test_user_llm_answers_all_judge_questions_in_one_request():
    from eidolon.judge import LLMJudge
    llm = FakeLLM([json.dumps({"needs_retrieval": {"noul": 0.9}, "recall": {"noul": 0.1}, "about_producer": {"noul": 0.8}})])
    judge = LLMJudge(llm)
    questions = {key: {"type": "noul", "instructions": key} for key in ("needs_retrieval", "recall", "about_producer")}
    answers = await judge.ask({"用户这句话": "我喜欢喝茶"}, questions)
    assert answers["needs_retrieval"]["noul"] == 0.9
    assert len(llm.prompts) == 1
    content = json.loads(llm.prompts[0][-1].content)
    assert content["state"] == {"用户这句话": "我喜欢喝茶"}
    assert content["questions"] == questions


@pytest.mark.parametrize("answer", ["not json", '{"a":{"noul":2}}', '{"a":{"noul":"yes"}}', '{}'])
async def test_unreadable_judge_answers_raise_judge_error(answer):
    from eidolon.judge import LLMJudge
    with pytest.raises(JudgeError):
        await LLMJudge(FakeLLM([answer])).ask({}, {"a": {"type": "noul", "instructions": "a"}})


async def test_unreachable_user_judge_raises_judge_error():
    from eidolon.judge import LLMJudge
    with pytest.raises(JudgeError):
        await LLMJudge(FakeLLM(LLMError("unavailable"))).ask({}, {"a": {"type": "noul", "instructions": "a"}})


async def test_own_judge_uses_user_key_even_with_platform_judge_configured(settings: Settings):
    own_llm = FakeLLM([json.dumps({"check": {"noul": 1.0}})])
    own_service = FakeLLMService(own_llm)
    backend = build_faked(replace(settings, ), own_llm_service=own_service, speech=FakeSpeech())
    try:
        brought = OwnKeysInput.model_validate(payload(embedding=None, rerank=None)).brought()
        turn = backend.own_keys.for_turn(brought)
        assert turn.llms.services is not None
        assert turn.llms.services.judge is not None
        answer = await turn.llms.services.judge.ask({}, {"check": {"type": "noul", "instructions": "测试吗？"}})
        assert answer == {"check": {"noul": 1.0}}
        assert own_llm.keys == ["own-llm-secret"]
        assert any(s.reasoning_effort == "low" for s in own_service.opened)
        _, calls = await backend.activity.since(__import__('datetime').datetime.min.replace(tzinfo=__import__('datetime').UTC))
        assert [(c.service, c.provider, c.own_key) for c in calls] == [("judge", "own", True)]
    finally:
        await backend.aclose()


def test_platform_judge_environment_never_requires_credentials(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("JUDGE_PROVIDER", "cloudflare")
    monkeypatch.delenv("CLOUDFLARE_API_TOKEN", raising=False)
    monkeypatch.delenv("CLOUDFLARE_ACCOUNT_ID", raising=False)
    assert not hasattr(Settings.from_env(), "judge")


async def test_generic_embeddings_use_endpoint_model_dimensions_and_plain_query():
    from eidolon.config import EmbeddingSettings
    from eidolon.embedding import Document, open_embedder
    requests = []

    def handle(request):
        requests.append((str(request.url), request.headers["authorization"], json.loads(request.content)))
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.5, 1.0]}], "usage": {"total_tokens": 3}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        embedder = open_embedder(EmbeddingSettings("https://openrouter.ai/api/v1/", "some/model", 2, "vector-key"), client)
        assert await embedder.embed_query("你好") == [0.5, 1.0]
        assert await embedder.embed_documents([Document("资料")]) == [[0.5, 1.0]]
        assert embedder.model.endswith("/some/model@2")
    assert requests == [
        ("https://openrouter.ai/api/v1/embeddings", "Bearer vector-key", {"model": "some/model", "input": [text], "dimensions": 2, "encoding_format": "float"})
        for text in ["你好", "资料"]
    ]


async def test_user_endpoint_keeps_memories_without_rerank_and_disabled_judge(make_client, settings):
    from eidolon.own_keys import OwnRetrievalService
    from tests.test_text_turn import send_turn, start_conversation

    requests = []
    def handle(request):
        body = json.loads(request.content)
        requests.append((str(request.url), request.headers["authorization"], body))
        dimensions = body["dimensions"]
        return httpx.Response(200, json={"data": [{"index": i, "embedding": [1.0] + [0.0] * (dimensions - 1)} for i, _ in enumerate(body["input"])]})

    vectors = OwnRetrievalService(public_only=False, transport=httpx.MockTransport(handle))
    own = FakeLLMService(FakeLLM(["<ja>好的</ja><zh>好的</zh>"], ['{"memories":[{"text":"用户喜欢茶","supersedes":[]}]}']))
    try:
        client = make_client(FakeLLM(), settings=replace(settings, chat_llm=None, background_llm=None), own_llm_service=own, own_retrieval_service=vectors)
        body = payload(judge_enabled=False, rerank=None)
        events = await send_turn(client, await start_conversation(client), "我喜欢茶", own_keys=body)
        assert events[-1]["type"] == "done"
        assert not any(event["type"] == "judged" for event in events)
        assert [m["text"] for m in (await client.get("/api/memories")).json()] == ["用户喜欢茶"]
        assert requests and all(url == "https://openrouter.ai/api/v1/embeddings" and key == "Bearer own-vector-secret" for url, key, _ in requests)
        assert {tool.name for tool in own.llm.tools[0]} == {"recall_story"}
        assert own.llm.keys == ["own-llm-secret", "own-llm-secret"]
    finally:
        await vectors.aclose()


async def test_disabled_judge_uses_default_call_expression(settings):
    backend = build_faked(replace(settings, ), own_llm_service=FakeLLMService(), speech=FakeSpeech())
    try:
        body = payload(judge_enabled=False, embedding=None, rerank=None)
        body.update(tts={"api_key": "fish-own"}, stt={"api_key": "soniox-own"})
        call = backend.own_keys.for_call(OwnKeysInput.model_validate(body).brought())
        assert call.emotions is None
        assert call.llms.services is not None
        assert call.llms.services.judge is None
    finally:
        await backend.aclose()


async def test_judge_score_question_uses_zero_based_levels():
    from eidolon.judge import LLMJudge
    answers = await LLMJudge(FakeLLM(['{"affinity":{"probabilities":{"0":0.1,"1":0.2,"2":0.7}}}'])).ask(
        {}, {"affinity": {"type": "score", "instructions": "态度", "criteria": ["差", "普通", "好"]}},
    )
    assert answers["affinity"]["probabilities"]["2"] == 0.7

async def test_same_model_name_at_different_endpoints_never_reuses_vectors():
    from eidolon.config import EmbeddingSettings
    from eidolon.embedding import open_embedder
    a = open_embedder(EmbeddingSettings("https://one.example/v1", "default", 2, "key"))
    b = open_embedder(EmbeddingSettings("https://two.example/v1", "default", 2, "key"))
    try:
        assert a.model != b.model
        assert "one.example" not in a.model
    finally:
        await a.aclose()
        await b.aclose()


@pytest.mark.parametrize("service", ["embedding", "rerank"])
async def test_user_vector_error_never_repeats_key_in_traceback(settings, service):
    import traceback
    from eidolon.own_keys import OwnRetrievalService
    secret = payload()[service]["api_key"]
    vectors = OwnRetrievalService(public_only=False, transport=httpx.MockTransport(lambda request: httpx.Response(401, text=f"invalid key {secret}")))
    backend = build_faked(settings, own_llm_service=FakeLLMService(), own_retrieval_service=vectors)
    try:
        services = backend.own_keys.for_turn(OwnKeysInput.model_validate(payload()).brought()).llms.services
        assert services is not None
        with pytest.raises(Exception) as error:
            if service == "embedding":
                assert services.embedder is not None
                await services.embedder.embed_query("茶")
            else:
                assert services.reranker is not None
                await services.reranker.rerank("茶", ["资料"], 1)
        assert secret not in "".join(traceback.format_exception(error.value))
    finally:
        await backend.aclose()
        await vectors.aclose()


async def test_user_recall_uses_document_source_after_model_or_dimension_change(
    make_client, own_vectors, monkeypatch
):
    import eidolon.assembly
    from eidolon.llm import ToolCall
    from eidolon.retrieval import DocumentPassage
    from tests.test_text_turn import send_turn, start_conversation

    calls = []

    class Documents:
        async def search(self, query_vector, character_id, limit):
            calls.append((character_id, list(query_vector)))
            return [DocumentPassage("约好在图书馆见面", "note", 1.0)]

    monkeypatch.setattr(eidolon.assembly, "EmptyDocumentSource", Documents)
    own = FakeLLMService(FakeLLM(
        [ToolCall("recall1", "recall_story", {"query": "见面"})],
        ["<ja>图书馆</ja><zh>图书馆</zh>"], ['{"memories":[]}'],
        [ToolCall("recall2", "recall_story", {"query": "见面"})],
        ["<ja>图书馆</ja><zh>图书馆</zh>"], ['{"memories":[]}'],
    ))
    client = make_client(FakeLLM(), own_llm_service=own, own_retrieval_service=own_vectors)
    for model, dimensions in [("first", 2), ("second", 3)]:
        body = payload(judge_enabled=False, rerank=None)
        body["embedding"].update(model=model, dimensions=dimensions)
        events = await send_turn(client, await start_conversation(client), "在哪里见面", own_keys=body)
        assert events[-1]["type"] == "done"
        assert any("图书馆" in message.content for message in own.llm.prompts[-1] if message.role == "tool")
        await client.get("/api/memories")
    assert [character for character, _ in calls] == ["mano", "mano"]


async def test_disabling_user_judge_keeps_affinity_and_cannot_bypass_existing_cooldown(make_client, settings):
    from tests.fakes import FakeClock, START
    from tests.test_affinity import keep, status
    from tests.test_text_turn import start_conversation
    client = make_client(FakeLLM(), settings=replace(settings, affinity_and_gifts=True), clock=FakeClock())
    conversation = await start_conversation(client)
    keep(settings.database_path, "producer", 0, START, cooling=True)
    assert (await status(client)).json()["tier"] == "cold"
    response = await client.post(f"/api/conversations/{conversation}/turns", json={"text":"在吗", "own_keys":payload(judge_enabled=False)})
    assert response.status_code == 409
    assert (await status(client)).json()["cooldown_until"] is not None


async def test_user_corpus_vectors_keep_models_separate_and_only_embed_current_character(database_target):
    from eidolon.corpus import Episode, Line, StoryCorpus
    from eidolon.data_access import Database
    from tests.fakes import FakeEmbedder

    db = Database(database_target)
    original = StoryCorpus(db, FakeEmbedder("original"))
    first_model, second_model = FakeEmbedder("first@13"), FakeEmbedder("second@13")
    first, second = StoryCorpus(db, first_model), StoryCorpus(db, second_model)
    try:
        await original.save([
            Episode("mine", "custom", "notes", "park", frozenset({"mine"}), (Line("me", "公園"),)),
            Episode("other", "custom", "notes", "cats", frozenset({"other"}), (Line("them", "猫"),)),
        ])
        assert await first.search("公園", "mine") == []
        await first.prepare_character("mine")
        assert first_model.documents == ["notes「park」\nme：公園"]
        assert [p.episode_id for p in await first.search("公園", "mine")] == ["mine"]
        assert await second.search("公園", "mine") == []
        await second.prepare_character("mine")
        assert [p.episode_id for p in await second.search("公園", "mine")] == ["mine"]
        await first.prepare_character("mine")
        assert first_model.documents == ["notes「park」\nme：公園"]
        assert await first.search("猫", "other") == []
    finally:
        await first.aclose()
        await second.aclose()
        await original.aclose()
        await db.close()
