"""Invite links (GLOSSARY.md「邀请链接」「注册方式」): while only those invited may sign up, a
new identity signs up only through an invite link an admin made, but an admin's and the
deployment's first user; users who already are sign in as ever. A link is used up, expires
or is deleted; who signed up through it is kept as long as both are. Driven through the API
with the providers faked."""

from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import cast
from unittest.mock import ANY
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from eidolon.config import Settings
from tests.conftest import ClientFactory, agree_to_terms, github_identity, sign_in_with
from tests.fakes import START, FakeClock, FakeIdentityProvider, FakeLLM
from tests.test_admin_users import ADMIN, admin_beside, admin_client
from tests.test_sign_in import signed_in

INVITES = "/api/admin/invites"


@pytest.fixture
def settings(settings: Settings, database_target: Path | str) -> Settings:
    return replace(
        settings, database_path=cast(Path, database_target), dev_login=False,
        admins=frozenset({ADMIN}), registration="invite",
    )


def code_of(link: str) -> str:
    [code] = parse_qs(urlsplit(link).query)["invite"]
    return code


async def invite(admin: httpx.AsyncClient, **made) -> dict:
    res = await admin.post(INVITES, json=made)
    assert res.status_code == 201, res.text
    return res.json()


async def invites(admin: httpx.AsyncClient) -> list[dict]:
    res = await admin.get(INVITES)
    assert res.status_code == 200, res.text
    return res.json()["invites"]


async def test_while_only_those_invited_may_sign_up_new_identities_need_an_invite_link(
    make_client: ClientFactory, github: FakeIdentityProvider, settings: Settings,
):
    first = make_client(FakeLLM(), user=None, settings=replace(settings, registration="open"))
    stranger = make_client(FakeLLM(), user=None)
    returning = make_client(FakeLLM(), user=None)
    before_first_signup = await sign_in_with(stranger, github, github_identity("2002", "stranger"))
    assert before_first_signup.headers["location"] == "/login?error=not_invited"
    assert not await signed_in(stranger)

    first_signed_up = await sign_in_with(first, github, github_identity("1001"))
    turned_away = await sign_in_with(stranger, github, github_identity("2002", "stranger"))
    admin = await admin_client(make_client, github)
    signed_in_again = await sign_in_with(returning, github, github_identity("1001"))

    assert first_signed_up.headers["location"] == "/conversations"
    assert await signed_in(first)
    assert turned_away.headers["location"] == "/login?error=not_invited"
    assert not await signed_in(stranger)
    assert (await admin.get("/api/admin")).status_code == 200
    assert (await admin.get("/api/admin/users")).json()["total"] == 2
    assert signed_in_again.headers["location"] == "/conversations"
    assert await signed_in(returning)


async def test_first_user_can_find_their_admin_identity_if_no_admins_are_set(
    make_client: ClientFactory, github: FakeIdentityProvider, settings: Settings,
):
    unset = replace(settings, admins=frozenset())
    first = make_client(FakeLLM(), user=None, settings=unset)
    second = make_client(FakeLLM(), user=None, settings=unset)

    signed_up = await sign_in_with(first, github, github_identity("1001"))
    refused = await sign_in_with(second, github, github_identity("1002"))

    assert signed_up.headers["location"] == "/conversations"
    assert await signed_in(first)
    assert (await first.get(INVITES)).status_code == 404
    assert refused.headers["location"] == "/login?error=not_invited"
    assert not await signed_in(second)


