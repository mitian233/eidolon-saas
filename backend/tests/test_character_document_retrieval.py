"""Character document retrieval without a database."""

from collections.abc import Sequence

import pytest

from eidolon.characters import Character
from eidolon.retrieval import DocumentPassage, Need, Retrieval, open_reference_sources
from tests.fakes import FakeEmbedder, FakeReranker


class Documents:
    async def search(
        self, query_vector: Sequence[float], character_id: str, limit: int
    ) -> list[DocumentPassage]:
        passages = {
            "one": [DocumentPassage("近的资料", "a", 0.9), DocumentPassage("远的资料", "b", 0.4)],
            "two": [DocumentPassage("另一角色的资料", "c", 1.0)],
        }
        return passages.get(character_id, [])[:limit]


class Judge:
    def __init__(self, answer: Need) -> None:
        self.answer: Need = answer

    async def judge(self, character, history, text, affinity=False, photo=False, days=None) -> tuple[Need, None, bool]:
        return self.answer, None, False


ONE = Character("one", "一", "", "", "")
TWO = Character("two", "二", "", "", "")


@pytest.mark.parametrize("mode", ["references", "recall", "tool"])
async def test_all_paths_use_only_current_character_documents(mode):
    source = open_reference_sources(FakeEmbedder(), Documents())
    retrieval = Retrieval(Judge("recall" if mode == "recall" else "references"), source, FakeReranker("近的资料", others=0.1), lambda: 0.8)
    result = (await retrieval.recall_story(ONE, "问题")) if mode == "tool" else (
        await retrieval.retrieve(ONE, [], "问题")
    ).prompt
    assert result is not None
    assert "近的资料" in result
    assert "远的资料" not in result
    assert "另一角色的资料" not in result
    other = await retrieval.recall_story(TWO, "问题")
    assert "另一角色的资料" not in other  # below the relevance threshold


@pytest.mark.parametrize("mode", ["references", "recall", "tool"])
async def test_no_reranker_falls_back_to_nearest_passages(mode):
    retrieval = Retrieval(Judge("recall" if mode == "recall" else "references"), open_reference_sources(FakeEmbedder(), Documents()), None, lambda: 1.0)
    result = (await retrieval.recall_story(ONE, "问题")) if mode == "tool" else (
        await retrieval.retrieve(ONE, [], "问题")
    ).prompt
    assert result is not None and "近的资料" in result
    assert "另一角色的资料" not in result
