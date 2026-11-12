"""Prices from the catalogs online (GLOSSARY.md「看板」): models.dev's and OpenRouter's,
fetched in the background and on an admin's asking, matched to each service call by the
host it was at and the model it named, in place of the presets and under an admin's
prices. Driven through the backend's external API, the catalogs served by a fake over
HTTP and the clock the tests'."""

import asyncio
import sqlite3
from dataclasses import replace
from datetime import date

import httpx
import pytest

import eidolon.prices
from eidolon.config import Settings
from eidolon.prices import Price
from tests.browser import TIMEOUT
from tests.conftest import (
    ClientFactory,
    agree_to_terms,
    character_id,
    github_identity,
    sign_in_with,
)
from tests.fakes import START, FakeCatalog, FakeClock, FakeIdentityProvider, FakeLLM
from tests.test_activity_records import REPLY, dashboard
from tests.test_cost_estimate import on, row
from tests.test_live_config import start
from tests.test_text_turn import send_turn, start_conversation

AS_OF = date(2026, 10, 7)
REFRESH = "/api/admin/prices/refresh"


@pytest.fixture
def settings(settings: Settings) -> Settings:
    """The tests' settings, where the GitHub user 1001 is an admin."""
    return replace(settings, admins=frozenset({("github", "1001")}))


@pytest.fixture(autouse=True)
def presets(monkeypatch: pytest.MonkeyPatch) -> None:
    """A model priced in advance per million tokens, and one per million bytes."""
    monkeypatch.setattr(eidolon.prices, "PRESETS", {
        ("llm.example", "m-usd", "tokens"): Price(2, 8, "USD", AS_OF),
        ("tts.example", "voice", "bytes"): Price(15, None, "USD", AS_OF),
    })


async def admin_on(
    make_client: ClientFactory,
    github: FakeIdentityProvider,
    clock: FakeClock,
    catalog: FakeCatalog,
) -> httpx.AsyncClient:
    """An admin, signed in on a backend of their own that fetches `catalog`."""
    client = make_client(
        FakeLLM(), user=None, clock=clock, catalog_transport=catalog.transport()
    )
    await sign_in_with(client, github, github_identity("1001", name="octo"))
    await agree_to_terms(client)
    return client


async def turn_on(
    make_client: ClientFactory,
    settings: Settings,
    clock: FakeClock,
    base_url: str,
    model: str,
    tokens: tuple[int, int] | tuple[int, int, int] = (1000, 500),
) -> None:
    """A turn on the deployer's chat model at `base_url` named `model`, billed `tokens`."""
    client = make_client(
        FakeLLM(REPLY, tokens=tokens), model, settings=on(settings, base_url, model), clock=clock
    )
    await send_turn(client, await start_conversation(client, character_id("mano", model)), "在吗")


def models_dev(provider: str, api: str | None, models: dict[str, tuple[float, float]]) -> dict:
    """models.dev's catalog of one provider at `api`, its models priced in dollars per
    million input and output tokens, and a tenth of the input's for that read from the
    cache."""
    return {provider: {
        "id": provider,
        **({"api": api} if api else {}),
        "models": {
            model: {"id": model, "cost": {"input": i, "output": o, "cache_read": i / 10}}
            for model, (i, o) in models.items()
        },
    }}


