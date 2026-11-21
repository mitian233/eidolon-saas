"""Retrieve character document passages and the user's separate long-term memories.

The judge chooses ordinary retrieval, recall, memories, or no lookup. Embedding and
candidate search start while the judge runs; selected passages are reranked and
filtered, with a similarity fallback if reranking is unavailable. The recall_story
tool uses the same character-scoped document source.
"""

import asyncio
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from typing import Any, Literal, Protocol

from eidolon.affinity import Days, Judged
from eidolon.affinity_judge import affinity_questions, read_judged
from eidolon.characters import Character
from eidolon.embedding import Embedder, EmbeddingError
from eidolon.judge import (
    FALLBACK_FAMILY,
    JUDGE_THRESHOLDS,
    JudgeError,
    JudgeModel,
    JudgeThresholds,
    turn_state,
)
from eidolon.llm import Tool
from eidolon.memory import Memory, MemoryTurn, memory_query
from eidolon.photo_judge import QUESTIONS as PHOTO_QUESTIONS
from eidolon.photo_judge import read_asked
from eidolon.rerank import Reranker, RerankError
from eidolon.store import Message

log = logging.getLogger(__name__)

MAX_REFERENCES = 5
"""The most references one turn's prompt carries, after reranking."""
CANDIDATES_PER_SOURCE = 12
"""How many candidates each reference source offers the reranker."""
FALLBACK_REFERENCES = 3
"""How many references a turn's prompt carries if reranking fails: those nearest by their
vectors, of which no threshold can tell the relevant."""

RECALL_PASSAGES = 2
"""The most passages one call of the recall-story tool brings back after reranking."""

RECALL_STORY_TOOL = Tool(
    name="recall_story",
    description="回顾背景资料：查找和某件事有关的已有记录，返回相关内容。"
    "当用户问起过去的事、而你想不起具体经过时使用；闲聊时不需要。",
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "要回顾的事，写成一句概括，例如「第一次见面时的约定」",
            }
        },
        "required": ["query"],
    },
)


_NOT_IN_STORY = (
    "背景资料里没有记录这段经过，但这不等于这件事没有发生过。"
    "不要编造经过，也不要说没有这回事；可以坦率地说细节记不太清了"
)
_CANNOT_RECALL = "暂时想不起来，现在查不到资料。不要编造经过，可以坦率地说记不太清了。"


Need = Literal["nothing", "memories", "references", "recall"]
"""What a turn needs looked up: nothing, the user's memories only, character references
along with the user's memories, or a recall of past events."""


class RetrievalJudge(Protocol):
    async def judge(
        self,
        character: Character,
        history: Sequence[Message],
        text: str,
        affinity: bool = False,
        photo: bool = False,
        days: Days | None = None,
    ) -> tuple[Need, Judged | None, bool]:
        """What answering `text` needs looked up; asked about `affinity` too, what saying it
        does to her affinity (None if that alone cannot be told), the considerate question
        asked too in her `days`; and asked about `photo`, whether it asks her for a photo (no if that alone cannot be told)."""
        ...


@dataclass(frozen=True)
class DocumentPassage:
    """A character document passage and its similarity to the query vector."""

    text: str
    origin: str
    similarity: float


class CharacterDocumentSource(Protocol):
    async def search(
        self, query_vector: Sequence[float], character_id: str, limit: int
    ) -> list[DocumentPassage]:
        """Return only this character's passages, nearest first, up to limit.

        Vectors must belong to the query embedder's model and dimensions.
        """
        ...


class ReferenceSources:
    """Search and rank references from the character document source."""

    def __init__(self, embedder: Embedder, source: CharacterDocumentSource) -> None:
        self.embedder = embedder
        self._source = source

    async def candidates(
        self,
        query_vector: Sequence[float],
        character: Character,
    ) -> list[DocumentPassage]:
        """The character's nearest passages for a query embedded with this embedder."""
        return await self._source.search(query_vector, character.id, CANDIDATES_PER_SOURCE)

    async def rerank(
        self, reranker: Reranker, query: str, candidates: Sequence[DocumentPassage]
    ) -> list[tuple[DocumentPassage, float]]:
        """The `candidates` for `query`, with the reranker's score, best first, reranked
        together. Raises RerankError."""
        if not candidates:
            return []
        best = await reranker.rerank(query, [c.text for c in candidates], len(candidates))
        return [(candidates[i], score) for i, score in best]

    def prompt(self, references: Sequence[DocumentPassage]) -> str:
        """The prompt section carrying a turn's references from the character's documents."""
        lines = [
            "# 回忆与资料",
            "下面是和用户这句话可能有关的内容，按相关程度排列，和话题无关的可以忽略。",
            "- 以下资料来自角色知识库，只根据资料中记载的内容回答。",
        ]
        for reference in references:
            lines += ["", "## 角色资料", reference.text]
        return "\n".join(lines)


