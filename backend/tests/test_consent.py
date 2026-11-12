"""Agreeing to the privacy policy and terms of use: a new user can do nothing but agree,
sign out or delete their data until they have agreed and said they are at least 13."""

import sqlite3

import httpx
import pytest

from eidolon.config import Settings
from eidolon.sessions import CONSENT_REQUIRED
from tests.conftest import ClientFactory, github_identity, sign_in_with
from tests.fakes import FakeIdentityProvider, FakeLLM
from tests.test_text_turn import send_turn

REPLY = ["<ja>はいっ</ja><zh>好的</zh>"]


async def newcomer(make_client: ClientFactory, github: FakeIdentityProvider) -> httpx.AsyncClient:
    client = make_client(FakeLLM(REPLY), user=None)
    await sign_in_with(client, github, github_identity())
    return client


async def test_until_they_agree_new_users_are_sent_to_agree_first(
    make_client: ClientFactory, github: FakeIdentityProvider
):
    client = await newcomer(make_client, github)

    for res in [
        await client.post("/api/conversations", json={"character_id": "mano"}),
        await client.get("/api/conversations", params={"character_id": "mano"}),
        await client.post("/api/conversations/any/turns", json={"text": "在吗"}),
        await client.get("/api/profile"),
        await client.get("/api/memories"),
        await client.get("/api/characters/mano/affinity"),
        await client.get("/api/ice-servers"),
        await client.get("/api/account"),
    ]:
        assert res.status_code == CONSENT_REQUIRED
        assert "同意" in res.json()["detail"]


async def test_once_they_agree_they_can_talk(
    make_client: ClientFactory, github: FakeIdentityProvider, settings: Settings
):
    client = await newcomer(make_client, github)

    res = await client.post(
        "/api/account/consent", json={"agree_to_terms": True, "at_least_13": True}
    )

    assert res.status_code == 204
    created = await client.post("/api/conversations", json={"character_id": "mano"})
    events = await send_turn(client, created.json()["id"], "在吗")
    assert events[-1]["type"] == "done"
    with sqlite3.connect(settings.database_path) as db:
        [(consented_at,)] = db.execute("SELECT consented_at FROM users").fetchall()
    assert consented_at is not None  # when they agreed is kept


@pytest.mark.parametrize(
    "consent",
    [
        {"agree_to_terms": False, "at_least_13": True},
        {"agree_to_terms": True, "at_least_13": False},
        {"agree_to_terms": True},
    ],
    ids=["disagrees", "under 13", "age not said"],
)
async def test_agreeing_needs_both_the_terms_and_the_age(
    make_client: ClientFactory, github: FakeIdentityProvider, consent: dict
):
    client = await newcomer(make_client, github)

    res = await client.post("/api/account/consent", json=consent)

    assert res.status_code == 422
    still = await client.get("/api/conversations", params={"character_id": "mano"})
    assert still.status_code == CONSENT_REQUIRED


async def test_they_can_sign_out_without_agreeing(
    make_client: ClientFactory, github: FakeIdentityProvider
):
    client = await newcomer(make_client, github)

    assert (await client.post("/api/auth/logout")).status_code == 204

    res = await client.get("/api/conversations", params={"character_id": "mano"})
    assert res.status_code == 401


async def test_agreeing_needs_a_session(make_client: ClientFactory):
    client = make_client(FakeLLM(), user=None)

    res = await client.post(
        "/api/account/consent", json={"agree_to_terms": True, "at_least_13": True}
    )

    assert res.status_code == 401
