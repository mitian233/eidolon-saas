"""Which model each of the deployer's service calls is recorded as (GLOSSARY.md「运行记录」):
always the one that answered it. A turn or call takes the deployer's models together with
what they are as it begins (`LiveConfig.lease`), so one under way when an admin changes a
model goes on being recorded as the model it runs on. Trying a model in the admin console
is not a service call. The deployer's clients are made by a fake `ServiceClients`."""

from dataclasses import replace

import pytest

from eidolon.config import JevSettings, Settings
from eidolon.llm import ChatLLM, ChatMessage
from tests.conftest import ClientFactory
from tests.fakes import FakeIdentityProvider, FakeLLM, FakeServiceClients
from tests.test_live_config import CHAT_LLM, NEW, REPLY, admin_client, recorded, start
from tests.test_live_config_services import CLOUDFLARE, JEV_KEY, JUDGE, backend_of, with_retrieval

ENV = ("llm.invalid", "test-model", False)
SAVED = ("llm.example", "new-model", False)


@pytest.fixture
def admins(settings: Settings) -> Settings:
    return replace(settings, admins=frozenset({("github", "1001")}))


async def ask(llm: ChatLLM) -> None:
    async for _ in llm.stream([ChatMessage("user", "在吗")]):
        pass


async def test_a_lease_taken_before_the_chat_model_changes_is_recorded_as_the_model_it_is_on(
    make_client: ClientFactory, admins: Settings, github: FakeIdentityProvider
):
    clients = FakeServiceClients(FakeLLM(REPLY, REPLY, REPLY))
    client = await admin_client(make_client, admins, github, clients)
    config = backend_of(client).config

    before = config.lease()
    assert (await client.put(CHAT_LLM, json=NEW)).status_code == 200
    after = config.lease()
    for lease in (before, after):
        assert lease.keys.chat_llm is not None
        assert lease.keys.memory_llm is not None
        await ask(lease.keys.chat_llm)
        await ask(lease.keys.memory_llm)
        lease.release()

    assert recorded(client, "chat_llm") == sorted([ENV, SAVED])
    # Unless set apart, the memory model is the chat model the turn began on.
    assert recorded(client, "memory_llm") == sorted([ENV, SAVED])


async def test_trying_a_model_in_the_admin_console_is_no_service_call(
    make_client: ClientFactory, admins: Settings, github: FakeIdentityProvider
):
    clients = FakeServiceClients()
    clients.rejects["sk-rejected-0000"] = "401 invalid api key"
    clients.rejects["cf-rejected-0000"] = "Cloudflare Workers AI 返回 401"
    judged = replace(admins, judge=JevSettings(JEV_KEY))
    client = await admin_client(with_retrieval(make_client), judged, github, clients)

    for path, change, status in [
        (CHAT_LLM, NEW, 200),
        (CHAT_LLM, NEW | {"api_key": "sk-rejected-0000"}, 422),
        (JUDGE, CLOUDFLARE, 200),
        (JUDGE, CLOUDFLARE | {"api_key": "cf-rejected-0000"}, 422),
    ]:
        assert (await client.put(path, json=change)).status_code == status, change
    await start(client)  # tries every override again

    assert [kind for _, kind in clients.judge.asked] == ["check", "check"]
    for service in ("chat_llm", "memory_llm", "judge"):
        assert recorded(client, service) == [], service
