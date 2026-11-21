"""Moderation removes access immediately and removes only the selected account's data."""

import asyncio
from dataclasses import replace
from pathlib import Path
from typing import cast

import httpx
import pytest

import eidolon.call
from eidolon.call_nodes import CallNodes
from eidolon.config import Settings
from tests.browser import Browser
from tests.conftest import SITE, ClientFactory, sign_in_as
from tests.fakes import FakeBackgroundLLM, FakeEmbedder, FakeIdentityProvider, FakeJudge, FakeLLM, FakeReranker
from tests.test_admin_users import admin_beside
from tests.test_admin_users import settings  # noqa: F401
from tests.test_delete_account import REPLY, use_everything
from tests.test_service_status import backend_of
from tests.test_shared_memory import CAT, memorized
from tests.test_text_turn import start_conversation


@pytest.fixture
def moderation_settings(settings: Settings, database_target: Path | str) -> Settings:
    return replace(settings, database_path=cast(Path, database_target))


async def test_admin_ban_revokes_every_session_and_ends_the_call_before_periodic_poll(
    moderation_settings: Settings, make_client: ClientFactory, github: FakeIdentityProvider,
    browser: Browser, monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(eidolon.call, "USER_CHECK_INTERVAL", 60)
    user = make_client(FakeLLM(), settings=moderation_settings)
    phone = make_client(FakeLLM(), settings=moderation_settings)
    user_id = (await user.get("/api/account")).json()["id"]
    assert (await browser.call(user, conversation_id=await start_conversation(user))).status_code == 200
    await browser.connect()

    async with admin_beside(user, github) as admin:
        ban = f"/api/admin/users/{user_id}/ban"
        response = await admin.post(ban, json={"note": "已确认滥用"})
        assert response.status_code == 200, response.text
        for device in (user, phone):
            assert (await device.get("/api/account")).status_code == 401
        await asyncio.wait_for(browser.hung_up(), 3)

        assert (await admin.delete(ban)).status_code == 200
        assert (await phone.get("/api/account")).status_code == 401
        fresh = make_client(FakeLLM(), settings=moderation_settings)
        response = await fresh.get("/api/account")
        assert response.status_code == 200
        assert response.json()["id"] == user_id


async def test_admin_deletion_clears_the_accounts_data_but_keeps_other_users(
    moderation_settings: Settings, make_client: ClientFactory, github: FakeIdentityProvider, browser: Browser,
):
    split = isinstance(moderation_settings.database_path, str)
    config = replace(moderation_settings, role="api", call_nodes={"a": "http://127.0.0.1:8101"}) if split else moderation_settings
    user = make_client(
        FakeLLM(REPLY), settings=config, retrieval_judge=FakeJudge(), embedder=FakeEmbedder(),
        reranker=FakeReranker("制作人"), background_llm=FakeBackgroundLLM(memorized(CAT)),
    )
    phone = make_client(FakeLLM(), settings=config)
    other = make_client(FakeLLM(), user="friend", settings=config)
    voice = make_client(FakeLLM(), None, settings=replace(config, role="calls", call_node_id="a")) if split else user
    node = backend_of(voice)
    await node.calls.open()
    user_id = (await user.get("/api/account")).json()["id"]
    other_id = (await other.get("/api/account")).json()["id"]
    await node.documents.import_text(user_id, "mano", "被删资料", "猫", FakeEmbedder())
    await node.documents.import_text(other_id, "mano-friend", "留下资料", "狗", FakeEmbedder())

    await use_everything(user)
    [entry] = (await user.get("/api/conversations", params={"character_id": "mano"})).json()
    conversation = entry["id"]
    if not split:
        # A stale claim in a database now used in single-process mode must be removed too.
        prior = CallNodes(node.database, ("old",), "old", node.clock)
        await prior.start()
        await prior.reserve(user_id, "mano", conversation, None)

    async with (
        admin_beside(user, github) as admin,
        httpx.AsyncClient(transport=voice._transport, headers=SITE, base_url="http://test") as caller,
    ):
        sign_in_as(caller, user)
        assert (await browser.call(caller, conversation_id=conversation)).status_code == 200
        await browser.connect()
        queries = (
            ("SELECT COUNT(*) FROM characters WHERE owner_id = ?", user_id, 2, 0),
            ("SELECT COUNT(*) FROM documents WHERE character_id = ?", "mano", 1, 0),
            ("SELECT COUNT(*) FROM document_passages", None, 2, 1),
            ("SELECT COUNT(*) FROM document_vectors", None, 2, 1),
            ("SELECT COUNT(*) FROM active_calls WHERE user_id = ?", user_id, 1, 0),
            ("SELECT COUNT(*) FROM conversations WHERE user_id = ?", user_id, 1, 0),
            ("SELECT COUNT(*) FROM messages WHERE conversation_id = ?", conversation, 2, 0),
            ("SELECT COUNT(*) FROM memories WHERE user_id = ?", user_id, 1, 0),
            ("SELECT COUNT(*) FROM memory_vectors WHERE user_id = ?", user_id, 1, 0),
            ("SELECT COUNT(*) FROM producer_profiles WHERE user_id = ?", user_id, 1, 0),
            ("SELECT COUNT(*) FROM sessions WHERE user_id = ?", user_id, 2, 0),
        )

        async def counts() -> list[int]:
            return await node.database.read(lambda db: [
                db.execute(sql, (value,) if value else ()).fetchone()[0] for sql, value, *_ in queries
            ])

        assert await counts() == [before for _, _, before, _ in queries]
        response = await admin.delete(f"/api/admin/users/{user_id}")
        assert response.status_code == 204, response.text
        await browser.hung_up()
        assert await counts() == [after for _, _, _, after in queries]
        for device in (user, phone):
            assert (await device.get("/api/account")).status_code == 401
        assert (await admin.get(f"/api/admin/users/{user_id}")).status_code == 404
        assert (await other.get("/api/characters/mano-friend/documents")).json()[0]["origin"] == "留下资料"
