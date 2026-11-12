"""OpenAI-compatible text embeddings for user-supplied endpoints.

Queries hold up a turn and get a short deadline and one retry. Documents are given
longer. Stored model identifiers include dimensions so incompatible vectors cannot mix.
"""

import hashlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
import numpy as np

from eidolon.billing import bill
from eidolon.config import EmbeddingSettings
from eidolon.retry import TURN_TIMEOUT, ServiceError, answered, retry_once, transient_status

EMBEDDING_TIMEOUT = httpx.Timeout(120, connect=10)

_REQUEST_BATCH = 16


@dataclass(frozen=True)
class Document:
    """Text to embed for the index, with where it comes from: an episode's card or event and
    title for a story passage, a fact's headings for a character fact, None for a memory."""

    text: str
    title: str | None = None


class Embedder(Protocol):
    model: str
    """Vectors from different models are not comparable; the index keeps them apart by this."""

    async def embed_documents(self, documents: Sequence[Document]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...


class Reembeddable(Protocol):
    """What `eidolon reembed` embeds again after the embedding service, model or dimensions
    change (ADR-0005): the story corpus, the character facts, the work facts and the
    memories, each embedding with the embedder it was opened with."""

    @property
    def label(self) -> str:
        """What it is called in `eidolon reembed`'s log and report."""
        ...

    @property
    def unit(self) -> str:
        """What its count is counted in."""
        ...

    async def embed_missing(self, batch: int, progress: Callable[[int], None]) -> int:
        """Embed whatever has no vector from its embedder yet, `batch` at a time, each
        committed, telling `progress` the count so far as it goes; returns how many it
        embedded."""
        ...

    async def forget_other_models(self) -> int:
        """Drop the vectors not from its embedder; returns how many there were."""
        ...


class ClosableEmbedder(Embedder, Protocol):
    async def aclose(self) -> None: ...


class EmbeddingError(ServiceError):
    pass


class NoEmbedder:
    """For reading the story corpus without searching it or adding to it."""

    model = "none"

    async def embed_documents(self, documents: Sequence[Document]) -> list[list[float]]:
        raise EmbeddingError("没有配置向量化服务")

    async def embed_query(self, text: str) -> list[float]:
        raise EmbeddingError("没有配置向量化服务")


class OpenAIEmbedder:
    """An OpenAI-compatible `/embeddings` endpoint, without provider-specific prefixes."""

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str,
        client: httpx.AsyncClient | None = None,
        query_timeout: float = TURN_TIMEOUT,
        dimensions: int | None = None,
    ) -> None:
        endpoint = hashlib.sha256(base_url.rstrip("/").encode()).hexdigest()[:20]
        self.model = f"{endpoint}/{model}@{dimensions}" if dimensions is not None else f"{endpoint}/{model}"
        self._model = model
        self._dimensions = dimensions
        self._url = base_url.rstrip("/") + "/embeddings"
        self._api_key = api_key
        self._client = client or httpx.AsyncClient(timeout=EMBEDDING_TIMEOUT)
        self._query_timeout = query_timeout

    async def embed_documents(self, documents: Sequence[Document]) -> list[list[float]]:
        texts = [d.text for d in documents]
        vectors: list[list[float]] = []
        for start in range(0, len(texts), _REQUEST_BATCH):
            vectors.extend(await self._embed(texts[start : start + _REQUEST_BATCH]))
        return vectors

    async def embed_query(self, text: str) -> list[float]:
        texts = [text]
        return (await retry_once(lambda: self._embed(texts, self._query_timeout)))[0]

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _embed(
        self, texts: Sequence[str], timeout: float | None = None
    ) -> list[list[float]]:
        """The vectors of `texts`, asked for in one request given `timeout` seconds if not
        None, or else as long as the client gives any."""
        body: dict[str, Any] = {
            "model": self._model, "input": list(texts), "encoding_format": "float",
        }
        if self._dimensions is not None:
            body["dimensions"] = self._dimensions
        res = await _post(
            self._client,
            timeout,
            self._url,
            json=body,
            headers={"Authorization": f"Bearer {self._api_key}"},
        )
        if res.status_code >= 400:
            raise EmbeddingError(
                f"向量化服务返回 {res.status_code}: {res.text[:500]}",
                transient=transient_status(res.status_code),
            )
        try:
            body = res.json()
            data = sorted(body["data"], key=lambda d: d["index"])
        except (ValueError, KeyError, TypeError) as e:
            raise EmbeddingError(f"向量化服务的返回无法解析（{len(res.text)} 字）") from e
        if len(data) != len(texts):
            raise EmbeddingError(f"向量化服务返回了 {len(data)} 个向量，应为 {len(texts)} 个")
        usage = body.get("usage")
        if isinstance(usage, dict) and isinstance(tokens := usage.get("total_tokens"), int):
            bill("tokens", tokens)
        return [d["embedding"] for d in data]


async def _post(
    client: httpx.AsyncClient, timeout: float | None, url: str, **request: Any
) -> httpx.Response:
    """The answer to a POST of `request` to `url`, given `timeout` seconds if not None.
    Raises EmbeddingError if it does not come."""
    async with answered("向量化服务", timeout, EmbeddingError):
        return await client.post(url, **request)




def open_embedder(
    settings: EmbeddingSettings, client: httpx.AsyncClient | None = None
) -> ClosableEmbedder:
    """Open the user's endpoint on a shared client, or a client owned by the caller."""
    return OpenAIEmbedder(
        settings.api_key, settings.model, settings.base_url, client,
        dimensions=settings.dimensions,
    )


def nearest(
    vectors: Sequence[bytes], query: Sequence[float], limit: int
) -> list[tuple[int, float]]:
    """Indexes of the stored `vectors` most similar to `query` by cosine similarity, best
    first, with their scores."""
    if not vectors:
        return []
    query_vector = np.asarray(query, dtype=np.float32)
    matrix = np.stack([np.frombuffer(v, dtype=np.float32) for v in vectors])
    scores = matrix @ query_vector / (
        np.linalg.norm(matrix, axis=1) * np.linalg.norm(query_vector) + 1e-12
    )
    return [(int(i), float(scores[i])) for i in np.argsort(-scores)[:limit]]


def unit_rows(vectors: Sequence[bytes]) -> np.ndarray:
    """The stored `vectors` as the rows of a matrix, each scaled to length 1, so that
    `nearest_rows` finds by cosine similarity what `nearest` does, without working out
    their lengths again each time. Read-only."""
    if not vectors:
        return np.empty((0, 0), dtype=np.float32)
    matrix = np.stack([np.frombuffer(v, dtype=np.float32) for v in vectors])
    matrix /= np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-12
    matrix.flags.writeable = False  # searched on many threads at once
    return matrix


def nearest_rows(
    matrix: np.ndarray, query: Sequence[float], limit: int, rows: np.ndarray | None = None
) -> list[tuple[int, float]]:
    """Like `nearest`, among the rows of a `unit_rows` matrix, or only those of it at
    `rows`: their indexes (among `rows`, if given) and scores, best first."""
    among = matrix if rows is None else matrix[rows]
    if not len(among):
        return []
    query_vector = np.asarray(query, dtype=np.float32)
    scores = among @ (query_vector / (np.linalg.norm(query_vector) + 1e-12))
    return [(int(i), float(scores[i])) for i in np.argsort(-scores)[:limit]]


def to_blob(vector: Sequence[float]) -> bytes:
    """A vector as stored in SQLite."""
    return np.asarray(vector, dtype=np.float32).tobytes()
