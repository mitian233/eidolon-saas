"""The dashboard's cost estimate (GLOSSARY.md「看板」): what the deployer's keys were billed
for, priced at the preset prices or those admins set in their place, summed by currency
and never converted; usage on users' own keys is shown but not priced. Driven through the
backend's external API with a clock the tests control and presets the tests choose."""

from dataclasses import replace
from datetime import date

import pytest

import eidolon.prices
from eidolon.activity import OWN
from eidolon.config import LLMSettings, Settings
from eidolon.llm import Reasoning
from eidolon.prices import Price
from tests.conftest import ClientFactory, character_id
from tests.fakes import FakeClock, FakeIdentityProvider, FakeLLM, FakeLLMService
from tests.test_activity_records import REPLY, admin_client, dashboard
from tests.test_own_llm import LLM
from tests.test_text_turn import send_turn, start_conversation

AS_OF = date(2026, 10, 7)


@pytest.fixture
def settings(settings: Settings) -> Settings:
    """The tests' settings, where the GitHub user 1001 is an admin."""
    return replace(settings, admins=frozenset({("github", "1001")}))


@pytest.fixture(autouse=True)
def presets(monkeypatch: pytest.MonkeyPatch) -> None:
    """Models priced in advance, in dollars and in yuan, per million tokens; one with a price
    for the input read from the cache."""
    monkeypatch.setattr(eidolon.prices, "PRESETS", {
        ("llm.example", "m-usd", "tokens"): Price(2, 8, "USD", AS_OF),
        ("llm.example", "m-cached", "tokens"): Price(2, 8, "USD", AS_OF, cache_read=0.2),
        ("llm.cn", "m-cny", "tokens"): Price(1, 4, "CNY", AS_OF),
        ("llm.example.com", "my-model", "tokens"): Price(5, 5, "USD", AS_OF),
    })


def on(settings: Settings, base_url: str, model: str) -> Settings:
    """`settings`, with the deployer's chat model at `base_url` named `model`."""
    return replace(settings, chat_llm=LLMSettings(base_url, "test-key", model))


def row(board: dict, provider: str, model: str) -> dict:
    [found] = [
        r for r in board["cost"]["rows"] if (r["provider"], r["model"]) == (provider, model)
    ]
    return found


async def test_the_deployers_usage_is_priced_and_summed_by_currency(
    make_client: ClientFactory, settings: Settings, github: FakeIdentityProvider
):
    clock = FakeClock()
    dollars = make_client(
        FakeLLM(REPLY, REPLY, tokens=(1000, 500)), "a",
        settings=on(settings, "https://llm.example/v1", "m-usd"), clock=clock,
    )
    untold = make_client(
        FakeLLM(REPLY), "b", settings=on(settings, "https://llm.example/v1", "m-usd"), clock=clock
    )
    yuan = make_client(
        FakeLLM(REPLY, tokens=(3000, 1000)), "c",
        settings=on(settings, "https://llm.cn/v1", "m-cny"), clock=clock,
    )
    unpriced = make_client(FakeLLM(REPLY, tokens=(100, 50)), "d", clock=clock)
    admin = await admin_client(make_client, github, clock)

    conversation_id = await start_conversation(dollars, character_id("mano", "a"))
    await send_turn(dollars, conversation_id, "在吗")
    await send_turn(dollars, conversation_id, "在吗")
    for client, user in [(untold, "b"), (yuan, "c"), (unpriced, "d")]:
        await send_turn(
            client, await start_conversation(client, character_id("mano", user)), "在吗"
        )
    cost = (await dashboard(admin))["cost"]

    # 2000 input and 1000 output tokens at $2 and $8 a million; 3000 and 1000 at ¥1 and ¥4.
    assert cost["totals"] == [
        {"currency": "CNY", "amount": pytest.approx(0.007)},
        {"currency": "USD", "amount": pytest.approx(0.012)},
    ]
    assert cost["preset_as_of"] == AS_OF.isoformat()
    usd = row({"cost": cost}, "llm.example", "m-usd")
    assert (usd["service"], usd["unit"], usd["input"], usd["output"]) == (
        "chat_llm", "tokens", 2000, 1000
    )
    assert usd["price"] == {
        "input": 2, "output": 8, "cache_read": None, "currency": "USD", "per": 1_000_000,
        "as_of": AS_OF.isoformat(), "source": "preset",
    }
    assert usd["amount"] == pytest.approx(0.012)
    # The call that said nothing of its tokens is counted, not priced.
    assert (usd["calls"], usd["usage_unknown"]) == (3, 1)
    assert cost["usage_unknown"] == 1
    # A model without a price shows what it used, and no amount.
    test = row({"cost": cost}, "llm.invalid", "test-model")
    assert (test["input"], test["output"], test["price"], test["amount"]) == (100, 50, None, None)
    [chat] = cost["services"]
    assert chat["service"] == "chat_llm"
    assert chat["totals"] == cost["totals"]
    assert (chat["unpriced"], chat["usage_unknown"]) == (1, 1)
    assert [point["amounts"] for point in cost["trend"] if point["amounts"]] == [
        {"CNY": pytest.approx(0.007), "USD": pytest.approx(0.012)}
    ]


