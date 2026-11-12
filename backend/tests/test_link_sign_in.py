"""Linking sign-in methods: a signed-in user can link their other identity, and then
signing in with either is the same user. An identity that is someone else's cannot be
linked, and the last way to sign in cannot be unlinked. Signing out everywhere ends every
session of the user's."""

import httpx

from tests.conftest import (
    ClientFactory,
    agree_to_terms,
    character_id,
    github_identity,
    google_identity,
    sign_in_with,
)
from tests.fakes import FakeIdentityProvider, FakeLLM
from tests.test_text_turn import start_conversation


async def github_user(
    make_client: ClientFactory, github: FakeIdentityProvider, subject: str = "1001"
) -> httpx.AsyncClient:
    """A client signed in with GitHub as a user who has agreed to the terms."""
    client = make_client(FakeLLM(), user=None)
    await sign_in_with(client, github, github_identity(subject))
    await agree_to_terms(client)
    return client


async def methods(client: httpx.AsyncClient) -> list[tuple[str, str]]:
    res = await client.get("/api/account")
    assert res.status_code == 200, res.text
    return [(m["provider"], m["display_name"]) for m in res.json()["sign_in_methods"]]


async def conversations(client: httpx.AsyncClient, character: str = "mano") -> list[str]:
    res = await client.get("/api/conversations", params={"character_id": character})
    return [c["id"] for c in res.json()]


async def test_after_linking_either_identity_signs_in_as_the_same_user(
    make_client: ClientFactory, github: FakeIdentityProvider, google: FakeIdentityProvider
):
    client = await github_user(make_client, github)
    conversation_id = await start_conversation(client)

    res = await sign_in_with(client, google, google_identity(name="Producer G"), link=True)

    assert res.headers["location"] == "/settings/sign-in?linked=google"
    assert await methods(client) == [("github", "producer"), ("google", "Producer G")]
    phone = make_client(FakeLLM(), user=None)
    await sign_in_with(phone, google, google_identity())
    assert await conversations(phone) == [conversation_id]


async def test_an_identity_that_is_someone_elses_cannot_be_linked(
    make_client: ClientFactory, github: FakeIdentityProvider, google: FakeIdentityProvider
):
    theirs = make_client(FakeLLM(), user=None)
    await sign_in_with(theirs, google, google_identity())
    await agree_to_terms(theirs)
    their_conversation = await start_conversation(theirs, character_id("mano", "Producer"))
    mine = await github_user(make_client, github)

    res = await sign_in_with(mine, google, google_identity(), link=True)

    assert res.headers["location"] == "/settings/sign-in?error=taken"
    assert await methods(mine) == [("github", "producer")]
    again = make_client(FakeLLM(), user=None)
    await sign_in_with(again, google, google_identity())
    assert await conversations(again, character_id("mano", "Producer")) == [their_conversation]


async def test_linking_an_identity_already_yours_changes_nothing(
    make_client: ClientFactory, github: FakeIdentityProvider
):
    client = await github_user(make_client, github)

    res = await sign_in_with(client, github, github_identity(), link=True)

    assert res.headers["location"] == "/settings/sign-in?linked=github"
    assert await methods(client) == [("github", "producer")]


async def test_a_second_identity_at_the_same_provider_cannot_be_linked(
    make_client: ClientFactory, github: FakeIdentityProvider
):
    client = await github_user(make_client, github)

    res = await sign_in_with(client, github, github_identity("2002", "alt"), link=True)

    assert res.headers["location"] == "/settings/sign-in?error=already_linked"
    assert await methods(client) == [("github", "producer")]


async def test_linking_checks_the_identity_as_signing_in_does(
    make_client: ClientFactory, github: FakeIdentityProvider, google: FakeIdentityProvider
):
    client = await github_user(make_client, github)

    res = await sign_in_with(client, google, google_identity(verified=False), link=True)

    assert res.headers["location"] == "/settings/sign-in?error=email_unverified"
    assert await methods(client) == [("github", "producer")]


async def test_linking_needs_a_signed_in_user(
    make_client: ClientFactory, github: FakeIdentityProvider
):
    client = make_client(FakeLLM(), user=None)

    res = await client.get("/api/auth/github/start", params={"link": "1"})

    assert res.status_code == 302
    assert res.headers["location"] == "/login"


async def test_a_link_finished_after_signing_out_links_nothing(
    make_client: ClientFactory, github: FakeIdentityProvider, google: FakeIdentityProvider
):
    client = await github_user(make_client, github)
    start = await client.get("/api/auth/google/start", params={"link": "1"})
    state = httpx.URL(start.headers["location"]).params["state"]
    await client.post("/api/auth/logout")
    code = google.will_identify(google_identity())

    res = await client.get("/api/auth/google/callback", params={"code": code, "state": state})

    assert res.headers["location"] == "/login?error=state"


async def test_unlinking_one_of_two_identities_stops_it_signing_in_as_you(
    make_client: ClientFactory, github: FakeIdentityProvider, google: FakeIdentityProvider
):
    client = await github_user(make_client, github)
    await start_conversation(client)
    await sign_in_with(client, google, google_identity(), link=True)

    res = await client.delete("/api/account/sign-in-methods/google")

    assert res.status_code == 204
    assert await methods(client) == [("github", "producer")]
    stranger = make_client(FakeLLM(), user=None)
    await sign_in_with(stranger, google, google_identity())  # a new user now
    await agree_to_terms(stranger)
    assert await conversations(stranger, character_id("mano", "Producer")) == []


async def test_the_last_way_to_sign_in_cannot_be_unlinked(
    make_client: ClientFactory, github: FakeIdentityProvider
):
    client = await github_user(make_client, github)

    last = await client.delete("/api/account/sign-in-methods/github")
    missing = await client.delete("/api/account/sign-in-methods/google")

    assert last.status_code == 409
    assert "唯一的登录方式" in last.json()["detail"]
    assert missing.status_code == 404
    assert await methods(client) == [("github", "producer")]


async def test_signing_out_everywhere_ends_every_session_of_the_user(
    make_client: ClientFactory,
):
    desktop = make_client(FakeLLM())
    phone = make_client(FakeLLM())
    friend = make_client(FakeLLM(), "friend")

    res = await desktop.post("/api/account/logout-everywhere")

    assert res.status_code == 204
    for client in (desktop, phone):
        listed = await client.get("/api/conversations", params={"character_id": "mano"})
        assert listed.status_code == 401
    assert (await friend.get(
        "/api/conversations", params={"character_id": character_id("mano", "friend")}
    )).status_code == 200
