import asyncio
from collections.abc import AsyncIterator, Callable, Coroutine, Mapping
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from typing import Any, Literal, TypeVar

import httpx
import pytest

import eidolon.bailian
import eidolon.data_access
from eidolon.__main__ import main
from eidolon.activity import ActivityLog
from eidolon.app import create_app
from eidolon.assembly import Backend
from eidolon.characters import CallOpener, Character, Greeting, parse_facts
from eidolon.character_repository import CharacterRepository
from eidolon.clock import Clock
from eidolon.config import LLMSettings, Settings
from eidolon.data_access import Database
from eidolon.identity import Identity
from eidolon.producer import Birthday
from eidolon.sessions import SESSION_COOKIE
from eidolon.store import Store
from tests.browser import Browser, open_browser
from tests.fakes import (
    DEPLOYER_FISH_KEY,
    DEPLOYER_SONIOX_KEY,
    START,
    FakeCatalog,
    FakeClock,
    FakeDashScope,
    FakeIdentityProvider,
    FakeLLM,
    FakeLLMService,
    FakeSpeech,
    build_faked,
    registry_of,
)
from tests.stories import write_sample_stories

# A connection to the database taken on the event loop's thread fails the test, so that
# every path the tests run keeps the database off the loop.
eidolon.data_access.ON_THE_LOOP_RAISES = True

T = TypeVar("T")


def aside(work: Coroutine[Any, Any, T]) -> T:
    """What `work` comes to, run on an event loop of its own on a thread of its own and
    waited for here, blocking: for what is done where nothing can be awaited, as a test
    client is made, or as in another process."""
    with ThreadPoolExecutor(1) as thread:
        return thread.submit(asyncio.run, work).result()


@asynccontextmanager
async def store_in(database: Path) -> AsyncIterator[Store]:
    """The store of the database at `database`, on a data access layer of its own, as in
    another process."""
    db = Database(database)
    try:
        yield Store(db)
    finally:
        await db.close()


@asynccontextmanager
async def activity_in(
    database: Path, clock: Clock | None = None
) -> AsyncIterator[ActivityLog]:
    """The activity log of the database at `database`, on a data access layer of its own,
    as in another process, by `clock` (a fake one's by default)."""
    db = Database(database)
    try:
        yield ActivityLog(db, clock or FakeClock())
    finally:
        await db.close()


async def users_in(database: Path, *names: str) -> list[str]:
    """The ids of new users with these names, made in the database at `database` as in
    another process."""
    async with store_in(database) as store:
        return [(await store.create_user(name)).id for name in names]


