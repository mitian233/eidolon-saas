"""In-memory character document source for conversation tests."""

from collections.abc import Sequence

from eidolon.retrieval import DocumentPassage
from tests.fakes import FakeEmbedder

PARK_LINE = "雨の公園で鳩を数えていました"


class FakeDocuments:
    def __init__(self) -> None:
        self.texts = {
            "mano": [
                PARK_LINE,
                "町の音楽祭で優勝した日",
                "ドームで歌いました",
                "生日是3月4日，喜欢鸟。",
                "人物关系 / 井原灯里\n社区电台的同事，性格认真。",
                "深町あおい是伙伴。",
                "ポポちゃん 常和紗季在一起的鸽子。",
                "公園 紗季常去公园看鸟。",
            ],
            "kogane": ["来自长崎，最喜欢ちゃんぽん。"],
        }

    async def search(
        self, query_vector: Sequence[float], character_id: str, limit: int
    ) -> list[DocumentPassage]:
        embedder = FakeEmbedder()
        texts = self.texts.get(character_id, [])
        passages = [
            DocumentPassage(text, str(i), sum(a * b for a, b in zip(query_vector, embedder._vector(text))))
            for i, text in enumerate(texts)
        ]
        return sorted(passages, key=lambda p: -p.similarity)[:limit]