async def test_an_invite_link_signs_up_as_many_as_it_may_be_used_for_and_says_whom(
    make_client: ClientFactory, github: FakeIdentityProvider
):
    admin = await admin_client(make_client, github)
    made = await invite(admin, note="群里", max_uses=2, lifetime_days=None)
    code = code_of(made["link"])

    too_new = await sign_in_with(
        make_client(FakeLLM(), user=None), github,
        github_identity("1000", created_at=START - timedelta(days=30)), invite=code,
    )
    # As a chat app may stick the full stop after it onto the link.
    visitor = make_client(FakeLLM(), user=None)
    friend = await sign_in_with(
        visitor, github, github_identity("1001", "friend"),
        invite=f"{code}。",
    )
    second = await sign_in_with(
        make_client(FakeLLM(), user=None), github, github_identity("1002", "second"), invite=code
    )
    third = await sign_in_with(
        make_client(FakeLLM(), user=None), github, github_identity("1003", "third"), invite=code
    )
    friend_again = await sign_in_with(
        make_client(FakeLLM(), user=None), github, github_identity("1001", "friend"), invite=code
    )

    assert made["link"] == f"http://localhost:3000/login?invite={code}"
    assert too_new.headers["location"] == "/login?error=too_new"
    assert friend.headers["location"] == "/conversations"
    assert await signed_in(visitor)
    await agree_to_terms(visitor)
    assert (await visitor.get(INVITES)).status_code == 404
    assert (await visitor.post(INVITES, json={})).status_code == 404
    assert (await visitor.delete(f"{INVITES}/{made['id']}")).status_code == 404
    assert second.headers["location"] == "/conversations"
    assert third.headers["location"] == "/login?error=invite_invalid"
    assert friend_again.headers["location"] == "/conversations"
    admin_returning = make_client(FakeLLM(), user=None)
    admin_login = await sign_in_with(admin_returning, github, github_identity(ADMIN[1]))
    assert admin_login.headers["location"] == "/conversations"
    assert (await admin_returning.get(INVITES)).status_code == 200
    assert await invites(admin) == [{
        "id": made["id"], "link": made["link"], "note": "群里", "max_uses": 2, "used": 2,
        "expires_at": None, "created_at": made["created_at"], "state": "used_up",
        "invited": [{"id": ANY, "name": "friend"}, {"id": ANY, "name": "second"}],
    }]
    friend_id, second_id = (i["id"] for i in (await invites(admin))[0]["invited"])
    shown = (await admin.get(f"/api/admin/users/{friend_id}")).json()
    assert shown["invite"] == {"id": made["id"], "note": "群里"}

    assert (await admin.delete(f"/api/admin/users/{second_id}")).status_code == 204
    [after] = await invites(admin)
    assert (after["used"], after["invited"]) == (2, [{"id": friend_id, "name": "friend"}])

    assert (await admin.delete(f"{INVITES}/{made['id']}")).status_code == 204
    assert await invites(admin) == []
    assert (await admin.get(f"/api/admin/users/{friend_id}")).json()["invite"] is None
    assert (await admin.delete(f"{INVITES}/{made['id']}")).status_code == 404


async def test_an_invite_link_cannot_be_used_once_it_has_expired_or_is_deleted(
    make_client: ClientFactory, github: FakeIdentityProvider
):
    clock = FakeClock()
    admin = await admin_client(make_client, github, clock=clock)
    for_a_day = await invite(admin, lifetime_days=1)
    kept = await invite(admin)
    clock.advance(days=1)
    assert (await admin.delete(f"{INVITES}/{kept['id']}")).status_code == 204

    expired = await sign_in_with(
        make_client(FakeLLM(), user=None, clock=clock), github, github_identity("1001"),
        invite=code_of(for_a_day["link"]),
    )
    deleted = await sign_in_with(
        make_client(FakeLLM(), user=None, clock=clock), github, github_identity("1001"),
        invite=code_of(kept["link"]),
    )

    assert (for_a_day["state"], for_a_day["expires_at"]) == (
        "usable", (START + timedelta(days=1)).isoformat()
    )
    assert expired.headers["location"] == "/login?error=invite_invalid"
    assert deleted.headers["location"] == "/login?error=invite_invalid"
    assert [(i["id"], i["state"]) for i in await invites(admin)] == [(for_a_day["id"], "expired")]


async def test_once_the_admin_console_lets_anyone_sign_up_an_invite_link_is_not_used(
    make_client: ClientFactory, github: FakeIdentityProvider
):
    stranger = make_client(FakeLLM(), user=None)
    async with admin_beside(stranger, github) as admin:
        made = await invite(admin)
        opened = await admin.put("/api/admin/config/registration", json={"mode": "open"})

        res = await sign_in_with(
            stranger, github, github_identity("2002", "stranger"), invite=code_of(made["link"])
        )

        assert opened.status_code == 200, opened.text
        assert opened.json()["registration"]["effective"] == {"mode": "open"}
        assert res.headers["location"] == "/conversations"
        [shown] = await invites(admin)
        assert (shown["used"], shown["invited"]) == (0, [])
