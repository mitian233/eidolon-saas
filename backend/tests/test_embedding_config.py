"""Explicit endpoints replace embedding provider selection."""

import pytest

from eidolon.config import EmbeddingSettings, RerankSettings, Settings


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch):
    for prefix in ("EMBEDDING", "RERANK"):
        for suffix in ("BASE_URL", "MODEL", "API_KEY", "DIMENSIONS", "MIN_RELEVANCE", "MEMORY_MIN_RELEVANCE"):
            monkeypatch.delenv(f"{prefix}_{suffix}", raising=False)


def test_openrouter_base_url_embedding_settings_has_no_provider(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("EMBEDDING_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("EMBEDDING_MODEL", "qwen/qwen3-embedding-4b")
    monkeypatch.setenv("EMBEDDING_API_KEY", "sk-test")
    monkeypatch.setenv("EMBEDDING_DIMENSIONS", "768")
    embedding = EmbeddingSettings.from_env()
    assert embedding == EmbeddingSettings("https://openrouter.ai/api/v1", "qwen/qwen3-embedding-4b", 768, "sk-test")
    assert not hasattr(embedding, "provider")


def test_provider_keys_do_not_enable_embedding_or_rerank(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SILICONFLOW_API_KEY", "ignored")
    monkeypatch.setenv("GEMINI_API_KEY", "ignored")
    assert Settings.from_env().embedding is None
    assert Settings.from_env().rerank is None


def test_rerank_has_its_own_endpoint_key_and_model(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RERANK_BASE_URL", "https://rerank.example/v1")
    monkeypatch.setenv("RERANK_API_KEY", "rk-user")
    monkeypatch.setenv("RERANK_MODEL", "my-reranker")
    assert RerankSettings.from_env() == RerankSettings("rk-user", "my-reranker", "https://rerank.example/v1")
    assert EmbeddingSettings.from_env() is None


@pytest.mark.parametrize("value", ["0", "bad"])
def test_embedding_dimensions_must_be_positive(monkeypatch: pytest.MonkeyPatch, value: str):
    monkeypatch.setenv("EMBEDDING_BASE_URL", "https://embed.example/v1")
    monkeypatch.setenv("EMBEDDING_MODEL", "my-model")
    monkeypatch.setenv("EMBEDDING_API_KEY", "key")
    monkeypatch.setenv("EMBEDDING_DIMENSIONS", value)
    with pytest.raises(RuntimeError, match="EMBEDDING_DIMENSIONS"):
        EmbeddingSettings.from_env()
