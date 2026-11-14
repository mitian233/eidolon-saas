"""Character-owned documents and their model-specific passage vectors."""

import asyncio
import sqlite3
import uuid
import weakref
from datetime import UTC, datetime
from collections.abc import Sequence

from eidolon.data_access import Database
from eidolon.document_text import normalize_text, passages, text_hash
from eidolon.embedding import Document, Embedder, nearest, to_blob
from eidolon.retrieval import DocumentPassage

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    character_id TEXT NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
    origin TEXT NOT NULL,
    text_hash TEXT NOT NULL,
    created_at TEXT,
    UNIQUE(character_id, text_hash)
);
CREATE TABLE IF NOT EXISTS document_passages (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    text TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS document_vectors (
    passage_id TEXT NOT NULL REFERENCES document_passages(id) ON DELETE CASCADE,
    model TEXT NOT NULL,
    dimensions INTEGER NOT NULL,
    embedding BLOB NOT NULL,
    PRIMARY KEY(passage_id, model, dimensions)
);
"""


class Documents:
    """Storage shared by sources; no credentials or embedder are retained."""

    def __init__(self, db: Database) -> None:
        self._db = db
        self._locks: weakref.WeakValueDictionary[tuple[str, str], asyncio.Lock] = weakref.WeakValueDictionary()
        db.prepare(_prepare)

    def _lock_for(self, character_id: str, model: str) -> asyncio.Lock:
        key = (character_id, model)
        lock = self._locks.get(key)
        if lock is None:
            lock = self._locks[key] = asyncio.Lock()
        return lock

    async def import_text(self, owner_id: str, character_id: str, origin: str, text: str,
                          embedder: Embedder, dimensions: int | None = None) -> str:
        """Save a document and embed missing passages; return its stable id.

        Raises ValueError if the character is not owned or the text is empty.
        Reimport keeps the first origin. A failed embedding leaves the text retryable.
        """
        text = normalize_text(text)
        if not text:
            raise ValueError("文档为空")
        async with self._lock_for(character_id, embedder.model):
            document_id = await self._db.write(_import, owner_id, character_id, origin, text)
            await self._embed_missing(character_id, embedder, dimensions)
            return document_id

    async def list(self, owner_id: str, character_id: str) -> list[dict]:
        return await self._db.read(_list, owner_id, character_id)

    async def delete(self, owner_id: str, character_id: str, document_id: str) -> bool:
        return await self._db.write(_delete, owner_id, character_id, document_id)

    def source(self, embedder: Embedder) -> "DocumentSource":
        return DocumentSource(self, embedder)

    async def _embed_missing(
        self, character_id: str, embedder: Embedder, dimensions: int | None = None
    ) -> None:
        rows = await self._db.read(_missing, character_id, embedder.model, dimensions)
        if not rows:
            return
        vectors = await embedder.embed_documents([Document(text) for _, text in rows])
        values = [(pid, embedder.model, len(vector), to_blob(vector))
                  for (pid, _), vector in zip(rows, vectors, strict=True)]
        if any(size == 0 or (dimensions is not None and size != dimensions)
               for _, _, size, _ in values):
            raise ValueError("文档向量维度与查询不匹配")
        await self._db.write(_save_vectors, values)


class DocumentSource:
    def __init__(self, documents: Documents, embedder: Embedder) -> None:
        self._documents = documents
        self._embedder = embedder

    async def search(self, query_vector: Sequence[float], character_id: str,
                     limit: int) -> list[DocumentPassage]:
        if not query_vector or limit <= 0:
            return []
        async with self._documents._lock_for(character_id, self._embedder.model):
            await self._documents._embed_missing(character_id, self._embedder, len(query_vector))
            rows = await self._documents._db.read(
                _vectors, character_id, self._embedder.model, len(query_vector)
            )
        return [DocumentPassage(rows[i][0], rows[i][1], score)
                for i, score in nearest([row[2] for row in rows], query_vector, limit)]


def _prepare(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(documents)")}
    if "created_at" not in columns:
        conn.execute("ALTER TABLE documents ADD COLUMN created_at TEXT")


def _list(conn: sqlite3.Connection, owner: str, character: str) -> list[dict]:
    rows = conn.execute(
        "SELECT d.id, d.origin, d.created_at, COUNT(p.id), "
        "SUM(CASE WHEN EXISTS (SELECT 1 FROM document_vectors v WHERE v.passage_id = p.id) "
        "THEN 1 ELSE 0 END) FROM documents d "
        "JOIN characters c ON c.id = d.character_id "
        "LEFT JOIN document_passages p ON p.document_id = d.id "
        "WHERE c.owner_id = ? AND c.id = ? GROUP BY d.id, d.origin, d.created_at "
        "ORDER BY d.created_at DESC, d.id", (owner, character),
    ).fetchall()
    return [{"id": row[0], "origin": row[1], "created_at": row[2],
             "passage_count": row[3], "embedded_passage_count": row[4] or 0} for row in rows]


def _import(conn: sqlite3.Connection, owner: str, character: str, origin: str, text: str) -> str:
    if not conn.execute("SELECT 1 FROM characters WHERE id = ? AND owner_id = ?",
                        (character, owner)).fetchone():
        raise ValueError("角色不存在")
    digest = text_hash(text)
    row = conn.execute("SELECT id FROM documents WHERE character_id = ? AND text_hash = ?",
                       (character, digest)).fetchone()
    if row:
        return row[0]
    document_id = uuid.uuid4().hex
    conn.execute("INSERT INTO documents (id, character_id, origin, text_hash, created_at) VALUES (?, ?, ?, ?, ?)",
                 (document_id, character, origin, digest, datetime.now(UTC).isoformat()))
    conn.executemany("INSERT INTO document_passages VALUES (?, ?, ?)",
                     [(uuid.uuid4().hex, document_id, part) for part in passages(text)])
    return document_id


def _delete(conn: sqlite3.Connection, owner: str, character: str, document_id: str) -> bool:
    return conn.execute(
        "DELETE FROM documents WHERE id = ? AND character_id = ? AND character_id IN "
        "(SELECT id FROM characters WHERE owner_id = ?)", (document_id, character, owner)
    ).rowcount > 0


def _missing(conn: sqlite3.Connection, character: str, model: str,
             dimensions: int | None) -> list[tuple[str, str]]:
    return conn.execute(
        "SELECT p.id, p.text FROM document_passages p JOIN documents d ON d.id = p.document_id "
        "WHERE d.character_id = ? AND NOT EXISTS "
        "(SELECT 1 FROM document_vectors v WHERE v.passage_id = p.id AND v.model = ? "
        "AND (? IS NULL OR v.dimensions = ?))",
        (character, model, dimensions, dimensions),
    ).fetchall()


def _save_vectors(conn: sqlite3.Connection, values: list[tuple[str, str, int, bytes]]) -> None:
    conn.executemany("INSERT INTO document_vectors SELECT ?, ?, ?, ? WHERE EXISTS "
                     "(SELECT 1 FROM document_passages WHERE id = ?) ON CONFLICT DO NOTHING",
                     [(pid, model, size, blob, pid) for pid, model, size, blob in values])


def _vectors(conn: sqlite3.Connection, character: str, model: str,
             dimensions: int) -> list[tuple[str, str, bytes]]:
    return conn.execute(
        "SELECT p.text, d.origin, v.embedding FROM document_vectors v "
        "JOIN document_passages p ON p.id = v.passage_id JOIN documents d ON d.id = p.document_id "
        "WHERE d.character_id = ? AND v.model = ? AND v.dimensions = ?",
        (character, model, dimensions),
    ).fetchall()
