"""Choosing the embedding service at deploy time (ADR-0005): SiliconFlow's Qwen3-Embedding
by default, or Google's Gemini Embedding 2; reranking stays on SiliconFlow either way."""

from pathlib import Path

import pytest

from eidolon.config import EmbeddingSettings, LLMSettings, RerankSettings, Settings
from eidolon.embedding import GeminiEmbedder, SiliconFlowEmbedder, open_embedder
from tests.fakes import FakeBackgroundLLM, FakeJudge, FakeLLM, FakeSpeech, build_faked

NAMES = (
    "EMBEDDING_PROVIDER", "EMBEDDING_MODEL", "EMBEDDING_DIMENSIONS", "GEMINI_API_KEY",
    "GEMINI_BASE_URL", "SILICONFLOW_API_KEY", "SILICONFLOW_BASE_URL", "RERANK_MODEL",
    "RERANK_MIN_RELEVANCE", "RERANK_MEMORY_MIN_RELEVANCE", "AI_GATEWAY_API_KEY", "JEV_API_KEY",
    "JEV_MODEL", "JUDGE_PROVIDER",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CHAT_LLM_BASE_URL", "http://llm.invalid/v1")
    monkeypatch.setenv("CHAT_LLM_API_KEY", "chat-key")
    monkeypatch.setenv("CHAT_LLM_MODEL", "chat-model")


def test_siliconflow_is_the_default_and_embeds_and_reranks(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SILICONFLOW_API_KEY", "sk-test")

    settings = Settings.from_env()

    assert settings.embedding == EmbeddingSettings(
        "siliconflow", "sk-test", "Qwen/Qwen3-Embedding-0.6B", "https://api.siliconflow.cn/v1"
    )
    assert settings.rerank == RerankSettings("sk-test", "Qwen/Qwen3-Reranker-0.6B")
    assert settings.embedding is not None
    embedder = open_embedder(settings.embedding)
    assert isinstance(embedder, SiliconFlowEmbedder)
    assert embedder.model == "Qwen/Qwen3-Embedding-0.6B"  # as before: no re-embedding needed


def test_gemini_embeds_with_its_own_key_and_dimensions(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("EMBEDDING_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "gm-key")
    monkeypatch.setenv("SILICONFLOW_API_KEY", "sk-test")

    settings = Settings.from_env()

    assert settings.embedding == EmbeddingSettings(
        "gemini", "gm-key", "gemini-embedding-2",
        "https://generativelanguage.googleapis.com/v1beta", 1536,
    )
    assert settings.rerank == RerankSettings("sk-test")
    assert settings.embedding is not None
    embedder = open_embedder(settings.embedding)
    assert isinstance(embedder, GeminiEmbedder)
    assert embedder.model == "gemini-embedding-2@1536"


def test_the_model_and_dimensions_can_be_chosen(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("EMBEDDING_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "gm-key")
    monkeypatch.setenv("EMBEDDING_MODEL", "gemini-embedding-001")
    monkeypatch.setenv("EMBEDDING_DIMENSIONS", "768")
    monkeypatch.setenv("GEMINI_BASE_URL", "http://gemini.test/v1beta")

    embedding = EmbeddingSettings.from_env()

    assert embedding == EmbeddingSettings(
        "gemini", "gm-key", "gemini-embedding-001", "http://gemini.test/v1beta", 768
    )


@pytest.mark.parametrize(
    "name, value, complaint",
    [
        ("EMBEDDING_PROVIDER", "openai", "EMBEDDING_PROVIDER"),
        ("EMBEDDING_DIMENSIONS", "abc", "EMBEDDING_DIMENSIONS"),
        ("EMBEDDING_DIMENSIONS", "127", "128"),
        ("EMBEDDING_DIMENSIONS", "3073", "3072"),
    ],
)
def test_a_bad_choice_stops_the_start(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str, complaint: str
):
    monkeypatch.setenv("EMBEDDING_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "gm-key")
    monkeypatch.setenv(name, value)

    with pytest.raises(RuntimeError, match=complaint):
        Settings.from_env()


@pytest.mark.parametrize(
    "keys",
    [
        {"GEMINI_API_KEY": "gm-key"},  # nothing to rerank with
        {"SILICONFLOW_API_KEY": "sk-test"},  # nothing to embed with: Gemini was chosen
    ],
)
async def test_retrieval_is_off_without_either_key(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    keys: dict[str, str],
):
    monkeypatch.setenv("EMBEDDING_PROVIDER", "gemini")
    for name, value in keys.items():
        monkeypatch.setenv(name, value)
    settings = Settings(
        database_path=tmp_path / "eidolon.db",
        chat_llm=LLMSettings("http://llm.invalid/v1", "k", "m"),
        embedding=EmbeddingSettings.from_env(),
        rerank=RerankSettings.from_env(),
    )

    backend = build_faked(
        settings, FakeLLM([]), background_llm=FakeBackgroundLLM(),
        retrieval_judge=FakeJudge(), speech=FakeSpeech(),
    )

    await backend.aclose()
    assert backend.corpus is None  # nothing to retrieve from without both services


