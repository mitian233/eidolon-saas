"""How many calls there may be at once: each user one at a time, a new one, let through,
hanging up the one they had, and all users together as many as the limits say
(`UsageLimits.concurrent_calls`). A call is under way from being placed until it is over;
one refused is refused before anything is asked of it, both as the browser asks what it
needs to call and as it places the call."""

import asyncio
from dataclasses import replace
from typing import Any

import httpx
import pytest

from eidolon.assembly import Backend
from eidolon.config import Settings, UsageLimits
from tests.browser import TIMEOUT, Browser, open_browser, until_gone
from eidolon.sessions import SESSION_COOKIE
from tests.conftest import COOKIE_DOMAIN, SITE, ClientFactory, aside, character_id, seed_characters
from tests.fakes import FakeLLM, registry_of
from tests.test_service_status import backend_of
from tests.test_text_turn import start_conversation

BUSY = "现在打电话的人太多，稍后再试"


@pytest.fixture
def one_call_at_once(settings: Settings) -> Settings:
    return replace(settings, usage_limits=UsageLimits(concurrent_calls=1))


def another_user(client: httpx.AsyncClient, name: str) -> httpx.AsyncClient:
    """A client on the same backend as `client`, signed in as the user named `name`, who
    owns the registry's characters under their own ids (`character_id`)."""
    backend: Backend = client._transport.app.state.backend  # pyright: ignore[reportAttributeAccessIssue]

    async def signed_in() -> httpx.Cookies:
        now = backend.clock()
        user = await backend.store.first_user_named(name) or await backend.store.create_user(name)
        if user.consented_at is None:
            await backend.store.consent(user.id, now)
        await seed_characters(backend, user.id, registry_of(backend), suffix=f"-{name}")
        cookies = httpx.Cookies()
        cookies.set(SESSION_COOKIE, await backend.store.create_session(user.id, now), domain=COOKIE_DOMAIN)
        return cookies

    return httpx.AsyncClient(
        transport=client._transport,
        base_url="http://test",
        headers=SITE,
        cookies=aside(signed_in()),
    )


async def test_a_users_new_call_hangs_up_the_one_they_had(
    make_client: ClientFactory, one_call_at_once: Settings, browser: Browser
):
    """Theirs is not counted against the calls at once: it is hung up as the new one is
    let through."""
    client = make_client(FakeLLM(), settings=one_call_at_once)
    conversation_id = await start_conversation(client)
    await browser.call(client, conversation_id=conversation_id)
    await browser.connect()

    async with open_browser() as again:
        asked = await client.get("/api/ice-servers", params={"conversation": conversation_id})
        placed = await again.call(client, conversation_id=conversation_id)
        await browser.hung_up()
        await again.connect()

    assert asked.status_code == 200
    assert placed.status_code == 200


async def test_a_call_placed_while_the_users_last_is_still_being_placed_is_refused(
    make_client: ClientFactory, monkeypatch: pytest.MonkeyPatch
):
    client = make_client(FakeLLM())
    conversation_id = await start_conversation(client)
    admissions = backend_of(client).admissions
    let_in = admissions.call
    letting_in, may_go_on = asyncio.Event(), asyncio.Event()

    async def call(*args: Any) -> Any:
        """The first call is held being placed, until it may go on."""
        if not letting_in.is_set():
            letting_in.set()
            await may_go_on.wait()
        return await let_in(*args)

    monkeypatch.setattr(admissions, "call", call)
    async with open_browser() as a, open_browser() as b:
        placing = asyncio.create_task(a.call(client, conversation_id=conversation_id))
        await asyncio.wait_for(letting_in.wait(), TIMEOUT)
        refused = await b.call(client, conversation_id=conversation_id)
        may_go_on.set()
        placed = await placing

    assert (placed.status_code, refused.status_code) == (200, 409)
    assert "还在拨" in refused.json()["detail"]


async def test_calls_at_once_are_limited_across_users(
    make_client: ClientFactory, one_call_at_once: Settings, browser: Browser
):
    client = make_client(FakeLLM(), settings=one_call_at_once)
    await browser.call(client, conversation_id=await start_conversation(client))
    await browser.connect()
    assert browser.pc_id is not None

    async with another_user(client, "hazuki") as other:
        theirs = await start_conversation(other, character_id("mano", "hazuki"))
        asked = await other.get("/api/ice-servers", params={"conversation": theirs})
        async with open_browser() as second:
            refused = await second.call(other, conversation_id=theirs)
        await browser.hang_up()
        await until_gone(client, browser.pc_id)
        async with open_browser() as again:
            after = await again.call(other, conversation_id=theirs)

    assert asked.status_code == 503
    assert asked.json() == {"detail": BUSY, "code": "calls_busy"}
    assert refused.status_code == 503
    assert refused.json() == {"detail": BUSY, "code": "calls_busy"}
    assert after.status_code == 200


async def test_a_call_counts_from_being_placed(
    make_client: ClientFactory, one_call_at_once: Settings
):
    """Two placed at the same moment: the one placed first holds the place while it is let
    through and answered, before it is served."""
    client = make_client(FakeLLM(), settings=one_call_at_once)
    mine = await start_conversation(client)
    async with another_user(client, "hazuki") as other, open_browser() as a, open_browser() as b:
        theirs = await start_conversation(other, character_id("mano", "hazuki"))
        placed = await asyncio.gather(
            a.call(client, conversation_id=mine), b.call(other, conversation_id=theirs)
        )

    assert sorted(res.status_code for res in placed) == [200, 503]
