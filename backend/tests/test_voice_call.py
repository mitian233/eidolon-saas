"""Voice calls: signalling and ICE configuration, driven through the backend's external API."""

import base64
import hmac
from dataclasses import replace

import pytest

from eidolon.config import TURN_CREDENTIAL_LIFETIME, Settings, TurnSettings
from tests.browser import Browser
from tests.conftest import ClientFactory, character_id, sign_in_as
from tests.fakes import FakeClock, FakeLLM, FakeSpeech
from tests.test_text_turn import start_conversation


async def test_ice_servers_come_from_configuration(make_client: ClientFactory, settings: Settings):
    turn = {"urls": ["turn:turn.example.com:3478"], "username": "u", "credential": "p"}
    settings = replace(settings, ice_servers=[{"urls": ["stun:stun.example.com"]}, turn])
    client = make_client(FakeLLM(), settings=settings)

    res = await client.get("/api/ice-servers")

    assert res.status_code == 200
    assert res.json()["iceServers"] == [{"urls": ["stun:stun.example.com"]}, turn]


async def test_the_browser_learns_how_long_a_call_may_last_if_at_all_and_whether_it_counts(
    make_client: ClientFactory, settings: Settings
):
    """The call screen counts down the last minute, and says whether a dropped call counted."""
    limits = replace(settings.usage_limits, call_minutes=30)
    client = make_client(FakeLLM(), settings=replace(settings, usage_limits=limits))
    unlimited = replace(settings.usage_limits, call_minutes=None)
    without_limit = make_client(FakeLLM(), settings=replace(settings, usage_limits=unlimited))

    body = (await client.get("/api/ice-servers")).json()

    assert body["maxCallSeconds"] == 1800
    assert body["callExempt"] is False
    assert (await without_limit.get("/api/ice-servers")).json()["maxCallSeconds"] is None


def turn_password(secret: str, username: str) -> str:
    """What the TURN server expects under its shared-secret scheme (coturn's `use-auth-secret`)."""
    return base64.b64encode(hmac.new(secret.encode(), username.encode(), "sha1").digest()).decode()


async def test_turn_credentials_are_minted_from_the_shared_secret_for_each_request(
    make_client: ClientFactory, settings: Settings
):
    """The browser never sees the shared secret, only credentials that expire."""
    turn = TurnSettings(["turn:turn.example.com:3478", "turns:turn.example.com:5349"], "s3cret")
    settings = replace(settings, ice_servers=[{"urls": ["stun:stun.example.com"]}], turn=turn)
    clock = FakeClock()
    client = make_client(FakeLLM(), settings=settings, clock=clock)

    stun, minted = (await client.get("/api/ice-servers")).json()["iceServers"]

    assert stun == {"urls": ["stun:stun.example.com"]}
    assert minted["urls"] == ["turn:turn.example.com:3478", "turns:turn.example.com:5349"]
    expires, _, user = minted["username"].partition(":")
    assert int(expires) == int((clock.now + TURN_CREDENTIAL_LIFETIME).timestamp())
    assert user
    assert minted["credential"] == turn_password("s3cret", minted["username"])
    assert "s3cret" not in str(minted)

    clock.advance(hours=1)
    later = (await client.get("/api/ice-servers")).json()["iceServers"][1]
    assert int(later["username"].partition(":")[0]) == int(expires) + 3600


def test_turn_settings_come_from_the_environment(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("EIDOLON_TURN_URLS", raising=False)
    monkeypatch.delenv("EIDOLON_TURN_SECRET", raising=False)
    assert TurnSettings.from_env() is None

    monkeypatch.setenv(
        "EIDOLON_TURN_URLS", "turn:turn.example.com:3478, turn:turn.example.com:3478?transport=tcp"
    )
    monkeypatch.setenv("EIDOLON_TURN_SECRET", "s3cret")
    assert TurnSettings.from_env() == TurnSettings(
        ["turn:turn.example.com:3478", "turn:turn.example.com:3478?transport=tcp"], "s3cret"
    )

    monkeypatch.delenv("EIDOLON_TURN_SECRET")
    with pytest.raises(RuntimeError, match="EIDOLON_TURN_SECRET"):
        TurnSettings.from_env()


async def test_calling_needs_a_session(
    make_client: ClientFactory, speech: FakeSpeech, browser: Browser
):
    client = make_client(FakeLLM())
    conversation_id = await start_conversation(client)
    client.cookies.clear()

    assert (await client.get("/api/ice-servers")).status_code == 401
    res = await browser.call(client, conversation_id=conversation_id)

    assert res.status_code == 401
    assert speech.stts == []


async def test_call_into_someone_elses_or_a_missing_conversation_is_refused(
    make_client: ClientFactory, speech: FakeSpeech, browser: Browser
):
    theirs = await start_conversation(make_client(FakeLLM(), "stranger"), character_id("mano", "stranger"))
    client = make_client(FakeLLM())

    assert (await browser.call(client, conversation_id=theirs)).status_code == 404
    assert (await browser.call(client, conversation_id="missing")).status_code == 404
    assert (await browser.call(client)).status_code == 422
    assert speech.stts == []


async def test_ice_candidates_are_only_accepted_for_your_own_call(
    make_client: ClientFactory, browser: Browser
):
    client = make_client(FakeLLM())
    conversation_id = await start_conversation(client)
    pc_id = (await browser.call(client, conversation_id=conversation_id)).json()["pc_id"]
    end_of_candidates = {
        "pc_id": pc_id,
        "candidates": [{"candidate": "", "sdp_mid": "0", "sdp_mline_index": 0}],
    }
    assert (await client.patch("/api/offer", json=end_of_candidates)).status_code == 200

    sign_in_as(client, make_client(FakeLLM(), "stranger"))

    assert (await client.patch("/api/offer", json=end_of_candidates)).status_code == 404


async def test_call_is_unavailable_until_voice_services_are_configured(
    make_client: ClientFactory, browser: Browser
):
    client = make_client(FakeLLM(), voice_configured=False)
    conversation_id = await start_conversation(client)

    for res in [
        await client.get("/api/ice-servers"),  # the browser asks for these before calling
        await browser.call(client, conversation_id=conversation_id),
    ]:
        assert res.status_code == 503
        assert "语音" in res.json()["detail"]


async def test_only_your_own_call_can_be_renegotiated(
    make_client: ClientFactory, speech: FakeSpeech, browser: Browser
):
    client = make_client(FakeLLM())
    conversation_id = await start_conversation(client)
    pc_id = (await browser.call(client, conversation_id=conversation_id)).json()["pc_id"]
    renegotiation = {
        **await browser.offer(conversation_id=conversation_id), "pc_id": pc_id
    }

    assert (await client.post("/api/offer", json=renegotiation)).status_code == 200

    sign_in_as(client, make_client(FakeLLM(), "stranger"))

    assert (await client.post("/api/offer", json=renegotiation)).status_code == 404
    assert len(speech.stts) == 1
