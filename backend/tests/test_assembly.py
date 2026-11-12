"""Turns use the user's explicit model and vector services for recall and memory."""

import json
from collections.abc import AsyncIterator
from dataclasses import asdict
from datetime import UTC, datetime

import pytest

from eidolon.account_api import OwnKeysInput
from eidolon.assembly import Backend
from eidolon.config import Settings
from eidolon.retrieval import RECALL_STORY_TOOL
from tests.conftest import Characters
from tests.fakes import RETRIEVAL_KEYS, FakeBackgroundLLM, FakeEmbedder, FakeJudge, FakeLLM, FakeReranker, build_faked

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)
REPLY = ["<ja>はいっ</ja><zh>好的</zh>"]
CAT = "制作人家里养了一只叫小白的猫"


class Services:
    def __init__(self) -> None:
        self.chat = FakeLLM(REPLY)
        self.background = FakeBackgroundLLM(json.dumps({"memories": [CAT]}, ensure_ascii=False))
        self.retrieval_judge = FakeJudge()
        self.embedder = FakeEmbedder()
        self.reranker = FakeReranker("制作人")


@pytest.fixture
async def backends() -> AsyncIterator[list[Backend]]:
    made: list[Backend] = []
    yield made
    for backend in made:
        await backend.aclose()


async def tell_mano(backend: Backend, text: str, keys: dict | None = None) -> tuple[str, list[dict]]:
    user = await backend.store.create_user("producer")
    conversation = await backend.store.create_conversation(user.id, "mano")
    turn = backend.own_keys.for_turn(OwnKeysInput.model_validate(keys or RETRIEVAL_KEYS).brought())
    try:
        events = [asdict(e) async for e in backend.engine.turn(conversation, text, turn.llms)]
    finally:
        turn.release()
    return user.id, events


async def test_with_every_user_service_turns_retrieve_and_remember(
    settings: Settings, characters: Characters, backends: list[Backend],
):
    services = Services()
    backend = build_faked(settings, services.chat, background_llm=services.background,
                          retrieval_judge=services.retrieval_judge, embedder=services.embedder,
                          reranker=services.reranker, characters=characters, clock=lambda: NOW)
    backends.append(backend)
    user_id, events = await tell_mano(backend, "我家的猫叫小白哦")
    assert events[-1]["type"] == "done"
    assert services.chat.keys == ["test-user-secret"]
    assert services.chat.tools[0][0] == RECALL_STORY_TOOL
    assert [m.text for m in await backend.memories.entries(user_id)] == [CAT]


async def test_without_user_embedding_retrieval_and_memory_are_off(
    settings: Settings, characters: Characters, backends: list[Backend],
):
    services = Services()
    backend = build_faked(settings, services.chat, background_llm=services.background,
                          embedder=services.embedder, reranker=services.reranker,
                          characters=characters, clock=lambda: NOW)
    backends.append(backend)
    keys = {name: value for name, value in RETRIEVAL_KEYS.items() if name not in ("embedding", "rerank")}
    user_id, events = await tell_mano(backend, "我家的猫叫小白哦", keys)
    assert events[-1]["type"] == "done"
    assert RECALL_STORY_TOOL not in services.chat.tools[0]
    assert await backend.memories.entries(user_id) == []
    assert services.background.prompts == []


async def test_without_user_judge_recall_tool_and_memory_still_work(
    settings: Settings, characters: Characters, backends: list[Backend],
):
    services = Services()
    backend = build_faked(settings, services.chat, background_llm=services.background,
                          embedder=services.embedder, reranker=services.reranker,
                          characters=characters, clock=lambda: NOW)
    backends.append(backend)
    user_id, events = await tell_mano(backend, "我家的猫叫小白哦", RETRIEVAL_KEYS | {"judge_enabled": False})
    assert events[-1]["type"] == "done"
    assert RECALL_STORY_TOOL in services.chat.tools[0]
    assert [m.text for m in await backend.memories.entries(user_id)] == [CAT]



