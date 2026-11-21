"""Open a story corpus on a separate data access layer, as another process would."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from eidolon.corpus import StoryCorpus
from eidolon.data_access import Database
from eidolon.embedding import Embedder


@asynccontextmanager
async def corpus_in(database: Path, embedder: Embedder) -> AsyncIterator[StoryCorpus]:
    """The story corpus in the database at `database`, on a data access layer of its own,
    as another process has it."""
    db = Database(database)
    try:
        yield StoryCorpus(db, embedder)
    finally:
        await db.close()
