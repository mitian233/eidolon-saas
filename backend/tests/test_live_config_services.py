"""The admin manages operations; platform credential editors have been retired."""

import pytest

from eidolon.config import Settings
from tests.conftest import ClientFactory
from tests.fakes import FakeIdentityProvider, FakeServiceClients
from tests.test_live_config import CONFIG, admin_client, admins  # noqa: F401


@pytest.mark.parametrize("item", [
    "chat_llm", "memory_llm", "tts", "stt", "image", "gpt_image", "judge",
    "judge_thresholds", "rerank", "qweather", "proxy", "service_status",
])
async def test_platform_credentials_cannot_be_written_or_restored(
    make_client: ClientFactory, admins: Settings, github: FakeIdentityProvider, item: str,
):
    client = await admin_client(make_client, admins, github, FakeServiceClients())
    assert (await client.put(f"{CONFIG}/{item}", json={"api_key": "unused-platform-key"})).status_code == 404
    assert (await client.delete(f"{CONFIG}/{item}")).status_code == 404
    assert (await client.post(f"{CONFIG}/{item}/models", json={})).status_code == 404


@pytest.mark.parametrize("provider", ["jev", "cloudflare", "bailian", "retired-provider"])
async def test_legacy_judge_environment_does_not_expose_credentials_or_stop_startup(
    make_client: ClientFactory, settings: Settings, github: FakeIdentityProvider,
    monkeypatch: pytest.MonkeyPatch, provider: str,
):
    from dataclasses import replace

    legacy = {
        "JUDGE_PROVIDER": provider,
        "JEV_API_KEY": "retired-jev-secret",
        "JEV_MODEL": "retired-model",
        "JEV_BASE_URL": "not-a-url",
        "AI_GATEWAY_API_KEY": "retired-gateway-secret",
        "CLOUDFLARE_API_TOKEN": "retired-cloudflare-secret",
        "CLOUDFLARE_JUDGE_MODEL": "invalid-retired-model",
        "BAILIAN_JUDGE_API_KEY": "retired-bailian-secret",
        "BAILIAN_JUDGE_REGION": "invalid-retired-region",
        "SILICONFLOW_API_KEY": "retired-siliconflow-secret",
        "GEMINI_API_KEY": "retired-gemini-secret",
    }
    for name, value in legacy.items():
        monkeypatch.setenv(name, value)
    env = replace(Settings.from_env(), database_path=settings.database_path, admins=frozenset({("github", "1001")}))
    client = await admin_client(make_client, env, github, FakeServiceClients())
    backend = client._transport.app.state.backend  # pyright: ignore[reportAttributeAccessIssue]
    await backend.start()
    response = await client.get(CONFIG)
    assert response.status_code == 200
    assert set(response.json()) == {"limits", "affinity", "reach_outs", "letters", "moments", "schedule", "cycles", "bar", "registration"}
    assert not backend.config.has_service("judge")
    for name, value in legacy.items():
        assert name.lower() not in response.text.lower()
        assert value not in response.text
