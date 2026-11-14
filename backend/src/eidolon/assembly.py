"""Compose the API and conversation services without bundled character content."""

import asyncio
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import httpx

from eidolon.accounts import Accounts
from eidolon.activity import ActivityLog, metered_retrieval
from eidolon.admission import Admissions
from eidolon.affinity import Affinities
from eidolon.announcements import Announcements
from eidolon.backup import Backups
from eidolon.call import Calls, Speech, SpeechServices
from eidolon.characters import Character
from eidolon.character_repository import CharacterRepository
from eidolon.clock import Clock, utc_now
from eidolon.config import DEFAULT_BAILIAN_STT_MODEL, Settings
from eidolon.corpus import StoryCorpus
from eidolon.data_access import Database
from eidolon.data_package import DataPackages
from eidolon.documents import Documents
from eidolon.embedding import Embedder
from eidolon.engine import ConversationEngine
from eidolon.her_now import HerNow
from eidolon.housekeeping import keep_tidy
from eidolon.identity import IdentityProvider, ProviderName, open_identity_providers
from eidolon.invites import Invites
from eidolon.live_config import AFFINITY, LiveConfig, Reach
from eidolon.llm import TurnServices
from eidolon.loop_lag import watch_the_loop
from eidolon.memory import Memories
from eidolon.own_keys import LLMService, OwnKeys, OwnRetrievalService, ProviderLLMService
from eidolon.price_catalog import Catalog
from eidolon.prices import Prices
from eidolon.proxy import ProxyRoutes, reach as reach_provider
from eidolon.rerank import Reranker
from eidolon.retrieval import ModelRetrievalJudge, Retrieval, open_reference_sources
from eidolon.service_clients import ProviderClients, ServiceClients
from eidolon.service_status import ServiceStatus, probes
from eidolon.sponsor import Sponsor
from eidolon.store import Store
from eidolon.titles import Titles
from eidolon.usage import UsageLimiter

Closer = Callable[[], Awaitable[None] | None]
THREADS = 32


