"""Split call nodes keep media ownership and admission shared, never user keys."""

import json
import asyncio
from dataclasses import replace
from pathlib import Path
from typing import cast

from tests.browser import Browser, open_browser
from tests.conftest import ClientFactory
from tests.fakes import FakeLLM
from tests.test_service_status import backend_of
from tests.test_text_turn import start_conversation
from eidolon.config import UsageLimits

import pytest
import httpx

from eidolon.call_nodes import CallNodes
from tests.conftest import SITE

from eidolon.config import Settings


def test_split_mode_requires_shared_postgres(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("EIDOLON_ROLE", "api")
    monkeypatch.setenv("EIDOLON_CALL_NODES", '{"voice-a":"http://127.0.0.1:8101"}')
    with pytest.raises(RuntimeError, match="PostgreSQL"):
        Settings.from_env()


@pytest.mark.parametrize("nodes", [
    {"../other": "http://127.0.0.1:8101"},
    {"voice-a": "http://user:password@127.0.0.1:8101"},
    {"voice-a": "http://127.0.0.1:8101/other"},
    {"voice-a": "http://127.0.0.1:8101?other=yes"},
    {"voice-a": "file:///tmp/voice"},
])
def test_split_mode_refuses_unsafe_node_map(monkeypatch: pytest.MonkeyPatch, nodes: dict):
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused/db")
    monkeypatch.setenv("EIDOLON_ROLE", "api")
    monkeypatch.setenv("EIDOLON_CALL_NODES", json.dumps(nodes))
    with pytest.raises(RuntimeError, match="EIDOLON_CALL_NODES"):
        Settings.from_env()


def test_calls_process_must_name_a_configured_node(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused/db")
    monkeypatch.setenv("EIDOLON_ROLE", "calls")
    monkeypatch.setenv("EIDOLON_CALL_NODES", '{"voice-a":"http://127.0.0.1:8101"}')
    monkeypatch.setenv("EIDOLON_CALL_NODE_ID", "voice-b")
    with pytest.raises(RuntimeError, match="EIDOLON_CALL_NODE_ID"):
        Settings.from_env()


async def test_api_does_not_host_media_and_requires_a_live_node(
    postgres_url: str, settings: Settings, make_client: ClientFactory, browser: Browser,
):
    config = replace(settings, database_path=cast(Path, postgres_url), role="api",
                     call_nodes={"a": "http://127.0.0.1:8101"})
    api = make_client(FakeLLM(), settings=config)
    conversation = await start_conversation(api)
    setup = await api.get("/api/ice-servers", params={"conversation": conversation})
    assert setup.status_code == 503
    refused = await browser.call(api, conversation_id=conversation)
    assert refused.status_code == 503
    assert backend_of(api).calls.in_progress == 0


async def test_nodes_share_capacity_replacement_and_character_deletion(
    postgres_url: str, settings: Settings, make_client: ClientFactory, browser: Browser,
):
    config = replace(settings, database_path=cast(Path, postgres_url), role="api",
                     call_nodes={"a": "http://127.0.0.1:8101", "b": "http://127.0.0.1:8102"},
                     usage_limits=UsageLimits(concurrent_calls=1))
    api = make_client(FakeLLM(), settings=config)
    a = make_client(FakeLLM(), settings=replace(config, role="calls", call_node_id="a"))
    b = make_client(FakeLLM(), settings=replace(config, role="calls", call_node_id="b"))
    await backend_of(a).calls.open()
    await backend_of(b).calls.open()
    await backend_of(api).config.save("limits", {"call_minutes": 2})
    created = await api.post("/api/characters", json={"name": "私有角色", "sheet": "简短回答", "voice_id": "custom-voice"})
    assert created.status_code == 201
    character = created.json()["id"]
    conversation = await start_conversation(api, character)
    setup = await api.get("/api/ice-servers", params={"conversation": conversation})
    assert setup.status_code == 200
    assert setup.json()["offerEndpoint"] == "/api/call-nodes/a/offer"
    assert setup.json()["maxCallSeconds"] == 120
    assert (await browser.call(a, conversation_id=conversation)).status_code == 200
    await browser.connect()
    assert backend_of(a).config.usage_limits.call_minutes == 2
    assert (await api.get("/api/admin/calls/live")).json() == {"in_progress": 1}
    other = make_client(FakeLLM(), user="other", settings=config)
    other_conversation = await start_conversation(other, "mano-other")
    full = await other.get("/api/ice-servers", params={"conversation": other_conversation})
    assert full.status_code == 503
    assert full.json()["code"] == "calls_busy"
    async with open_browser() as again:
        replacing = asyncio.create_task(again.call(b, conversation_id=conversation))
        await browser.hung_up()
        assert (await replacing).status_code == 200
        await again.connect()
        async with httpx.AsyncClient(transport=b._transport, cookies=other.cookies, headers=SITE, base_url="http://test") as stranger:
            wrong_owner = await stranger.patch("/api/offer", json={"pc_id": again.pc_id, "candidates": []})
        assert wrong_owner.status_code == 404
        deleted = await api.delete(f"/api/characters/{character}")
        assert deleted.status_code == 204
        await again.hung_up()
    assert backend_of(a).calls.in_progress == 0
    assert backend_of(b).calls.in_progress == 0
    assert (await api.get("/api/ice-servers", params={"conversation": conversation})).status_code == 404


async def test_deleted_character_cannot_start_after_waiting_to_reserve(
    postgres_url: str, settings: Settings, make_client: ClientFactory,
    browser: Browser, monkeypatch: pytest.MonkeyPatch,
):
    config = replace(settings, database_path=cast(Path, postgres_url), role="calls", call_node_id="a",
                     call_nodes={"a": "http://127.0.0.1:8101"})
    node = make_client(FakeLLM(), settings=config)
    api = make_client(FakeLLM(), settings=replace(config, role="api", call_node_id=None))
    await backend_of(node).calls.open()
    conversation = await start_conversation(api)
    reached, resume = asyncio.Event(), asyncio.Event()
    reserve = CallNodes.reserve

    async def held_reserve(self, *args):
        reached.set()
        await resume.wait()
        return await reserve(self, *args)

    monkeypatch.setattr(CallNodes, "reserve", held_reserve)
    placing = asyncio.create_task(browser.call(node, conversation_id=conversation))
    try:
        await asyncio.wait_for(reached.wait(), 5)
        assert (await api.delete("/api/characters/mano")).status_code == 204
    finally:
        resume.set()
    assert (await placing).status_code == 404
    assert backend_of(node).calls.in_progress == 0


async def test_reservation_after_heartbeat_read_is_not_mistaken_for_lost_ownership(
    postgres_url: str, settings: Settings, make_client: ClientFactory,
    browser: Browser, monkeypatch: pytest.MonkeyPatch,
):
    config = replace(settings, database_path=cast(Path, postgres_url), role="calls", call_node_id="a",
                     call_nodes={"a": "http://127.0.0.1:8101"})
    node = make_client(FakeLLM(), settings=config)
    read, resume = asyncio.Event(), asyncio.Event()
    heartbeat = CallNodes.heartbeat

    async def held_heartbeat(self):
        controls = await heartbeat(self)
        if not read.is_set():
            read.set()
            await resume.wait()
        return controls

    monkeypatch.setattr(CallNodes, "heartbeat", held_heartbeat)
    await backend_of(node).calls.open()
    await asyncio.wait_for(read.wait(), 5)
    conversation = await start_conversation(node)
    try:
        assert (await browser.call(node, conversation_id=conversation)).status_code == 200
    finally:
        resume.set()
    await browser.connect()
    patch = await node.patch("/api/offer", json={"pc_id": browser.pc_id, "candidates": []})
    assert patch.status_code == 200
    await backend_of(node).database.write(lambda db: db.execute("UPDATE call_nodes SET expires_at = 0"))
    await browser.hung_up()
    async def settled():
        while backend_of(node).calls.in_progress:
            await asyncio.sleep(0.01)
    await asyncio.wait_for(settled(), 5)
    assert backend_of(node).calls.in_progress == 0
    unavailable = await node.get("/api/ice-servers", params={"conversation": conversation})
    assert unavailable.status_code == 503


async def test_remote_end_during_activation_rejects_offer(
    postgres_url: str, settings: Settings, make_client: ClientFactory,
    browser: Browser, monkeypatch: pytest.MonkeyPatch,
):
    config = replace(settings, database_path=cast(Path, postgres_url), role="calls",
                     call_node_id="a", call_nodes={"a": "http://127.0.0.1:8101"})
    node = make_client(FakeLLM(), settings=config)
    backend = backend_of(node)
    conversation = await start_conversation(node)
    activated, delivered = asyncio.Event(), asyncio.Event()
    activate, heartbeat = CallNodes.activated, CallNodes.heartbeat
    remote = CallNodes(backend.database, ("a",), None, backend.clock)

    async def held_activation(self, call_id):
        accepted = await activate(self, call_id)
        activated.set()
        await delivered.wait()
        return accepted

    async def observed_heartbeat(self):
        controls = await heartbeat(self)
        if any(control.ended_for for control in controls):
            delivered.set()
        return controls

    monkeypatch.setattr(CallNodes, "activated", held_activation)
    monkeypatch.setattr(CallNodes, "heartbeat", observed_heartbeat)
    await backend.calls.open()
    placing = asyncio.create_task(browser.call(node, conversation_id=conversation))
    try:
        await asyncio.wait_for(activated.wait(), 5)
        await remote.end(conversation, "fed_up")
        assert (await asyncio.wait_for(placing, 5)).status_code == 500
    finally:
        delivered.set()
        await asyncio.gather(placing, return_exceptions=True)