class Admin:
    """Drives the admin command line against the test database."""

    def __init__(self, database_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        self._database_path = database_path
        self._capsys = capsys

    def run(self, *args: str) -> str:
        code, out, err = self._invoke(args)
        assert code == 0, err
        return out

    def fails(self, *args: str) -> str:
        code, _, err = self._invoke(args)
        assert code != 0
        return err

    def invoke(self, *args: str) -> tuple[int, str, str]:
        """The exit code, standard output and standard error."""
        return self._invoke(args)

    def _invoke(self, args: tuple[str, ...]) -> tuple[int, str, str]:
        self._capsys.readouterr()
        # On a thread of its own, as in a process of its own: it runs an event loop.
        with ThreadPoolExecutor(1) as thread:
            code = thread.submit(main, ["--db", str(self._database_path), *args]).result()
        captured = self._capsys.readouterr()
        return code, captured.out, captured.err


ClientFactory = Callable[..., httpx.AsyncClient]

MANO_SHEET = "# 人设\n你是櫻木真乃。口癖是「ほわっ」。"
KOGANE_SHEET = "# 人设\n你是月岡恋鐘。说长崎方言。"


class Characters(Mapping[str, Character]):
    """The test characters, defined in memory as the engine sees them: no configuration
    directory, no asset files. `build_faked` seeds them into the backend's shared mapping;
    `make_client` and `sign_in_with` also keep them in the database as the signed-in user's
    own, so the private-character API finds them (`seed_characters`). Legacy tests speak
    paired Japanese and Chinese, so `add` defaults to `language_mode="bilingual"`;
    characters created through the API default to single language as production does."""

    def __init__(self) -> None:
        self._by_id: dict[str, Character] = {}

    def add(
        self,
        id: str,
        name: str,
        sheet: str,
        *,
        intro: str = "",
        voice_id: str = "voice",
        color: str | None = "#ffbad6",
        birthday: str | None = "07-07",
        age: int | None = 20,
        speakers: list[str] | None = None,
        facts: str | None = None,
        idol_id: int | None = None,
        greeting: tuple[str, str] | None = None,
        call_opener: tuple[str, str] | None = None,
        other_names: tuple[str, str, str] | None = None,
        short_name: str | None = None,
        avatar_url: str | None = None,
        user_address: str = "你",
        language_mode: Literal["single", "bilingual"] = "bilingual",
    ) -> "Characters":
        """`greeting` is her greeting, delivery cues and all, and its subtitle;
        `call_opener` her call opener, likewise; `other_names` her `name_zh`, `name_kana`
        and `name_romaji`; `facts` her character facts as Markdown, split by heading;
        `birthday` her `"MM-DD"` (None leaves it out); `age` her age (None leaves it out);
        `speakers` the names her lines carry in story scripts."""
        month, day = (int(part) for part in birthday.split("-")) if birthday else (None, None)
        self._by_id[id] = Character(
            id=id,
            name=name,
            intro=intro,
            voice_id=voice_id,
            sheet=sheet,
            color=color or "#64748b",
            birthday=Birthday(month, day) if month is not None and day is not None else None,
            age=age,
            speakers=tuple(speakers) if speakers is not None else (),
            facts=parse_facts(facts) if facts is not None else (),
            idol_id=idol_id,
            greeting=Greeting(*greeting) if greeting is not None else None,
            call_opener=CallOpener(*call_opener) if call_opener is not None else None,
            short_name=short_name,
            name_zh=other_names[0] if other_names is not None else None,
            name_kana=other_names[1] if other_names is not None else None,
            name_romaji=other_names[2] if other_names is not None else None,
            avatar_url=avatar_url,
            user_address=user_address,
            language_mode=language_mode,
        )
        return self

    def __getitem__(self, id: str) -> Character:
        return self._by_id[id]

    def __iter__(self):
        return iter(self._by_id)

    def __len__(self) -> int:
        return len(self._by_id)


def _settings_of(character: Character) -> dict[str, Any]:
    """The settings of hers the database keeps, as `CharacterRepository` takes them."""
    return dict(
        name=character.name, sheet=character.sheet, intro=character.intro,
        avatar_url=character.avatar_url,
        greeting=character.greeting.text if character.greeting is not None else "",
        voice_id=character.voice_id, color=character.color,
        user_address=character.user_address, language_mode=character.language_mode,
        birthday=character.birthday, age=character.age,
    )


def _rename_character(conn, old_id: str, new_id: str) -> None:
    conn.execute("UPDATE characters SET id = ? WHERE id = ?", (new_id, old_id))


def character_id(id: str, user: str = "producer") -> str:
    """The id the registry's character `id` is kept under for the user named `user`: the
    producer's under its own name, everyone else's with the user's name after it, as each
    user's characters are their own rows (`seed_characters`)."""
    return id if user == "producer" else f"{id}-{user}"


class _SeededRepository(CharacterRepository):
    """The repository of a backend whose characters were seeded (`seed_characters`): the
    database keeps their settings, the registry's view what it has no column for (her
    speakers, facts and other names). Each read that refreshes the shared mapping keeps
    those on it, so a turn looking its character up does not drop what the engine and the
    corpus read. Ownership stays the database's: a read finds only the owner's character."""

    def __init__(self, repository: CharacterRepository) -> None:
        self._db = repository._db
        self._characters = repository._characters
        self._views: dict[str, Character] = {}

    def keep(self, seeded: Mapping[str, Character]) -> None:
        """Remember the registry's view of each seeded character, by the id it is kept under."""
        self._views.update(seeded)

    async def load(self) -> None:
        await super().load()
        for id, character in self._characters.items():
            if (view := self._views.get(id)) is not None:
                self._characters[id] = _with_view(character, view)

    async def get(self, owner_id: str, character_id: str) -> Character | None:
        return self._kept(await super().get(owner_id, character_id))

    async def update(
        self, owner_id: str, character_id: str, **settings: object
    ) -> Character | None:
        return self._kept(await super().update(owner_id, character_id, **settings))

    def _kept(self, character: Character | None) -> Character | None:
        if character is None or (view := self._views.get(character.id)) is None:
            return character
        kept = _with_view(character, view)
        self._characters[kept.id] = kept
        return kept


def _with_view(character: Character, view: Character) -> Character:
    """The database's character with what only the registry keeps (`Characters.add`)."""
    return replace(
        character,
        speakers=view.speakers, facts=view.facts, idol_id=view.idol_id,
        call_opener=view.call_opener, short_name=view.short_name,
        name_zh=view.name_zh, name_kana=view.name_kana, name_romaji=view.name_romaji,
    )


async def seed_characters(
    backend: Backend, owner_id: str, characters: Mapping[str, Character], *, suffix: str = ""
) -> None:
    """Keep the registry's characters in the database as `owner_id`'s own, under the ids
    the tests know them by with `suffix` after each, and refresh the shared mapping with
    them: the real repository writes them (a fresh id renamed to the test's, once), so the
    private-character API finds them as the owner's. What the database does not keep (her
    speakers, facts and other names) stays on the mapping's view, for the engine and the
    corpus to read; every later read of the database keeps it there (`_SeededRepository`).
    Seeding again updates what is already there, leaving conversations
    alone; an id another user already owns is left to them, as names are not unique and two
    users may be called the same."""
    await backend.character_repository.load()
    seeded: dict[str, Character] = {}
    for definition in characters.values():
        id = definition.id + suffix
        held = backend.characters.get(id)
        if held is not None and held.owner_id != owner_id:
            continue
        settings = _settings_of(definition)
        if held is None:
            made = await backend.character_repository.create(owner_id, **settings)
            await backend.database.write(_rename_character, made.id, id)
        else:
            await backend.character_repository.update(owner_id, id, **settings)
        seeded[id] = replace(definition, id=id, owner_id=owner_id)
    repository = backend.character_repository
    if not isinstance(repository, _SeededRepository):
        repository = _SeededRepository(repository)
        backend.character_repository = repository
    repository.keep(seeded)
    await repository.load()
    backend.characters.update(seeded)


@pytest.fixture
def characters() -> Characters:
    """Mano and Kogane, bilingual as the legacy tests' replies are."""
    return (
        Characters()
        .add(
            "mano", "櫻木真乃", MANO_SHEET, intro="illumination STARS 的中心",
            color="#ffbad6", speakers=["真乃"], voice_id="mano-voice", idol_id=1,
            birthday="04-25", age=16, language_mode="bilingual",
        )
        .add(
            "kogane", "月岡恋鐘", KOGANE_SHEET, intro="L'Antica 的偶像", color="#f84cad",
            speakers=["恋鐘"], voice_id="kogane-voice", birthday="02-25", age=19,
            language_mode="bilingual",
        )
    )


@pytest.fixture
def story(tmp_path: Path) -> Path:
    """A directory of sample story CSVs: Mano's W.I.N.G. episodes (won, and failure endings),
    a card of Kogane's that Mano also speaks in, and an event with neither."""
    return write_sample_stories(tmp_path / "story")


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_path=tmp_path / "eidolon.db",
        chat_llm=LLMSettings("http://llm.invalid/v1", "test-key", "test-model"),
        ice_servers=[],  # tests run offline: gather host candidates only
        dev_login=True,
        secret_key="test-secret-key",
        soniox_api_key=DEPLOYER_SONIOX_KEY,
        fish_audio_api_key=DEPLOYER_FISH_KEY,
    )


