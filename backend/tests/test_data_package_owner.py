"""Data packages keep characters private (D13): a package tells only the exporting user's
own character names, and an import adds only references to the importing user's own
characters — another owner's are skipped, telling neither that they exist nor their name."""

import asyncio
import io
import sqlite3
import zipfile
from collections.abc import AsyncIterator
from dataclasses import replace
from pathlib import Path
from threading import Event
from typing import cast

import httpx
import pytest
from PIL import Image

from eidolon.config import Settings
from eidolon.database import delete_conversation_data
from eidolon.data_package import PackagedConversation
from tests.conftest import ClientFactory, agree_to_terms
from tests.fakes import FakeBackgroundLLM, FakeEmbedder, FakeJudge, FakeLLM
from tests.test_data_package import (
    EXPORT_CHECK, MANIFEST, PACKAGED_PROFILE, PROFILE_PACKAGE, export, import_package,
    package_of, unzipped,
)
from tests.test_data_package_conversations import conversations_package, packaged_conversation
from tests.test_service_status import backend_of
from tests.test_shared_memory import CAT, memorized
from tests.test_text_turn import send_turn, start_conversation


@pytest.fixture
def package_settings(settings: Settings, database_target: Path | str) -> Settings:
    return replace(settings, database_path=cast(Path, database_target))


async def log_in(client: httpx.AsyncClient, name: str) -> str:
    response = await client.post("/api/auth/dev-login", json={"name": name})
    assert response.status_code == 204, response.text
    await agree_to_terms(client)
    return (await client.get("/api/account")).json()["id"]


async def create_character(client: httpx.AsyncClient, name: str) -> str:
    response = await client.post("/api/characters", json={"name": name, "sheet": "你是山间向导。"})
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def test_package_uses_current_owned_characters_and_restores_a_single_language_turn(
    package_settings: Settings, make_client: ClientFactory,
):
    writer = make_client(
        FakeLLM(["山路", "向左。"]), None, settings=package_settings,
        background_llm=FakeBackgroundLLM(memorized(CAT)), retrieval_judge=FakeJudge(),
        embedder=FakeEmbedder(),
    )
    reader = make_client(FakeLLM(), None, settings=package_settings)
    stranger = make_client(FakeLLM(), None, settings=package_settings)
    owner_id = await log_in(writer, "alice")
    await log_in(reader, "alice")
    await log_in(stranger, "bob")
    await backend_of(reader).character_repository.load()

    character_id = await create_character(writer, "向导")
    stranger_id = await create_character(stranger, "另一位用户的向导")
    conversation_id = await start_conversation(writer, character_id)
    assert (await send_turn(writer, conversation_id, "往哪走？"))[-1]["type"] == "done"
    assert len((await writer.get("/api/memories")).json()) == 1
    assert (await writer.put(f"/api/characters/{character_id}", json={
        "name": "山间向导", "sheet": "你是山间向导。",
    })).status_code == 200
    assert (await writer.put("/api/profile", json={"form_of_address": "旅人"})).status_code == 200

    # Older data may still reference a foreign character. The package must not reveal its name,
    # and the importing owner must match the character ID independently of the package's name.
    db = backend_of(writer).database
    await backend_of(writer).store.create_conversation(owner_id, stranger_id)
    package = await export(reader, "conversations,memories,profile")
    _, manifest, data = unzipped(package)
    assert manifest["format"] == 5
    own, foreign = data["conversations"]
    assert own["character_name"] == "山间向导"
    assert foreign["character_name"] is None
    assert [m["role"] for m in own["messages"]] == ["user", "character"]
    reply = own["messages"][-1]
    assert (reply["ja"], reply["zh"], reply["segments"]) == (
        "山路向左。", "", [{"ja": "山路向左。", "zh": ""}],
    )
    [memory] = data["memories"]
    assert memory["text"] == CAT and memory["source_character_name"] == "山间向导"
    assert memory["conversation"] == conversation_id

    await db.write(delete_conversation_data, conversation_id)
    assert (await writer.delete("/api/memories")).status_code == 204
    assert (await writer.put("/api/profile", json={"form_of_address": "访客"})).status_code == 200
    restored = await import_package(reader, package, "conversations,memories,profile")
    assert restored.status_code == 200, restored.text
    assert restored.json()["conversations"] == 1
    assert restored.json()["memories"] == 1 and restored.json()["profile"]
    assert restored.json()["skipped"] == [{"character_name": stranger_id, "conversations": 1}]
    again = await import_package(writer, package, "conversations,memories,profile")
    assert again.status_code == 200, again.text
    assert not again.json()["conversations"] and not again.json()["memories"] and not again.json()["profile"]
    [conversation] = (await writer.get("/api/conversations", params={"character_id": character_id})).json()
    assert conversation["id"] != conversation_id
    messages = (await writer.get(f"/api/conversations/{conversation['id']}/messages")).json()
    assert messages[-1]["text"] == "山路向左。"
    _, _, restored_data = unzipped(await export(reader, "conversations,memories,profile"))
    [restored_memory] = restored_data["memories"]
    assert restored_memory["conversation"] == conversation["id"]
    assert restored_data["profile"]["form_of_address"] == "旅人"
    _, _, stranger_data = unzipped(await export(stranger, "conversations,memories,profile"))
    assert stranger_data["conversations"] == []
    assert stranger_data["memories"] == []
    assert stranger_data["profile"]["form_of_address"] is None
    result = await import_package(stranger, package, "conversations")
    assert result.status_code == 200, result.text
    assert result.json()["skipped"] == [{"character_name": "山间向导", "conversations": 1}]
    assert (await stranger.get(f"/api/conversations/{conversation['id']}/messages")).status_code == 404