async def test_the_catalogs_price_holds_over_the_preset_and_an_admins_over_both(
    make_client: ClientFactory, settings: Settings, github: FakeIdentityProvider
):
    clock = FakeClock()
    catalog = FakeCatalog(models_dev("example", "https://llm.example/v1", {"m-usd": (3, 12)}))
    await turn_on(make_client, settings, clock, "https://llm.example/v1", "m-usd")
    admin = await admin_on(make_client, github, clock, catalog)
    before = await dashboard(admin)

    refreshed = await admin.post(REFRESH)
    after = await dashboard(admin)
    await admin.put("/api/admin/prices", json={
        "provider": "llm.example", "model": "m-usd", "unit": "tokens",
        "input": 1, "output": 1, "currency": "USD",
    })
    overridden = await dashboard(admin)

    # 1000 input and 500 output tokens: at the preset's $2 and $8 a million, then the
    # catalog's $3 and $12, then the admin's $1 and $1.
    assert row(before, "llm.example", "m-usd")["price"]["source"] == "preset"
    assert row(before, "llm.example", "m-usd")["amount"] == pytest.approx(0.006)
    assert refreshed.status_code == 200
    assert refreshed.json()["catalog"] == {
        "fetched_at": clock().isoformat(), "failed_at": None, "error": None, "fetching": False
    }
    assert row(after, "llm.example", "m-usd")["price"] == {
        "input": 3, "output": 12, "cache_read": 0.3, "currency": "USD", "per": 1_000_000,
        "as_of": clock().date().isoformat(), "source": "catalog",
        "match": {"provider": "example", "model": "m-usd"},
    }
    assert row(after, "llm.example", "m-usd")["amount"] == pytest.approx(0.009)
    assert row(overridden, "llm.example", "m-usd")["price"]["source"] == "override"
    assert row(overridden, "llm.example", "m-usd")["amount"] == pytest.approx(0.0015)


async def test_a_model_is_found_by_its_name_as_it_is_then_looser_and_looser(
    make_client: ClientFactory, settings: Settings, github: FakeIdentityProvider
):
    clock = FakeClock()
    catalog = FakeCatalog(models_dev("example", "https://llm.example/v1", {
        "M-Exact": (1, 1),
        "m-exact": (2, 2),
        "vendor/gpt-6-sol": (3, 3),
        "m-tagged": (4, 4),
        "m-variant": (5, 5),
        "claude-opus-4-6": (6, 6),
        "m-embed": (7, 7),
    }))
    called = [
        "M-Exact",  # as it is, before the same name in lower case
        "openai/GPT-6-Sol",  # without a path, in lower case
        "m-tagged:free",  # without a tag
        "m-variant (thinking)",  # without a variant
        "claude-opus-4.6",  # with a dot taken for a dash
        "Claude-Opus-4.6:thinking",  # all of these at once
        "m-embed@1536",  # without its dimensions
        "m-unknown",
    ]
    for model in called:
        await turn_on(make_client, settings, clock, "https://llm.example/v1", model)
    admin = await admin_on(make_client, github, clock, catalog)

    await admin.post(REFRESH)
    board = await dashboard(admin)

    prices = {
        model: (p := row(board, "llm.example", model)["price"]) and (p["input"], p["match"]["model"])
        for model in called
    }
    assert prices == {
        "M-Exact": (1, "M-Exact"),
        "openai/GPT-6-Sol": (3, "vendor/gpt-6-sol"),
        "m-tagged:free": (4, "m-tagged"),
        "m-variant (thinking)": (5, "m-variant"),
        "claude-opus-4.6": (6, "claude-opus-4-6"),
        "Claude-Opus-4.6:thinking": (6, "claude-opus-4-6"),
        "m-embed@1536": (7, "m-embed"),
        "m-unknown": None,
    }


async def test_a_model_at_a_host_no_catalog_knows_is_priced_as_its_maker_prices_it(
    make_client: ClientFactory, settings: Settings, github: FakeIdentityProvider
):
    clock = FakeClock()
    catalog = FakeCatalog({
        **models_dev("openai", None, {"shared": (1, 1)}),
        **models_dev("anthropic", None, {"claude-x-5": (4, 20)}),
        **models_dev("deepseek", "https://api.deepseek.com", {"shared": (2, 2)}),
        **models_dev("some-host", "https://api.some-host.example/v1", {"other": (1, 1)}),
    })
    # A relay, by the model's name alone or with its maker's before it; and a host the
    # catalog knows, which does not list the model.
    await turn_on(make_client, settings, clock, "https://relay.example/v1", "anthropic/claude-x-5")
    await turn_on(make_client, settings, clock, "https://relay.example/v1", "deepseek/shared")
    await turn_on(make_client, settings, clock, "https://api.some-host.example/v1", "claude-x-5")
    admin = await admin_on(make_client, github, clock, catalog)

    await admin.post(REFRESH)
    board = await dashboard(admin)
    prices = (await admin.get("/api/admin/prices")).json()

    relayed = row(board, "relay.example", "anthropic/claude-x-5")["price"]
    assert (relayed["input"], relayed["output"], relayed["source"], relayed["match"]) == (
        4, 20, "catalog_upstream", {"provider": "anthropic", "model": "claude-x-5"}
    )
    assert row(board, "relay.example", "deepseek/shared")["price"]["match"] == {
        "provider": "deepseek", "model": "shared"
    }
    assert row(board, "api.some-host.example", "claude-x-5")["price"] is None
    assert prices["unpriced"] == [{
        "service": "chat_llm", "provider": "api.some-host.example", "model": "claude-x-5",
        "unit": "tokens",
    }]