@pytest.fixture
def admin(settings: Settings, capsys: pytest.CaptureFixture[str]) -> Admin:
    return Admin(settings.database_path, capsys)


SITE = {"Origin": "http://localhost:3000"}
"""What the tests' clients send as browsers do: they are the site's own pages."""

COOKIE_DOMAIN = "test.local"
"""Where the cookies of the tests' clients (at http://test) are kept, as for any host
without a dot."""


def sign_in(store: Store, name: str, now: datetime) -> httpx.Cookies:
    """The cookies of a new session for the first user named `name`, who is made, having
    agreed to the terms, if there is none; blocking, so that a client is made signed in
    without awaiting anything."""
    return aside(_signed_in(store, name, now))


async def _signed_in(store: Store, name: str, now: datetime) -> httpx.Cookies:
    user = await store.first_user_named(name) or await store.create_user(name)
    if user.consented_at is None:
        await store.consent(user.id, now)
    cookies = httpx.Cookies()
    cookies.set(SESSION_COOKIE, await store.create_session(user.id, now), domain=COOKIE_DOMAIN)
    return cookies


async def _signed_in_with_characters(
    backend: Backend, name: str, characters: Mapping[str, Character], suffix: str
) -> httpx.Cookies:
    now = backend.clock()
    user = await backend.store.first_user_named(name) or await backend.store.create_user(name)
    if user.consented_at is None:
        await backend.store.consent(user.id, now)
    await seed_characters(backend, user.id, characters, suffix=suffix)
    cookies = httpx.Cookies()
    cookies.set(
        SESSION_COOKIE, await backend.store.create_session(user.id, now), domain=COOKIE_DOMAIN
    )
    return cookies