async def test_legacy_categories_are_read_but_not_applied_to_saas(
    package_settings: Settings, make_client: ClientFactory,
):
    client = make_client(FakeLLM(), None, settings=package_settings)
    await log_in(client, "alice")
    character_id = await create_character(client, "向导")
    manifest = MANIFEST | {
        "format": 5, "categories": ["conversations", "photos", "profile", "cycles", "letters"],
        "counts": {"conversations": 1, "photos": 1, "profile": 1, "cycles": 1, "letters": 1},
    }
    cycle = {"character_id": character_id, "first_day": "2025-01-01", "days": 4}
    conversation = packaged_conversation("1", "2025-01-01", character=(character_id, "向导"))
    at = conversation["created_at"]
    conversation["messages"][1]["photo"] = {
        "id": "mountain", "tag": "view", "status": "ready", "reason": None,
        "created_at": at, "updated_at": at,
    }
    letter = {
        "character_id": character_id, "character_name": "向导", "occasions": ["anniversary"],
        "day": "2025-01-01", "written_at": at, "salutation": "旅人",
        "paragraphs": [{"ja": "こんにちは", "zh": "你好"}],
    }
    data = {"conversations": [conversation], "profile": PACKAGED_PROFILE, "cycles": [cycle], "letters": [letter]}
    include = "conversations,photos,profile,cycles,letters"
    picture = io.BytesIO()
    with Image.new("RGB", (1, 1)) as image:
        image.save(picture, "WEBP")

    def zipped(manifest: dict, data: dict, photo: bytes) -> bytes:
        package = io.BytesIO(package_of(manifest, data))
        with zipfile.ZipFile(package, "a") as archive:
            archive.writestr("photos/mountain.webp", photo)
        return package.getvalue()

    webp = picture.getvalue()
    broken = {
        "extra cycle key": zipped(manifest, data | {"cycles": [cycle | {"extra": True}]}, webp),
        "letter before version 5": zipped(manifest | {"format": 4}, data, webp),
        "broken picture": zipped(manifest, data, b"not a webp"),
    }
    for case, package in broken.items():
        bad = await import_package(client, package, include)
        assert (bad.status_code, bad.json().get("code")) == (422, "broken"), case
    assert (await client.get("/api/profile")).json()["form_of_address"] is None

    imported = await import_package(client, zipped(manifest, data, webp), include)
    assert imported.status_code == 200, imported.text
    result = imported.json()
    assert result["profile"] and result["conversations"] == 1
    assert [result[category] for category in ("photos", "cycles", "letters")] == [0, 0, 0]
    assert (await client.get("/api/profile")).json()["form_of_address"] == "小林"
    entries, exported, exported_data = unzipped(await export(
        client, "conversations,photos,memories,profile,cycles,letters",
    ))
    assert exported["categories"] == ["conversations", "memories", "profile"]
    assert [entry.filename for entry in entries] == ["manifest.json", "data.json"]
    [kept] = exported_data["conversations"]
    assert "photo" not in kept["messages"][1]