def open_reference_sources(embedder: Embedder, source: CharacterDocumentSource) -> ReferenceSources:
    """Open the character document source for this embedder."""
    return ReferenceSources(embedder, source)


@dataclass(frozen=True)
class Retrieved:
    """What a turn looked up."""

    prompt: str | None
    """The prompt section carrying the references or recalled passages, if any."""
    memories_prompt: str | None = None
    """The prompt section carrying the user's memories relevant to the turn, if any."""
    recalled: bool = False
    """Whether the recall-story tool already ran, so the chat model need not call it."""
    judged: Judged | None = None
    """What the turn does to her affinity, asked about it; None if not or if it could not
    be told."""
    photo: bool = False
    """Whether the user asks her for a photo, asked about it; no if it could not be told."""
    query_vector: list[float] | None = None
    """The turn's query embedded, for writing down (`MemoryTurn.write_down`); None if it
    was not by the time the turn knew what it needed, or could not be."""


@dataclass(frozen=True)
class _Found:
    """What a turn finds before it knows what it needs: its query embedded, the candidate
    references and the candidate memories."""

    query_vector: list[float]
    references: list[DocumentPassage] | None
    """None if searching the character's documents failed."""
    memories: list[Memory]


class Retrieval:
    def __init__(
        self,
        judge: RetrievalJudge | None,
        sources: ReferenceSources,
        reranker: Reranker | None,
        min_relevance: Callable[[], float],
    ) -> None:
        """`min_relevance` says, whenever asked, the reranker's score below which a
        reference or recalled passage is left out (see `rerank.KNOWN_THRESHOLDS`); the
        admin console may change it while the backend runs."""
        self._judge = judge
        self._sources = sources
        self._reranker = reranker
        self._min_relevance = min_relevance

    async def retrieve(
        self,
        character: Character,
        history: Sequence[Message],
        text: str,
        memory: MemoryTurn | None = None,
        affinity: bool = False,
        photo: bool = False,
        days: Days | None = None,
        recalling: Callable[[], None] = lambda: None,
    ) -> Retrieved:
        """Look up what this turn needs, finding the user's memories through `memory`, and
        telling `recalling` as it begins recalling the story for her (GLOSSARY.md「查看」);
        and judge what it does to her affinity, in her `days` if she is in them, and whether
        it asks her for a photo, if asked to."""
        if self._judge is None:
            return Retrieved(None)  # Explicit recall_story remains available.
        query = memory_query(history, text)
        embedding = asyncio.ensure_future(self._embed(query))
        finding = asyncio.ensure_future(self._find(character, embedding, memory))
        looked_up = False
        try:
            judged, asked = None, False
            try:
                need, judged, asked = await self._judge.judge(
                    character, history, text, affinity, photo, days
                )
            except JudgeError:
                log.warning("retrieval judge failed; retrieving anyway", exc_info=True)
                need = "references"
            if need == "nothing":
                retrieved = Retrieved(None)
            else:
                looked_up = True
                if need == "recall":
                    recalling()
                retrieved = await self._look_up(text, query, await finding, memory, need)
        finally:
            for task in (finding, embedding):  # needing nothing, or no longer anything at all
                task.cancel()
                if not looked_up:  # nor will anyone else see what it failed with
                    task.add_done_callback(_log_failure)
        return replace(
            retrieved, judged=judged, photo=asked, query_vector=_query_vector(embedding)
        )

    async def _embed(self, query: str) -> list[float] | None:
        """The turn's query embedded; None if it cannot be."""
        try:
            return await self._sources.embedder.embed_query(query)
        except EmbeddingError:
            log.warning("embedding the turn failed; replying without references or memories",
                        exc_info=True)
            return None

    async def _find(
        self,
        character: Character,
        embedding: "asyncio.Future[list[float] | None]",
        memory: MemoryTurn | None,
    ) -> _Found | None:
        """The candidates for the turn's query, once `embedding` it is done; None if it
        cannot be embedded."""
        if (query_vector := await embedding) is None:
            return None
        references, memories = await asyncio.gather(
            self._candidates(character, query_vector), _memory_candidates(memory, query_vector)
        )
        return _Found(query_vector, references, memories)

    async def _candidates(
        self, character: Character, query_vector: Sequence[float]
    ) -> list[DocumentPassage] | None:
        try:
            return await self._sources.candidates(query_vector, character)
        except EmbeddingError:
            log.warning("searching the references failed; replying without them", exc_info=True)
            return None

    async def _look_up(
        self,
        text: str,
        query: str,
        found: _Found | None,
        memory: MemoryTurn | None,
        need: Need,
    ) -> Retrieved:
        """What the turn `need`s (something) of what it found for `query`, `text` and her
        reply before it."""
        if need == "recall":
            return Retrieved(await self._recall_turn(text, query, found), recalled=True)
        if found is None:
            return Retrieved(None)
        if need == "memories":
            return Retrieved(None, await _find_memories(memory, query, found.memories))
        references, memories = await asyncio.gather(
            self._references(query, found.references or []),
            _find_memories(memory, query, found.memories),
        )
        return Retrieved(self._sources.prompt(references) if references else None, memories)

    async def _references(self, query: str, candidates: Sequence[DocumentPassage]) -> list[DocumentPassage]:
        """Those of the `candidates` relevant to `query`, most relevant first."""
        if self._reranker is None:
            return sorted(candidates, key=lambda r: -r.similarity)[:FALLBACK_REFERENCES]
        try:
            ranked = await self._sources.rerank(self._reranker, query, candidates)
        except RerankError:
            log.warning("reranking the references failed; replying with the nearest",
                        exc_info=True)
            return sorted(candidates, key=lambda r: -r.similarity)[:FALLBACK_REFERENCES]
        min_relevance = self._min_relevance()
        return [r for r, score in ranked if score >= min_relevance][:MAX_REFERENCES]

    async def recall_story(self, character: Character, query: str) -> str:
        """Look up the character's document passages for the recall tool."""
        try:
            vector = await self._sources.embedder.embed_query(query)
            candidates = await self._sources.candidates(vector, character)
        except EmbeddingError:
            log.warning("recall failed", exc_info=True)
            return _CANNOT_RECALL
        return await self._recall(query, query, candidates)

    async def _recall_turn(
        self, text: str, query: str, found: _Found | None
    ) -> str:
        if found is None or found.references is None:
            return _CANNOT_RECALL
        return await self._recall(text, query, found.references)

    async def _recall(
        self, asked: str, query: str, candidates: Sequence[DocumentPassage]
    ) -> str:
        if self._reranker is None:
            selected = sorted(candidates, key=lambda r: -r.similarity)[:1]
        else:
            try:
                ranked = await self._sources.rerank(self._reranker, query, candidates)
            except RerankError:
                log.warning("reranking the recall failed; recalling the nearest", exc_info=True)
                selected = sorted(candidates, key=lambda r: -r.similarity)[:1]
            else:
                selected = [r for r, score in ranked if score >= self._min_relevance()][:RECALL_PASSAGES]
        if not selected:
            return f"没有想起和「{asked}」有关的记录：{_NOT_IN_STORY}，或者向用户询问细节。"
        return f"# 回顾资料：{asked}\n" + self._sources.prompt(selected)


