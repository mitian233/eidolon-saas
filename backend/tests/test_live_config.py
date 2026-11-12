"""The live configuration: admins change the deployer's chat model in the admin console
(ADR-0013). A change is tried before it is kept, then plays the next turn and the next
call, while calls already connected keep the model they connected with; it overrides
`.env` until restored, and one that no longer works when the server starts falls back to
`.env`, marked as such. The clients are made by a fake `ServiceClients`."""

import asyncio
import sqlite3
from collections.abc import Callable
from contextlib import closing
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import httpx
import pytest

from eidolon.activity import ActivityLog
from eidolon.assembly import Backend
from eidolon.config import LLMSettings, Settings
from eidolon.data_access import Database
from eidolon.live_config import LiveConfig
from tests.browser import open_browser, until_gone
from tests.conftest import ClientFactory, agree_to_terms, github_identity, sign_in_with
from tests.fakes import (
    DEPLOYER_KEY,
    FakeClock,
    FakeIdentityProvider,
    FakeLLM,
    FakeServiceClients,
    FakeSpeech,
)

CONFIG = "/api/admin/config"
CHAT_LLM = "/api/admin/config/chat_llm"
REPLY = ["<ja>はいっ</ja><zh>好的</zh>"]

NEW_KEY = "sk-new-key-5678"
NEW = {
    "protocol": "anthropic",
    "base_url": "https://llm.example/v1",
    "model": "new-model",
    "max_tokens": 1024,
    "reasoning_effort": "high",
    "extra_body": {"top_k": 5},
    "call_reasoning_effort": "low",
    "api_key": NEW_KEY,
}
NEW_SETTINGS = LLMSettings(
    "https://llm.example/v1", NEW_KEY, "new-model", "anthropic", 1024, "high", {"top_k": 5}
)
NEW_FOLLOWED = LLMSettings("https://llm.example/v1", NEW_KEY, "new-model", "anthropic")
"""The memory model following the chat model NEW: where it is and which alone."""
NEW_SHOWN = {k: v for k, v in NEW.items() if k != "api_key"} | {"api_key_last4": "5678"}
ENV_SETTINGS = LLMSettings("http://llm.invalid/v1", DEPLOYER_KEY, "test-model")
ENV_SHOWN = {
    "protocol": "chat-completions",
    "base_url": "http://llm.invalid/v1",
    "model": "test-model",
    "max_tokens": None,
    "reasoning_effort": None,
    "extra_body": None,
    "call_reasoning_effort": None,
    "api_key_last4": DEPLOYER_KEY[-4:],
}


@pytest.fixture
def admins(settings: Settings) -> Settings:
    return replace(settings, admins=frozenset({("github", "1001")}))


async def admin_client(
    make_client: ClientFactory,
    settings: Settings,
    github: FakeIdentityProvider,
    clients: FakeServiceClients,
) -> httpx.AsyncClient:
    """A client signed in as the admin, on a backend whose chat models `clients` makes."""
    client = make_client(clients.llm, user=None, settings=settings, clients=clients)
    await sign_in_with(client, github, github_identity("1001"))
    await agree_to_terms(client)
    return client


def recorded(client: httpx.AsyncClient, service: str) -> list[tuple[str, str, bool]]:
    """The service calls to `service` recorded so far, by provider, model and whether on
    the user's own key, sorted."""
    backend: Backend = client._transport.app.state.backend  # pyright: ignore[reportAttributeAccessIssue]
    with closing(sqlite3.connect(backend.settings.database_path)) as db:
        calls = db.execute(
            "SELECT provider, model, own_key FROM service_calls WHERE service = ? AND at > ?",
            (service, (backend.clock() - timedelta(days=1)).timestamp()),
        ).fetchall()
    return sorted((provider, model, bool(own)) for provider, model, own in calls)


async def until(done: Callable[[], object]) -> None:
    """Wait, a while at most, for `done` to come true, as what a call let go of closes."""
    for _ in range(100):
        if done():
            return
        await asyncio.sleep(0.02)


async def start(client: httpx.AsyncClient) -> None:
    """What the server does as it starts, before serving anyone."""
    backend: Backend = client._transport.app.state.backend  # pyright: ignore[reportAttributeAccessIssue]
    await backend.start()


async def test_admin_config_has_no_platform_credentials(
    make_client: ClientFactory, admins: Settings, github: FakeIdentityProvider
):
    client = await admin_client(make_client, admins, github, FakeServiceClients())
    response = await client.get(CONFIG)
    assert response.status_code == 200
    config = response.json()
    for name in ("chat_llm", "memory_llm", "tts", "stt", "image", "gpt_image", "judge", "qweather"):
        assert name not in config
    for field in ("siliconflow_api_key", "gemini_api_key", "jev_api_key", "cloudflare_api_token"):
        assert field not in response.text.lower()
    assert config["limits"]["effective"]["turns_per_hour"] == admins.usage_limits.turns_per_hour
    assert config["affinity"]["effective"]["enabled"] == admins.affinity_and_gifts
    assert (await client.put(CHAT_LLM, json=NEW)).status_code == 404











# The chat model's two reasoning efforts: text turns go at one, calls' turns at the other.

async def call_turn(client: httpx.AsyncClient, speech: FakeSpeech, conversation_id: str) -> None:
    """One turn of a call placed and hung up on the conversation."""
    async with open_browser() as browser:
        await browser.call(client, conversation_id=conversation_id)
        await browser.connect()
        await speech.stts[-1].hear("早上好")
        await browser.turn()
        await browser.close()
        assert browser.pc_id is not None
        await until_gone(client, browser.pc_id)





























async def test_no_one_but_admins_finds_the_configuration(
    make_client: ClientFactory, admins: Settings
):
    producer = make_client(FakeLLM(), settings=admins)
    nobody = make_client(FakeLLM(), user=None, settings=admins)

    for client in (producer, nobody):
        assert (await client.get(CONFIG)).status_code == 404
        assert (await client.put(CHAT_LLM, json=NEW)).status_code == 404
        assert (await client.delete(CHAT_LLM)).status_code == 404


async def test_a_zero_key_deployment_starts_without_models(tmp_path: Path):
    """The platform configures no models: the live configuration starts, leases none,
    and makes no clients; the admin console may still set a model later."""
    settings = Settings(database_path=tmp_path / "eidolon.db")
    db = Database(settings.database_path)
    clients = FakeServiceClients()
    config = LiveConfig(
        settings, clients, FakeClock(), db=db, activity=ActivityLog(db, FakeClock())
    )
    try:
        assert config.chat_model is None and config.memory_llm is None
        assert not config.has_service("chat_llm") and not config.has_service("memory_llm")
        lease = config.lease()
        assert lease.keys.chat_llm is None and lease.keys.memory_llm is None
        lease.release()
        assert clients.opened == []
    finally:
        await config.aclose()
        await db.close()