async def test_usage_on_users_own_keys_is_shown_but_never_priced(
    make_client: ClientFactory,
    settings: Settings,
    github: FakeIdentityProvider,
    own_llm: FakeLLMService,
):
    clock = FakeClock()
    own_llm.llm = FakeLLM(REPLY, REPLY, tokens=(1000, 500))
    client = make_client(FakeLLM(), clock=clock)
    admin = await admin_client(make_client, github, clock)
    conversation_id = await start_conversation(client)

    # at llm.example.com, my-model, which has a price
    await send_turn(client, conversation_id, "在吗", own_llm=LLM)
    await send_turn(client, conversation_id, "在吗", own_llm=LLM)
    cost = (await dashboard(admin))["cost"]

    assert (cost["totals"], cost["rows"], cost["services"]) == ([], [], [])
    assert cost["own_keys"] == [
        {"service": "chat_llm", "unit": "tokens", "calls": 2, "input": 2000, "output": 1000}
    ]
    # Nor does the prices page offer what they are recorded as to be priced.
    prices = (await admin.get("/api/admin/prices")).json()
    assert prices["unpriced"] == []
    assert listed(prices, OWN, OWN) is None


async def test_a_reply_the_model_thought_through_is_billed_as_any_other(
    make_client: ClientFactory,
    settings: Settings,
    github: FakeIdentityProvider,
    own_llm: FakeLLMService,
):
    clock = FakeClock()
    thought = Reasoning({"reasoning_content": "制作人在吗"})
    client = make_client(
        FakeLLM([thought, *REPLY], tokens=(1000, 500)), "a",
        settings=on(settings, "https://llm.example/v1", "m-usd"), clock=clock,
    )
    own_llm.llm = FakeLLM([thought, *REPLY], tokens=(1000, 500))
    admin = await admin_client(make_client, github, clock)
    conversation_id = await start_conversation(client, character_id("mano", "a"))

    deployers = await send_turn(client, conversation_id, "在吗")
    own = await send_turn(client, conversation_id, "在吗", own_llm=LLM)
    cost = (await dashboard(admin))["cost"]

    assert [e["type"] for e in (deployers[-1], own[-1])] == ["done", "done"]
    usd = row({"cost": cost}, "llm.example", "m-usd")
    assert (usd["calls"], usd["input"], usd["output"]) == (1, 1000, 500)
    assert usd["amount"] == pytest.approx(0.006)
    assert cost["own_keys"] == [
        {"service": "chat_llm", "unit": "tokens", "calls": 1, "input": 1000, "output": 500}
    ]


def listed(prices: dict, provider: str, model: str) -> dict | None:
    return next(
        (p for p in prices["prices"] if (p["provider"], p["model"]) == (provider, model)), None
    )