async def test_openrouters_own_catalog_prices_its_models_per_million_tokens(
    make_client: ClientFactory, settings: Settings, github: FakeIdentityProvider
):
    clock = FakeClock()
    catalog = FakeCatalog(
        # models.dev's copy of OpenRouter's, which is not the one used
        models_dev(
            "openrouter", "https://openrouter.ai/api/v1",
            {"vendor/judge": (9, 9), "vendor/copied": (9, 9)},
        ),
        [
            {"id": "vendor/judge", "pricing": {"prompt": "0.000000042", "completion": "0"}},
            {"id": "openrouter/auto", "pricing": {"prompt": "-1", "completion": "-1"}},
        ],
    )
    await turn_on(
        make_client, settings, clock, "https://openrouter.ai/api/v1", "vendor/judge", (1000, 10)
    )
    for model in ["openrouter/auto", "vendor/copied"]:
        await turn_on(make_client, settings, clock, "https://openrouter.ai/api/v1", model)
    admin = await admin_on(make_client, github, clock, catalog)

    await admin.post(REFRESH)
    board = await dashboard(admin)

    judge = row(board, "openrouter.ai", "vendor/judge")
    assert (judge["price"]["input"], judge["price"]["output"]) == (0.042, 0)
    assert judge["amount"] == pytest.approx(0.000042)
    # A price that varies is no price; nor is one only models.dev's copy has.
    assert row(board, "openrouter.ai", "openrouter/auto")["price"] is None
    assert row(board, "openrouter.ai", "vendor/copied")["price"] is None


async def test_the_catalogs_price_the_input_read_from_the_cache_where_they_say(
    make_client: ClientFactory, settings: Settings, github: FakeIdentityProvider
):
    clock = FakeClock()
    catalog = FakeCatalog(
        {
            **models_dev("example", "https://llm.example/v1", {"m-usd": (3, 12)}),
            "plain": {"id": "plain", "api": "https://plain.example/v1", "models": {
                "m-plain": {"id": "m-plain", "cost": {"input": 1, "output": 2}},
            }},
        },
        [
            {"id": "vendor/cached", "pricing": {
                "prompt": "0.000002", "completion": "0.00001", "input_cache_read": "0.0000002",
            }},
            {"id": "vendor/uncached", "pricing": {"prompt": "0.000002", "completion": "0.00001"}},
        ],
    )
    for base_url, model in [
        ("https://llm.example/v1", "m-usd"),
        ("https://plain.example/v1", "m-plain"),
        ("https://openrouter.ai/api/v1", "vendor/cached"),
        ("https://openrouter.ai/api/v1", "vendor/uncached"),
    ]:
        await turn_on(make_client, settings, clock, base_url, model, (1000, 0, 800))
    admin = await admin_on(make_client, github, clock, catalog)

    await admin.post(REFRESH)
    board = await dashboard(admin)
    prices = (await admin.get("/api/admin/prices")).json()

    def priced(provider: str, model: str) -> tuple[float | None, float]:
        found = row(board, provider, model)
        return found["price"]["cache_read"], found["amount"]

    # 200 input tokens missing the cache, 800 hitting it, at the input's price and the
    # cache's; where the catalog has no cache price, all 1000 at the input's.
    assert priced("llm.example", "m-usd") == (0.3, pytest.approx(0.00084))
    assert priced("plain.example", "m-plain") == (None, pytest.approx(0.001))
    assert priced("openrouter.ai", "vendor/cached") == (0.2, pytest.approx(0.00056))
    assert priced("openrouter.ai", "vendor/uncached") == (None, pytest.approx(0.002))
    [listed] = [p for p in prices["prices"] if p["model"] == "m-usd"]
    assert listed["catalog"]["cache_read"] == 0.3