@dataclass
class Backend:
    settings: Settings
    database: Database
    store: Store
    characters: dict[str, Character]
    character_repository: CharacterRepository
    memories: Memories
    titles: Titles
    engine: ConversationEngine
    usage: UsageLimiter
    clock: Clock
    calls: Calls
    speech: Speech
    own_keys: OwnKeys
    admissions: Admissions
    accounts: Accounts
    identity_providers: dict[ProviderName, IdentityProvider]
    activity: ActivityLog
    config: LiveConfig
    prices: Prices
    announcements: Announcements
    sponsor: Sponsor
    invites: Invites
    affinities: Affinities
    backups: Backups
    service_status: ServiceStatus
    data_packages: DataPackages
    her_now: HerNow
    documents: Documents
    corpus: StoryCorpus | None = None
    _closers: list[Closer] = field(default_factory=list, repr=False)
    _tasks: list[asyncio.Task] = field(default_factory=list, repr=False)

    async def start(self) -> None:
        asyncio.get_running_loop().set_default_executor(
            ThreadPoolExecutor(THREADS, thread_name_prefix="eidolon")
        )
        await self.character_repository.load()
        await self.config.start()
        self._tasks = [
            asyncio.create_task(self.prices.catalog.keep_fresh()),
            asyncio.create_task(self.service_status.keep_probing()),
            asyncio.create_task(keep_tidy(self.usage.forget_old, self.activity.forget_old)),
            asyncio.create_task(watch_the_loop(lambda: self.calls.in_progress)),
        ]
        if self.corpus is not None:
            self._tasks.append(asyncio.create_task(self.corpus.load()))

    async def aclose(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        for close in reversed(self._closers):
            result = close()
            if result is not None:
                await result
        self._closers.clear()


def build(
    settings: Settings,
    *,
    embedder: Embedder | None = None,
    reranker: Reranker | None = None,
    clock: Clock | None = None,
    speech: Speech | None = None,
    identity_providers: dict[ProviderName, IdentityProvider] | None = None,
    own_llm_service: LLMService | None = None,
    own_retrieval_service: OwnRetrievalService | None = None,
    clients: ServiceClients | None = None,
    catalog_transport: httpx.AsyncBaseTransport | None = None,
    backup_transport: httpx.AsyncBaseTransport | None = None,
    reach: Reach | None = None,
) -> Backend:
    clock = clock or utc_now
    database = Database(settings.database_path)
    closers: list[Closer] = [database.close]
    store = Store(database)
    characters: dict[str, Character] = {}
    character_repository = CharacterRepository(database, characters)
    documents = Documents(database)
    if identity_providers is None:
        identity_providers = open_identity_providers(settings.github, settings.google)
        closers.extend(provider.aclose for provider in identity_providers.values())
    routes = ProxyRoutes(settings.proxy)
    closers.append(routes.aclose)
    bailian_model = (
        settings.bailian_stt_model if settings.stt_provider == "bailian"
        else DEFAULT_BAILIAN_STT_MODEL
    )
    speech = speech or SpeechServices(bailian_model, (), (), routes=routes)
    activity = ActivityLog(database, clock)
    closers.append(activity.aclose)
    catalog = Catalog(database, clock, catalog_transport)
    closers.append(catalog.aclose)
    prices = Prices(database, clock, catalog)
    announcements = Announcements(database, clock)
    sponsor = Sponsor(database, clock)
    invites = Invites(database, clock)
    backups = Backups(database, clock, transport=backup_transport)
    closers.append(backups.aclose)
    config = LiveConfig(
        settings, clients or ProviderClients(routes), clock, db=database,
        activity=activity, speech=speech, routes=routes,
        reach=reach if reach is not None else reach_provider,
    )
    closers.append(config.aclose)
    if own_llm_service is None:
        own_llm_service = ProviderLLMService(
            public_only=settings.domain is not None, routes=routes,
            known_provider=catalog.known_provider,
        )
        closers.append(own_llm_service.aclose)
    if own_retrieval_service is None:
        own_retrieval_service = OwnRetrievalService(
            public_only=settings.domain is not None, routes=routes,
            known_provider=catalog.known_provider,
        )
        closers.append(own_retrieval_service.aclose)
    service_status = ServiceStatus(
        activity, config, probes(config, speech, "", embedder, reranker), clock
    )
    embedder, reranker = metered_retrieval(activity, settings, embedder, reranker)
    retrieval = None
    corpus = None
    if embedder is not None:
        references = open_reference_sources(embedder, documents.source(embedder))
        retrieval = Retrieval(
            None, references, reranker, lambda: config.rerank_thresholds.references
        )

    async def retrieval_for(services: TurnServices, character_id: str) -> Retrieval | None:
        if services.embedder is None:
            return None
        sources = open_reference_sources(services.embedder, documents.source(services.embedder))
        judge = (
            ModelRetrievalJudge(services.judge, services.judge_thresholds)
            if services.judge is not None and services.judge_thresholds is not None else None
        )
        return Retrieval(
            judge, sources, services.reranker,
            lambda: services.rerank_thresholds.references if services.rerank_thresholds else 0.0,
        )
    memories = Memories(
        database, characters, clock, embedder=embedder, reranker=reranker,
        min_relevance=lambda: config.rerank_thresholds.memories,
    )
    closers.append(memories.aclose)
    titles = Titles(store, characters, {})
    closers.append(titles.aclose)
    affinities = Affinities(database, clock, lambda: config.affinity_on)
    usage = UsageLimiter(database, lambda: config.usage_limits, clock)
    own_keys = OwnKeys(
        own_llm_service, config, activity, speech, exempting=lambda: config.exempting_keys,
        retrieval_service=own_retrieval_service,
        emotion=settings.emotion,
    )
    her_now = HerNow(characters, affinities=affinities)
    engine = ConversationEngine(
        database, store, characters, {}, memories, titles, clock, her_now, retrieval,
        history_turns=lambda: config.history_turns,
        affinities=affinities,
        retrieval_for=retrieval_for,
        affinity_enabled=lambda: config.effective(AFFINITY)["enabled"],
    )
    admissions = Admissions(usage, activity, own_keys, cooldown_until=affinities.cooldown_until)
    closers.append(admissions.aclose)
    calls = Calls(
        settings, engine, admissions, own_keys, lambda: config.usage_limits,
        speech, clock, store,
    )
    closers.append(calls.aclose)
    engine.on_cooled(calls.cooled)
    engine.on_ended(calls.conversation_ended)
    return Backend(
        settings=settings, database=database, store=store, characters=characters,
        character_repository=character_repository, memories=memories, titles=titles,
        engine=engine, usage=usage, clock=clock, calls=calls, speech=speech, own_keys=own_keys,
        admissions=admissions,
        accounts=Accounts(
            store, clock, memories, calls, invites, lambda: config.registration,
            settings.admins, settings.secret_key, characters,
        ),
        identity_providers=identity_providers, activity=activity, config=config,
        prices=prices, announcements=announcements, sponsor=sponsor, invites=invites,
        affinities=affinities, backups=backups, service_status=service_status,
        data_packages=DataPackages(database, store, memories, characters, {}, clock),
        her_now=her_now, documents=documents, corpus=corpus, _closers=closers,
    )
