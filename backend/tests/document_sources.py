"""In-memory character document source for conversation tests."""

from collections.abc import Sequence

from eidolon.retrieval import DocumentPassage
from tests.fakes import FakeEmbedder

PARK_LINE = "公園で鳩と一緒に歌っていました"


class FakeDocuments:
    def __init__(self) -> None:
        self.texts = {
            "mano": [
                PARK_LINE,
                "WING 優勝 決勝後コミュ",
                "ドームで歌いました",
                "生日是3月4日，喜欢鸟。",
                "人物关系 / 風野灯織\nillumination STARS 的伙伴，性格认真。",
                "八宮めぐる是伙伴。",
                "ピーちゃん 常和真乃在一起的鸽子。",
                "公園 真乃常去公园看鸟。",
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