def _query_vector(embedding: "asyncio.Future[list[float] | None]") -> list[float] | None:
    """The turn's query embedded, if it was by the time `embedding` was let go of."""
    if not embedding.done() or embedding.cancelled() or embedding.exception() is not None:
        return None
    return embedding.result()


def _log_failure(task: "asyncio.Future[Any]") -> None:
    """Log what looking a turn up failed with that no one awaited."""
    if not task.cancelled() and (error := task.exception()) is not None:
        log.warning("looking the turn up failed", exc_info=error)


async def _memory_candidates(
    memory: MemoryTurn | None, query_vector: Sequence[float]
) -> list[Memory]:
    return await memory.candidates(query_vector) if memory else []


async def _find_memories(
    memory: MemoryTurn | None, query: str, candidates: Sequence[Memory]
) -> str | None:
    return await memory.find(query, candidates) if memory else None


_JUDGE_QUESTION = {
    "type": "noul",
    "instructions": "角色按用户提供的人设与用户对话。可查找的内容是已提供的背景资料、"
    "角色设定和相关经历。回答用户最新的一句话，是否需要查找这些内容？",
    "criteria": {
        "true": "需要回忆过去的具体经历、提到具体的人物或事件、需要确认角色设定或背景资料细节",
        "false": "只是寒暄、闲聊、情绪回应，或只凭上文就能回答",
    },
}
_RECALL_QUESTION = {
    "type": "noul",
    "instructions": "用户最新的一句话，是不是在问角色过去某一次具体经历的来龙去脉"
    "（例如「那次……是怎么回事」「还记得……那次吗」），需要回想那段经历的完整经过才能回答？",
    "criteria": {
        "true": "问的是过去某一次具体的事情、活动、工作或比赛的经过和当时的心情",
        "false": "寒暄闲聊、问喜好或设定、问身边人物近况，或者只是顺口提到过去",
    },
}
_ABOUT_PRODUCER_QUESTION = {
    "type": "noul",
    "instructions": "角色按用户提供的人设与用户对话。用户最新的一句话，是否说起或问起用户自己的事"
    "（生活、近况、工作安排、计划、家人、宠物、喜好、身体状况等），而用户以前对自己创建的角色"
    "说过的相关的事可能有助于回应？",
    "criteria": {
        "true": "说起或问起用户自己的生活、近况、计划、家人宠物、喜好，或提到以前对角色说过的事",
        "false": "只是打招呼、说角色自己的事、问背景资料或角色设定，与用户自己的生活无关",
    },
}
_QUESTIONS = {
    "needs_retrieval": _JUDGE_QUESTION,
    "recall": _RECALL_QUESTION,
    "about_producer": _ABOUT_PRODUCER_QUESTION,
}


