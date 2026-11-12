"""Judge requests use the user's LLM and never become platform usage."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from eidolon.config import Settings
from tests.conftest import ClientFactory
from tests.fakes import JUDGED_KEYS, FakeClock, FakeLLM, FakeServiceClients, level
from tests.test_affinity_turns import value
from tests.test_text_turn import send_turn, start_conversation


@pytest.mark.parametrize("provider", ["jev", "cloudflare", "bailian"])
async def test_legacy_platform_credentials_never_pay_for_user_judgements(
    make_client: ClientFactory, settings: Settings, monkeypatch: pytest.MonkeyPatch, provider: str,
):
    for name, old in {
        "JUDGE_PROVIDER": provider,
        "JEV_API_KEY": "old-jev-key",
        "CLOUDFLARE_API_TOKEN": "old-cloudflare-key",
        "BAILIAN_JUDGE_API_KEY": "old-bailian-key",
    }.items():
        monkeypatch.setenv(name, old)
    env = replace(Settings.from_env(), database_path=settings.database_path, dev_login=True)
    clients = FakeServiceClients()
    clients.user_judge.judgings = [level(4)]
    chat = FakeLLM(["<ja>うれしい</ja><zh>很开心</zh>"])
    client = make_client(chat, settings=env, clients=clients, clock=FakeClock())
    events = await send_turn(client, await start_conversation(client), "谢谢你", own_keys=JUDGED_KEYS)
    assert events[-1]["type"] == "done"
    assert value(settings.database_path) == pytest.approx(50.2)
    assert chat.keys == ["test-user-secret"]
    assert clients.user_judge.asked == [("test-user-secret", "affinity")]
    backend = client._transport.app.state.backend  # pyright: ignore[reportAttributeAccessIssue]
    since = datetime.min.replace(tzinfo=UTC)
    _, calls = await backend.activity.since(since)
    assert {(call.service, call.provider, call.own_key) for call in calls} == {
        ("chat_llm", "own", True), ("judge", "own", True),
    }
    assert await backend.activity.deployer_calls_since(since) == {}