async def test_an_admins_price_holds_over_the_preset_and_prices_a_model_without_one(
    make_client: ClientFactory, settings: Settings, github: FakeIdentityProvider
):
    clock = FakeClock()
    dollars = make_client(
        FakeLLM(REPLY, tokens=(1000, 500)), "a",
        settings=on(settings, "https://llm.example/v1", "m-usd"), clock=clock,
    )
    unpriced = make_client(FakeLLM(REPLY, tokens=(2000, 0)), "b", clock=clock)
    admin = await admin_client(make_client, github, clock)
    for client, user in [(dollars, "a"), (unpriced, "b")]:
        await send_turn(
            client, await start_conversation(client, character_id("mano", user)), "在吗"
        )
    before = await admin.get("/api/admin/prices")
    assert before.status_code == 200
    # The model used without a price is offered to be priced, under the names recorded.
    assert before.json()["unpriced"] == [
        {"service": "chat_llm", "provider": "llm.invalid", "model": "test-model", "unit": "tokens"}
    ]

    clock.advance(days=1)
    changed = await admin.put("/api/admin/prices", json={
        "provider": "llm.example", "model": "m-usd", "unit": "tokens",
        "input": 4, "output": 10, "currency": "CNY",
    })
    added = await admin.put("/api/admin/prices", json={
        "provider": "llm.invalid", "model": "test-model", "unit": "tokens",
        "input": 0.5, "output": None, "currency": "USD",
    })
    cost = (await dashboard(admin, "7d"))["cost"]

    assert (changed.status_code, added.status_code) == (200, 200)
    usd = listed(added.json(), "llm.example", "m-usd")
    assert usd is not None
    assert usd["preset"] == {
        "input": 2, "output": 8, "cache_read": None, "currency": "USD", "per": 1_000_000,
        "as_of": "2026-10-07", "source": "preset",
    }
    assert usd["override"] == {
        "input": 4, "output": 10, "cache_read": None, "currency": "CNY", "per": 1_000_000,
        "as_of": "2026-09-26", "source": "override",
    }
    assert added.json()["unpriced"] == []
    # 1000 and 500 tokens at ¥4 and ¥10 a million; 2000 at $0.5, output priced as input.
    assert cost["totals"] == [
        {"currency": "CNY", "amount": pytest.approx(0.009)},
        {"currency": "USD", "amount": pytest.approx(0.001)},
    ]
    assert row({"cost": cost}, "llm.example", "m-usd")["price"]["source"] == "override"

    restored = await admin.delete(
        "/api/admin/prices",
        params={"provider": "llm.example", "model": "m-usd", "unit": "tokens"},
    )
    removed = await admin.delete(
        "/api/admin/prices",
        params={"provider": "llm.invalid", "model": "test-model", "unit": "tokens"},
    )
    cost = (await dashboard(admin, "7d"))["cost"]

    assert (restored.status_code, removed.status_code) == (200, 200)
    assert listed(removed.json(), "llm.example", "m-usd")["override"] is None  # pyright: ignore[reportOptionalSubscript]
    # Used lately, the model is still listed, now without a price.
    unset = listed(removed.json(), "llm.invalid", "test-model")
    assert unset is not None
    assert (unset["override"], unset["source"]) == (None, None)
    assert cost["totals"] == [{"currency": "USD", "amount": pytest.approx(0.006)}]


async def test_the_input_read_from_the_cache_is_priced_at_the_cache_price_where_there_is_one(
    make_client: ClientFactory, settings: Settings, github: FakeIdentityProvider
):
    clock = FakeClock()
    cached = make_client(
        FakeLLM(REPLY, tokens=(1000, 100, 800)), "a",
        settings=on(settings, "https://llm.example/v1", "m-cached"), clock=clock,
    )
    untold = make_client(
        FakeLLM(REPLY, tokens=(1000, 100)), "b",
        settings=on(settings, "https://llm.example/v1", "m-cached"), clock=clock,
    )
    no_cache_price = make_client(
        FakeLLM(REPLY, tokens=(1000, 100, 800)), "c",
        settings=on(settings, "https://llm.example/v1", "m-usd"), clock=clock,
    )
    admin = await admin_client(make_client, github, clock)
    for client, user in [(cached, "a"), (untold, "b"), (no_cache_price, "c")]:
        await send_turn(
            client, await start_conversation(client, character_id("mano", user)), "在吗"
        )

    cost = (await dashboard(admin))["cost"]
    with_price = row({"cost": cost}, "llm.example", "m-cached")
    # 1200 input tokens missing the cache (the call that did not say hit none) at $2 a
    # million, 800 hitting it at $0.2, 200 output at $8; without a cache price, all the
    # input at the input's.
    assert (with_price["input"], with_price["cached"], with_price["output"]) == (2000, 800, 200)
    assert with_price["price"]["cache_read"] == 0.2
    assert with_price["amount"] == pytest.approx(0.00416)
    assert row({"cost": cost}, "llm.example", "m-usd")["amount"] == pytest.approx(0.0028)
    assert cost["totals"] == [{"currency": "USD", "amount": pytest.approx(0.00696)}]
    assert [p["amounts"] for p in cost["trend"] if p["amounts"]] == [
        {"USD": pytest.approx(0.00696)}
    ]

    async def priced_at(cache_read: float | None) -> float:
        saved = await admin.put("/api/admin/prices", json={
            "provider": "llm.example", "model": "m-cached", "unit": "tokens",
            "input": 2, "output": 8, "cache_read": cache_read, "currency": "USD",
        })
        assert saved.status_code == 200, saved.text
        override = listed(saved.json(), "llm.example", "m-cached")
        assert override is not None and override["override"]["cache_read"] == cache_read
        return row(await dashboard(admin), "llm.example", "m-cached")["amount"]

    # An admin's cache price holds over the preset's; their price without one has the
    # input read from the cache priced as the rest.
    assert await priced_at(0.1) == pytest.approx(0.00408)
    assert await priced_at(None) == pytest.approx(0.0056)


async def test_prices_are_for_admins_only(make_client: ClientFactory, settings: Settings):
    client = make_client(FakeLLM())

    assert (await client.get("/api/admin/prices")).status_code == 404
    assert (await client.put("/api/admin/prices", json={})).status_code == 404