async def test_a_failed_fetch_keeps_the_catalogs_fetched_before_and_says_why(
    make_client: ClientFactory, settings: Settings, github: FakeIdentityProvider
):
    clock = FakeClock()
    catalog = FakeCatalog(models_dev("example", "https://llm.example/v1", {"m-usd": (3, 12)}))
    await turn_on(make_client, settings, clock, "https://llm.example/v1", "m-usd")
    admin = await admin_on(make_client, github, clock, catalog)
    await admin.post(REFRESH)
    fetched_at = clock().isoformat()

    clock.advance(days=2)
    catalog.failing = True
    failed = await admin.post(REFRESH)
    board = await dashboard(admin, "7d")

    assert failed.status_code == 200
    state = failed.json()["catalog"]
    assert (state["fetched_at"], state["failed_at"]) == (fetched_at, clock().isoformat())
    assert "503" in state["error"]
    price = row(board, "llm.example", "m-usd")["price"]
    assert (price["source"], price["input"], price["as_of"]) == (
        "catalog", 3, fetched_at[:10]
    )
    assert board["cost"]["catalog_as_of"] == fetched_at[:10]

    catalog.failing = False
    await admin.post(REFRESH)
    assert (await admin.get("/api/admin/prices")).json()["catalog"] == {
        "fetched_at": clock().isoformat(), "failed_at": None, "error": None, "fetching": False
    }


async def test_the_catalogs_price_only_what_is_billed_in_tokens(
    make_client: ClientFactory, github: FakeIdentityProvider
):
    catalog = FakeCatalog(models_dev("tts", "https://tts.example/v1", {"voice": (1, 1)}))
    admin = await admin_on(make_client, github, FakeClock(), catalog)

    prices = (await admin.post(REFRESH)).json()

    [voice] = [p for p in prices["prices"] if p["model"] == "voice"]
    assert (voice["unit"], voice["source"], voice["catalog"]) == ("bytes", "preset", None)


async def settled(admin: httpx.AsyncClient) -> dict:
    """The prices, once no fetch of the catalogs is under way."""
    async with asyncio.timeout(TIMEOUT):
        while (prices := (await admin.get("/api/admin/prices")).json())["catalog"]["fetching"]:
            await asyncio.sleep(0.02)
    return prices


async def fetches_on_looking(admin: httpx.AsyncClient, catalog: FakeCatalog) -> int:
    """How many times looking at the prices fetched the catalogs."""
    before = catalog.fetches
    looked = (await admin.get("/api/admin/prices")).json()
    if looked["catalog"]["fetching"]:
        await settled(admin)
    return catalog.fetches - before


async def test_the_catalogs_are_fetched_as_the_server_starts_and_again_once_a_day(
    make_client: ClientFactory, github: FakeIdentityProvider
):
    clock = FakeClock()
    catalog = FakeCatalog(models_dev("example", "https://llm.example/v1", {"m-usd": (3, 12)}))
    admin = await admin_on(make_client, github, clock, catalog)

    await start(admin)
    started = await settled(admin)

    assert catalog.fetches == 1
    assert started["catalog"]["fetched_at"] == clock().isoformat()
    clock.advance(hours=23)
    assert await fetches_on_looking(admin, catalog) == 0
    clock.advance(hours=1)
    assert await fetches_on_looking(admin, catalog) == 1
    # Failing, it is tried again ten minutes on, not each time it is looked at.
    catalog.failing = True
    clock.advance(hours=24)
    assert (await settled(admin))["catalog"]["error"] is not None
    clock.advance(minutes=9)
    assert await fetches_on_looking(admin, catalog) == 0
    catalog.failing = False
    clock.advance(minutes=1)
    assert await fetches_on_looking(admin, catalog) == 1


