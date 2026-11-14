"""Document persistence, isolation and retrieval on both databases."""

import pytest

from eidolon.character_repository import CharacterRepository
from eidolon.data_access import Database
from eidolon.documents import Documents
from eidolon.embedding import EmbeddingError
from eidolon.retrieval import Retrieval, open_reference_sources
from eidolon.store import Store
from tests.fakes import FakeEmbedder
from tests.test_character_document_retrieval import Judge


async def test_documents_persist_deduplicate_retrieve_and_delete(database_target):
    db = Database(database_target)
    try:
        store = Store(db)
        alice = await store.create_user("Alice")
        bob = await store.create_user("Bob")
        characters = CharacterRepository(db, {})
        one = await characters.create(alice.id, name="一", sheet="")
        two = await characters.create(bob.id, name="二", sheet="")
        documents = Documents(db)
        embedder = FakeEmbedder("model@13")
        doc = await documents.import_text(alice.id, one.id, "笔记", " 公園的猫 ", embedder)
        assert await documents.import_text(alice.id, one.id, "其他名称", "公園的猫", embedder) == doc
        assert embedder.documents == ["公園的猫"]
        with pytest.raises(ValueError):
            await documents.import_text(bob.id, one.id, "偷看", "猫", embedder)
        await documents.import_text(bob.id, two.id, "另一份", "公園的鳩", embedder)
        retrieval = Retrieval(Judge("references"), open_reference_sources(embedder, documents.source(embedder)), None, lambda: 0)
        result = await retrieval.retrieve(one, [], "公園的猫")
        assert result.prompt is not None and "公園的猫" in result.prompt
        assert "公園的鳩" not in result.prompt
        assert "公園的猫" in await retrieval.recall_story(one, "猫")
        new_model = FakeEmbedder("another@13")
        source = documents.source(new_model)
        assert (await source.search(await new_model.embed_query("猫"), one.id, 5))[0].text == "公園的猫"
        assert new_model.documents == ["公園的猫"]
        assert not await documents.delete(bob.id, one.id, doc)
        assert await documents.delete(alice.id, one.id, doc)
        assert await source.search(await new_model.embed_query("猫"), one.id, 5) == []
        assert await characters.delete(bob.id, two.id)
        assert await db.read(lambda conn: conn.execute("SELECT COUNT(*) FROM document_vectors").fetchone()[0]) == 0
    finally:
        await db.close()


async def test_failed_embedding_can_be_retried(tmp_path):
    db = Database(tmp_path / "test.db")
    try:
        owner = await Store(db).create_user("Alice")
        character = await CharacterRepository(db, {}).create(owner.id, name="一", sheet="")
        documents = Documents(db)
        embedder = FakeEmbedder()
        embedder.documents_down = True
        with pytest.raises(EmbeddingError):
            await documents.import_text(owner.id, character.id, "笔记", "猫", embedder)
        embedder.documents_down = False
        await documents.import_text(owner.id, character.id, "笔记", "猫", embedder)
        assert embedder.documents == ["猫"]
    finally:
        await db.close()


async def test_user_deletion_removes_documents(database_target):
    from eidolon.database import delete_user_data

    db = Database(database_target)
    try:
        user = await Store(db).create_user("Alice")
        character = await CharacterRepository(db, {}).create(user.id, name="一", sheet="")
        documents = Documents(db)
        await documents.import_text(user.id, character.id, "笔记", "猫", FakeEmbedder())
        await db.write(delete_user_data, user.id)
        for table in ("documents", "document_passages", "document_vectors"):
            assert await db.read(lambda conn: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]) == 0
    finally:
        await db.close()


async def test_changed_dimensions_do_not_reuse_vectors(tmp_path):
    class ShortEmbedder(FakeEmbedder):
        def _vector(self, text):
            return super()._vector(text)[:2]

    db = Database(tmp_path / "test.db")
    try:
        user = await Store(db).create_user("Alice")
        character = await CharacterRepository(db, {}).create(user.id, name="一", sheet="")
        documents = Documents(db)
        await documents.import_text(user.id, character.id, "笔记", "猫", FakeEmbedder("same"))
        shorter = ShortEmbedder("same")
        found = await documents.source(shorter).search(await shorter.embed_query("猫"), character.id, 5)
        assert [p.text for p in found] == ["猫"]
        assert shorter.documents == ["猫"]
    finally:
        await db.close()


async def test_document_list_migrates_existing_documents(database_target):
    db = Database(database_target)
    try:
        owner = await Store(db).create_user("Alice")
        character = await CharacterRepository(db, {}).create(owner.id, name="一", sheet="")
        db.prepare(lambda conn: conn.executescript("""
            CREATE TABLE documents (
                id TEXT PRIMARY KEY,
                character_id TEXT NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
                origin TEXT NOT NULL, text_hash TEXT NOT NULL,
                UNIQUE(character_id, text_hash)
            );
        """))
        await db.write(lambda conn: conn.execute(
            "INSERT INTO documents VALUES (?, ?, ?, ?)", ("old", character.id, "旧文档", "hash")
        ))
        documents = Documents(db)
        assert await documents.list(owner.id, character.id) == [{
            "id": "old", "origin": "旧文档", "created_at": None,
            "passage_count": 0, "embedded_passage_count": 0,
        }]
    finally:
        await db.close()