def github_identity(
    subject: str = "1001",
    name: str = "producer",
    *,
    email: str | None = "producer@example.com",
    created_at: datetime = START - timedelta(days=800),
) -> Identity:
    return Identity("github", subject, name, email, email is not None, created_at)


def google_identity(
    subject: str = "g-1001",
    name: str = "Producer",
    *,
    email: str = "producer@example.com",
    verified: bool = True,
) -> Identity:
    return Identity("google", subject, name, email, verified, None)


async def sign_in_with(
    client: httpx.AsyncClient,
    provider: FakeIdentityProvider,
    identity: Identity,
    *,
    link: bool = False,
    invite: str | None = None,
) -> httpx.Response:
    """Go through signing in at `provider` as `identity`, through the invite link with the
    code `invite` if given, or with `link`, linking it to the signed-in user; the response
    to the callback. A sign-in (not a link) also keeps the registry's characters in the
    database as the signed-in user's own, under the ids `character_id` gives them, as
    `make_client` does for the users it signs in."""
    params = {"link": "1"} if link else {"invite": invite} if invite is not None else None
    start = await client.get(f"/api/auth/{provider.name}/start", params=params)
    assert start.status_code == 302, start.text
    [state] = parse_qs(urlsplit(start.headers["location"]).query)["state"]
    code = provider.will_identify(identity)
    res = await client.get(
        f"/api/auth/{provider.name}/callback", params={"code": code, "state": state}
    )
    if not link and res.headers.get("location") == "/conversations":
        backend: Backend = client._transport.app.state.backend  # pyright: ignore[reportAttributeAccessIssue]
        user_id = await backend.store.user_signing_in_with(identity.provider, identity.subject)
        assert user_id is not None
        user = await backend.store.get_user(user_id)
        await seed_characters(
            backend, user.id, registry_of(backend),
            suffix="" if user.name == "producer" else f"-{user.name}",
        )
    return res