def judge_questions(
    affinity: bool = False, photo: bool = False, days: Days | None = None
) -> dict[str, dict]:
    """What the judge model is asked of a turn: retrieval's three questions, affinity's in
    the same request if `affinity`, the considerate question with them in her `days`, and
    whether it asks for a photo if `photo`."""
    return (
        _QUESTIONS
        | (affinity_questions(days) if affinity else {})
        | (PHOTO_QUESTIONS if photo else {})
    )


@dataclass(frozen=True)
class RetrievalAnswer:
    """The judge model's probability of yes to each of its three questions."""

    needs_retrieval: float
    recall: float
    about_producer: float


class ModelRetrievalJudge:
    """The judge model, asked three yes-or-no questions (`noul`) about the turn in one
    request: whether it needs looking anything up, whether it asks how a past episode
    went, and whether it is about the user's own life. Each answer is yes at or above the
    model's threshold for it."""

    def __init__(
        self,
        judge_model: JudgeModel,
        thresholds: JudgeThresholds = JUDGE_THRESHOLDS[FALLBACK_FAMILY],
    ) -> None:
        self._judge_model = judge_model
        self.thresholds = thresholds

    async def judge(
        self,
        character: Character,
        history: Sequence[Message],
        text: str,
        affinity: bool = False,
        photo: bool = False,
        days: Days | None = None,
    ) -> tuple[Need, Judged | None, bool]:
        """As `RetrievalJudge.judge`, affinity's questions and the photo's asked in the same
        request."""
        answers = await self._judge_model.ask(
            turn_state(character, history, text), judge_questions(affinity, photo, days)
        )
        need = self.decide(_answer(answers))
        judged = None
        if affinity:
            try:
                judged = read_judged(answers, self.thresholds, days)
            except JudgeError:
                log.warning("affinity judge's answers could not be read", exc_info=True)
        asked = False
        if photo:
            try:
                asked = read_asked(answers, self.thresholds)
            except JudgeError:
                log.warning("the photo question's answer could not be read", exc_info=True)
        return need, judged, asked

    async def ask(
        self, character: Character, history: Sequence[Message], text: str, affinity: bool = False
    ) -> RetrievalAnswer:
        """How likely the judge model finds yes to each question about `text`, affinity's
        questions asked in the same request if `affinity`."""
        return _answer(await self._judge_model.ask(
            turn_state(character, history, text), judge_questions(affinity)
        ))

    def decide(self, answer: RetrievalAnswer) -> Need:
        """What a turn so answered needs: recall first, then references, then memories."""
        if answer.recall >= self.thresholds.recall:
            return "recall"
        if answer.needs_retrieval >= self.thresholds.needs_retrieval:
            return "references"
        if answer.about_producer >= self.thresholds.about_producer:
            return "memories"
        return "nothing"


def _answer(answers: dict) -> RetrievalAnswer:
    """The probabilities of yes `answers` give each of the three questions."""
    try:
        return RetrievalAnswer(
            float(answers["needs_retrieval"]["noul"]),
            float(answers["recall"]["noul"]),
            float(answers["about_producer"]["noul"]),
        )
    except (ValueError, KeyError, TypeError) as e:
        raise JudgeError("判断模型的返回无法解析（缺少回答）") from e