async def test_a_model_without_a_price_has_the_catalogs_fetched_again_at_most_every_six_hours(
    make_client: ClientFactory, settings: Settings, github: FakeIdentityProvider
):
    clock = FakeClock()
    catalog = FakeCatalog()
    admin = await admin_on(make_client, github, clock, catalog)
    await admin.post(REFRESH)
    assert await fetches_on_looking(admin, catalog) == 0  # nothing is without a price

    await turn_on(make_client, settings, clock, "https://llm.example/v1", "m-new")
    clock.advance(hours=5)
    assert await fetches_on_looking(admin, catalog) == 0
    catalog.models_dev = models_dev("example", "https://llm.example/v1", {"m-new": (1, 1)})
    clock.advance(hours=1)
    assert await fetches_on_looking(admin, catalog) == 1
    assert (await settled(admin))["unpriced"] == []


async def test_only_admins_have_the_catalogs_fetched(make_client: ClientFactory):
    catalog = FakeCatalog()
    client = make_client(FakeLLM(), catalog_transport=catalog.transport())

    assert (await client.post(REFRESH)).status_code == 404
    assert catalog.fetches == 0


async def test_catalogs_never_fetched_leave_the_presets_in_effect(
    make_client: ClientFactory, settings: Settings, github: FakeIdentityProvider
):
    clock = FakeClock()
    catalog = FakeCatalog(models_dev("example", "https://llm.example/v1", {"m-usd": (3, 12)}))
    catalog.failing = True
    await turn_on(make_client, settings, clock, "https://llm.example/v1", "m-usd")
    admin = await admin_on(make_client, github, clock, catalog)

    failed = (await admin.post(REFRESH)).json()
    board = await dashboard(admin)

    assert (failed["catalog"]["fetched_at"], failed["catalog"]["failed_at"]) == (
        None, clock().isoformat()
    )
    assert row(board, "llm.example", "m-usd")["price"]["source"] == "preset"
    assert board["cost"]["catalog_as_of"] is None


async def test_prices_kept_before_cache_prices_were_have_none(
    make_client: ClientFactory, settings: Settings, github: FakeIdentityProvider
):
    """An admin's price and the catalogs as kept before: input read from the cache is priced
    as the rest, until the admin sets it or the catalogs are fetched again."""
    with sqlite3.connect(settings.database_path) as db:
        db.execute(
            "CREATE TABLE price_overrides (provider TEXT NOT NULL, model TEXT NOT NULL,"
            " unit TEXT NOT NULL, input REAL NOT NULL, output REAL, currency TEXT NOT NULL,"
            " updated_at TEXT NOT NULL, PRIMARY KEY (provider, model, unit))"
        )
        db.execute(
            "INSERT INTO price_overrides VALUES ('llm.example', 'm-usd', 'tokens', 1, 1, 'USD',"
            " ?)",
            (START.isoformat(),),
        )
        db.execute(
            "CREATE TABLE price_catalog (provider TEXT NOT NULL, model TEXT NOT NULL,"
            " input REAL NOT NULL, output REAL, PRIMARY KEY (provider, model))"
        )
        db.execute("INSERT INTO price_catalog VALUES ('example', 'm-usd', 3, 12)")
    catalog = FakeCatalog(models_dev("example", "https://llm.example/v1", {"m-usd": (3, 12)}))
    admin = await admin_on(make_client, github, FakeClock(), catalog)

    before = (await settled(admin))["prices"]
    after = (await admin.post(REFRESH)).json()["prices"]

    [kept] = [p for p in before if p["model"] == "m-usd"]
    assert (kept["override"]["input"], kept["override"]["cache_read"]) == (1, None)
    [fetched] = [p for p in after if p["model"] == "m-usd"]
    assert fetched["catalog"]["cache_read"] == 0.3
