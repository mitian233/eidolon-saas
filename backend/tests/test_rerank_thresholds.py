"""The reranker's thresholds go with its model: each known model has its own, an unknown
model gets the newest's with a warning, and the environment overrides either."""

import pytest

from eidolon.config import RerankSettings
from eidolon.rerank import KNOWN_THRESHOLDS, RerankThresholds, thresholds_for


def test_each_known_model_has_its_thresholds():
    assert thresholds_for(RerankSettings("k", "Qwen/Qwen3-Reranker-0.6B")) == RerankThresholds(
        0.3, 0.01
    )
    assert thresholds_for(RerankSettings("k", "Qwen/Qwen3-Reranker-4B")) == RerankThresholds(
        0.7, 0.005
    )


def test_an_unknown_model_gets_the_4b_thresholds():
    assert thresholds_for(RerankSettings("k", "BAAI/bge-reranker-v2-m3")) == (
        KNOWN_THRESHOLDS["Qwen/Qwen3-Reranker-4B"]
    )


def test_the_environment_overrides_either_threshold(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RERANK_API_KEY", "sk-test")
    monkeypatch.setenv("RERANK_BASE_URL", "https://rerank.example/v1")
    monkeypatch.setenv("RERANK_MODEL", "Qwen/Qwen3-Reranker-0.6B")
    monkeypatch.setenv("RERANK_MEMORY_MIN_RELEVANCE", "0.05")

    settings = RerankSettings.from_env()

    assert settings is not None
    assert thresholds_for(settings) == RerankThresholds(0.3, 0.05)


@pytest.mark.parametrize("value", ["high", "1.5", "-0.1"])
def test_a_threshold_out_of_range_stops_the_start(monkeypatch: pytest.MonkeyPatch, value: str):
    monkeypatch.setenv("RERANK_API_KEY", "sk-test")
    monkeypatch.setenv("RERANK_BASE_URL", "https://rerank.example/v1")
    monkeypatch.setenv("RERANK_MODEL", "Qwen/Qwen3-Reranker-4B")
    monkeypatch.setenv("RERANK_MIN_RELEVANCE", value)

    with pytest.raises(RuntimeError, match="RERANK_MIN_RELEVANCE"):
        RerankSettings.from_env()