async def agree_to_terms(client: httpx.AsyncClient) -> None:
    res = await client.post(
        "/api/account/consent", json={"agree_to_terms": True, "at_least_13": True}
    )
    assert res.status_code == 204, res.text


def sign_in_as(client: httpx.AsyncClient, other: httpx.AsyncClient) -> None:
    """Have `client` carry the session `other` carries from now on."""
    client.cookies.set(SESSION_COOKIE, other.cookies[SESSION_COOKIE], domain=COOKIE_DOMAIN)


@pytest.fixture
async def dashscope(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[FakeDashScope]:
    """Alibaba Cloud Model Studio's speech recognition, faked on localhost in both regions,
    where the backend connects to by default."""
    fake = FakeDashScope()
    await fake.start()
    monkeypatch.setattr(eidolon.bailian, "REGION_URLS", fake.urls)
    yield fake
    await fake.aclose()


@pytest.fixture
def speech() -> FakeSpeech:
    """Soniox and Fish Audio, faked."""
    return FakeSpeech()


@pytest.fixture
def own_llm() -> FakeLLMService:
    """The LLM services users bring their own keys to, faked."""
    return FakeLLMService()


@pytest.fixture
def github() -> FakeIdentityProvider:
    return FakeIdentityProvider("github")


@pytest.fixture
def google() -> FakeIdentityProvider:
    return FakeIdentityProvider("google")


@pytest.fixture
async def browser() -> AsyncIterator[Browser]:
    """The browser placing a call in the test."""
    async with open_browser() as browser:
        yield browser


@pytest.fixture
async def make_client(
    settings: Settings,
    characters: Characters,
    speech: FakeSpeech,
    github: FakeIdentityProvider,
    google: FakeIdentityProvider,
    own_llm: FakeLLMService,
) -> AsyncIterator[ClientFactory]:
    """Makes API clients, the deployer's chat model playing from `llm`'s script; each is
    signed in as the user with the given name, by default the producer, who has agreed to
    the terms (None for a client not signed in) and owns the registry's characters, kept
    in the database as theirs: the producer's under their own ids, everyone else's with
    the user's name after each (`character_id`). Any other keyword is a script for the
    deployer's models (`background_llm`, `retrieval_judge`, `emotion_judge`), the
    `FakeServiceClients` that make them (`clients`), or an outside service to use instead
    of the one the settings describe (see `fakes.build_faked`); speech, the identity
    providers (the `github` and `google` fixtures), the LLM services users bring their
    own keys to (`own_llm`) and the price catalogs online (an empty `FakeCatalog`) are
    fakes by default, and `voice_configured=False` leaves the deployer without speech
    keys."""
    backends: list[Backend] = []
    clients: list[httpx.AsyncClient] = []

    def factory(
        llm: FakeLLM,
        user: str | None = "producer",
        *,
        settings: Settings = settings,
        voice_configured: bool = True,
        **services: Any,
    ) -> httpx.AsyncClient:
        services.setdefault("identity_providers", {"github": github, "google": google})
        services.setdefault("own_llm_service", own_llm)
        services.setdefault("speech", speech)
        services.setdefault("catalog_transport", FakeCatalog().transport())
        if not voice_configured:
            settings = replace(settings, soniox_api_key=None, fish_audio_api_key=None)
        backend = build_faked(settings, llm, characters=characters, **services)
        backends.append(backend)
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(backend)),
            base_url="http://test",
            headers=SITE,
            cookies=(
                aside(_signed_in_with_characters(
                    backend, user, characters, "" if user == "producer" else f"-{user}"
                ))
                if user is not None else None
            ),
        )
        clients.append(client)
        return client

    yield factory
    for client in clients:
        await client.aclose()
    for backend in backends:  # the test transport runs no lifespan to close it
        await backend.aclose()