async def test_overlapping_packages_are_refused_across_api_instances(
    package_settings: Settings, make_client: ClientFactory,
):
    first = make_client(FakeLLM(), None, settings=package_settings)
    second = make_client(FakeLLM(), None, settings=package_settings)
    await log_in(first, "alice")
    await log_in(second, "alice")
    started, finish = asyncio.Event(), asyncio.Event()

    async def slowly() -> AsyncIterator[bytes]:
        yield PROFILE_PACKAGE[:10]
        started.set()
        await finish.wait()
        yield PROFILE_PACKAGE[10:]

    uploading = asyncio.create_task(first.post(
        "/api/account/data-package", params={"include": "profile"}, content=slowly(),
    ))
    try:
        async with asyncio.timeout(5):
            await started.wait()
            refused = await second.get(EXPORT_CHECK, params={"include": "profile"})
        assert refused.status_code == 409, refused.text
        assert refused.json()["code"] == "busy"
    finally:
        finish.set()
        assert (await uploading).status_code == 200


async def test_preparing_an_import_does_not_hold_up_another_users_write(
    package_settings: Settings, make_client: ClientFactory, monkeypatch: pytest.MonkeyPatch,
):
    alice = make_client(FakeLLM(), None, settings=package_settings)
    bob = make_client(FakeLLM(), None, settings=package_settings)
    await log_in(alice, "alice")
    await log_in(bob, "bob")
    character_id = await create_character(alice, "向导")
    package = conversations_package(packaged_conversation(
        "1", "2026-09-01", character=(character_id, "向导"),
    ))
    converting, finish = Event(), Event()
    whole = PackagedConversation.whole

    def wait_before_converting(conversation: PackagedConversation):
        converting.set()
        assert finish.wait(5)
        return whole(conversation)

    monkeypatch.setattr(PackagedConversation, "whole", wait_before_converting)
    importing = asyncio.create_task(import_package(alice, package, "conversations"))
    try:
        assert await asyncio.to_thread(converting.wait, 5)
        async with asyncio.timeout(2):
            saved = await bob.put("/api/profile", json={"form_of_address": "同行者"})
        assert saved.status_code == 200, saved.text
    finally:
        finish.set()
        imported = await importing
    assert imported.status_code == 200, imported.text
    assert imported.json()["conversations"] == 1


async def test_upload_finishing_after_user_deletion_leaves_no_import_record(
    package_settings: Settings, make_client: ClientFactory,
):
    first = make_client(FakeLLM(), None, settings=package_settings)
    second = make_client(FakeLLM(), None, settings=package_settings)
    user_id = await log_in(first, "alice")
    await log_in(second, "alice")
    started, finish = asyncio.Event(), asyncio.Event()

    async def slowly() -> AsyncIterator[bytes]:
        yield PROFILE_PACKAGE[:10]
        started.set()
        await finish.wait()
        yield PROFILE_PACKAGE[10:]

    uploading = asyncio.create_task(first.post("/api/account/data-package", content=slowly()))
    try:
        await asyncio.wait_for(started.wait(), 5)
        assert (await second.post("/api/account/delete", json={"confirm": True})).status_code == 204
    finally:
        finish.set()
        finished = await uploading
    assert finished.status_code == 401, finished.text

    def imports(conn: sqlite3.Connection) -> int:
        return conn.execute(
            "SELECT COUNT(*) FROM data_package_imports WHERE user_id = ?", (user_id,),
        ).fetchone()[0]

    assert await backend_of(second).database.read(imports) == 0