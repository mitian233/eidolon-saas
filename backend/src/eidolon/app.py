"""The backend's HTTP API."""

import asyncio
import json
import math
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import aclosing, asynccontextmanager
from dataclasses import asdict

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from starlette.types import Receive, Scope, Send
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator
from typing import Literal

from eidolon.admission import CoolingDown
from eidolon.assembly import Backend
from eidolon.avatar import InvalidAvatar, fetch_avatar
from eidolon.call import (
    CallFailed,
    CallsBusy,
    CallNotFound,
    CallOptions,
    IceCandidate,
    Quality,
    SessionDescription,
    StillPlacing,
)
from eidolon.character_repository import shown_character
from eidolon.database import readable
from eidolon.engine import ENDED, TurnJudged, shown
from eidolon.embedding import EmbeddingError
from eidolon.reply_format import SegmentComplete, SegmentDelta, SpeechDelta
from eidolon.own_keys import (
    BroughtKeys,
    CallsUnavailable,
    UnknownService,
    named_services,
)
from eidolon.producer import (
    MAX_CITY_PART_LENGTH,
    MAX_FORM_OF_ADDRESS_LENGTH,
    Birthday,
    City,
    Gender,
    ProducerProfile,
    is_day_of_the_year,
    is_timezone,
)
from eidolon.account_api import OwnKeysInput, add_account_routes
from eidolon.admin_api import add_admin_routes
from eidolon.admin_backup_api import add_admin_backup_routes
from eidolon.dashboard import add_dashboard_routes
from eidolon.data_package_api import add_data_package_routes
from eidolon.admin_users_api import add_admin_user_routes
from eidolon.admin_config_api import add_admin_config_routes
from eidolon.admin_prices_api import add_admin_price_routes
from eidolon.announcements_api import add_announcement_routes
from eidolon.invites_api import add_invite_routes
from eidolon.calendar_api import add_calendar_routes
from eidolon.sessions import DeviceTimezone, UserId, session_middleware
from eidolon.sponsor_api import add_sponsor_routes
from eidolon.service_status import add_service_status_routes
from eidolon.stats import add_stats_routes
from eidolon.store import Conversation, ConversationEvent, IsCurrent, ReachOut, Recorded
from eidolon.throttle import Throttled
from eidolon.turn_outcome import TurnOutcome
from eidolon.usage import OverLimit

HEALTH_TIMEOUT = 5.0
"""How long, in seconds, the health check may take before the backend is taken not to
serve: its threads may all be taken."""



class NewConversation(BaseModel):
    character_id: str


class TurnInput(BaseModel):
    text: str
    own_keys: OwnKeysInput | None = None
    """The user's own keys, which their browser keeps, for the turn to run on; the shape
    calls bring too. A text turn uses only the language model keys.
    """




class CallRequest(BaseModel):
    conversation_id: str
    muted: bool = False
    quality: Quality = "standard"
    own_keys: OwnKeysInput | None = None
    """The user's own keys, which their browser keeps, for the call to run on."""


class BirthdayInput(BaseModel):
    month: int
    day: int

    @model_validator(mode="after")
    def _day_of_the_year(self) -> "BirthdayInput":
        if not is_day_of_the_year(self.month, self.day):
            raise ValueError(f"没有 {self.month} 月 {self.day} 日这一天")
        return self


class CharacterInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=100)
    sheet: str = Field(min_length=1, max_length=100000)
    intro: str = Field(default="", max_length=2000)
    avatar_url: HttpUrl | None = None
    greeting: str = Field(default="", max_length=10000)
    voice_id: str = Field(default="", max_length=200)
    color: str = Field(default="#64748b", pattern=r"^#[0-9a-fA-F]{6}$")
    user_address: str = Field(default="你", min_length=1, max_length=80)
    language_mode: Literal["single", "bilingual"] = "single"
    birthday: BirthdayInput | None = None
    age: int | None = Field(default=None, gt=0)

    def settings(self) -> dict:
        values = self.model_dump()
        values["avatar_url"] = str(self.avatar_url) if self.avatar_url is not None else None
        values["birthday"] = Birthday(self.birthday.month, self.birthday.day) if self.birthday else None
        return values


class DocumentInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    origin: str = Field(min_length=1, max_length=500)
    text: str = Field(min_length=1, max_length=1000000)
    own_keys: OwnKeysInput | None = None


class CityInput(BaseModel):
    """The producer's city, as `/api/cities` found it."""

    name: str = Field(min_length=1, max_length=MAX_CITY_PART_LENGTH)
    adm2: str = Field("", max_length=MAX_CITY_PART_LENGTH)
    adm1: str = Field("", max_length=MAX_CITY_PART_LENGTH)
    country: str = Field("", max_length=MAX_CITY_PART_LENGTH)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class ProfileInput(BaseModel):
    """The whole producer profile; a field left out or empty returns to its default."""

    form_of_address: str | None = None
    gender: Gender | None = None
    timezone: str | None = None
    birthday: BirthdayInput | None = None
    city: CityInput | None = None

    @field_validator("form_of_address")
    @classmethod
    def _address(cls, value: str | None) -> str | None:
        value = (value or "").strip()
        if len(value) > MAX_FORM_OF_ADDRESS_LENGTH:
            raise ValueError(f"称呼最多 {MAX_FORM_OF_ADDRESS_LENGTH} 个字")
        return value or None

    @field_validator("timezone")
    @classmethod
    def _timezone(cls, value: str | None) -> str | None:
        value = (value or "").strip()
        if value and not is_timezone(value):
            raise ValueError(f"不认识的时区 {value}")
        return value or None


class Offer(BaseModel):
    """A WebRTC offer as the Pipecat client sends it; `requestData` carries our CallRequest."""

    model_config = ConfigDict(populate_by_name=True)

    sdp: str
    type: str
    pc_id: str | None = None
    restart_pc: bool | None = None
    call: CallRequest | None = Field(None, alias="requestData")


class IceCandidateInput(BaseModel):
    candidate: str
    sdp_mid: str
    sdp_mline_index: int


class IceCandidates(BaseModel):
    """ICE candidates the browser trickles in for one of its calls."""

    pc_id: str
    candidates: list[IceCandidateInput]




def create_app(backend: Backend) -> FastAPI:
    """The API over `backend`, which the app closes when it shuts down."""
    store, characters, engine = backend.store, backend.characters, backend.engine
    memory, calls, admissions = backend.memories, backend.calls, backend.admissions
    titles = backend.titles

    def last_shown(last: Recorded | None) -> dict | None:
        if last is None:
            return None
        shown = last.shown()
        if isinstance(last, ConversationEvent):
            return shown
        return {key: shown.get(key) for key in ("role", "text", "ja", "zh", "created_at")} | (
            {"reach_out": True} if isinstance(last, ReachOut) else {}
        )

    def recorded(entry: Recorded) -> dict:
        return entry.shown()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await backend.start()
        try:
            yield
        finally:
            await backend.aclose()

    app = FastAPI(title="Eidolon-SaaS", lifespan=lifespan)
    app.state.backend = backend
    app.middleware("http")(session_middleware(backend.settings))

    @app.exception_handler(OverLimit)
    async def over_limit(_: Request, e: OverLimit) -> JSONResponse:
        """Refused for now, with when the user can go on (also as `Retry-After`); or, set
        to their own keys only, with no time to wait for."""
        if e.retry_at is None:
            return JSONResponse({"detail": str(e), "retry_at": None}, status_code=429)
        wait = max(1, math.ceil((e.retry_at - e.now).total_seconds()))
        return JSONResponse(
            {"detail": str(e), "retry_at": e.retry_at.isoformat()},
            status_code=429,
            headers={"Retry-After": str(wait)},
        )

    @app.exception_handler(CoolingDown)
    async def cooling_down(_: Request, e: CoolingDown) -> JSONResponse:
        """Refused while she is in a cooldown, with when it ends; told apart from the limit's
        429."""
        return JSONResponse(
            {"detail": str(e), "cooldown_until": e.cooldown_until.isoformat()}, status_code=409
        )

    @app.exception_handler(CallsUnavailable)
    async def calls_unavailable(_: Request, e: CallsUnavailable) -> JSONResponse:
        return JSONResponse({"detail": str(e)}, status_code=503)

    @app.exception_handler(Throttled)
    async def throttled(_: Request, e: Throttled) -> JSONResponse:
        """Asked services on the internet too often: when to ask again, in words too."""
        wait = e.retry_after
        later = f"{wait} 秒" if wait < 120 else f"{math.ceil(wait / 60)} 分钟"
        return JSONResponse(
            {"detail": f"{e}，请 {later}后再试"}, status_code=429,
            headers={"Retry-After": str(wait)},
        )

    @app.exception_handler(UnknownService)
    async def unknown_service(_: Request, e: UnknownService) -> JSONResponse:
        return JSONResponse({"detail": str(e)}, status_code=422)


    @app.exception_handler(CallNotFound)
    async def call_not_found(_: Request, e: CallNotFound) -> JSONResponse:
        return JSONResponse({"detail": str(e)}, status_code=404)

    @app.exception_handler(CallsBusy)
    async def calls_busy(_: Request, e: CallsBusy) -> JSONResponse:
        """Refused for now, as many calls being under way as there may be at once; told
        apart from calls being unavailable by its `code`."""
        return JSONResponse({"detail": str(e), "code": "calls_busy"}, status_code=503)

    @app.exception_handler(StillPlacing)
    async def still_placing(_: Request, e: StillPlacing) -> JSONResponse:
        """Refused for now, the user's last call not yet answered; as a conflict, told apart
        from a call refused for the limit's 429."""
        return JSONResponse({"detail": str(e)}, status_code=409)

    @app.exception_handler(CallFailed)
    async def call_failed(_: Request, e: CallFailed) -> JSONResponse:
        return JSONResponse({"detail": str(e)}, status_code=500)

    async def conversation_or_404(conversation_id: str, user_id: str) -> Conversation:
        conversation = await store.get_conversation(conversation_id)
        if conversation is None or conversation.user_id != user_id:
            raise HTTPException(404, "对话不存在")
        character = await backend.character_repository.get(user_id, conversation.character_id)
        if character is None:
            raise HTTPException(404, "角色不存在")
        return conversation

    async def refuse_if_ended(conversation: Conversation) -> None:
        """A call into a conversation she has ended (GLOSSARY.md「已结束的对话」) is refused,
        before anything is asked or spent; told apart from the limit's 429."""
        if await store.ended(conversation.id) is not None:
            raise HTTPException(409, ENDED)

    async def conversation_to_call(conversation_id: str, user_id: str) -> Conversation:
        """The user's conversation a call is to go into, as `conversation_or_404` finds it,
        unless she has ended it (`refuse_if_ended`)."""
        conversation = await conversation_or_404(conversation_id, user_id)
        await refuse_if_ended(conversation)
        return conversation

    @app.get("/api/health")
    async def health() -> JSONResponse:
        """Whether the backend can serve: 503 when it cannot read the database in time,
        on a thread, as those it serves are."""
        try:
            ok = await asyncio.wait_for(
                asyncio.to_thread(readable, backend.settings.database_path), HEALTH_TIMEOUT
            )
        except TimeoutError:
            ok = False
        return JSONResponse({"ok": ok}, status_code=200 if ok else 503)

    add_account_routes(app, backend)
    add_admin_routes(app, backend)
    add_dashboard_routes(app, backend)
    add_admin_backup_routes(app, backend)
    add_admin_user_routes(app, backend)
    add_invite_routes(app, backend)
    add_admin_config_routes(app, backend)
    add_admin_price_routes(app, backend)
    add_announcement_routes(app, backend)
    add_calendar_routes(app)
    add_sponsor_routes(app, backend)
    add_data_package_routes(app, backend)
    add_service_status_routes(app, backend.service_status)
    add_stats_routes(app, backend)

    @app.get("/api/ice-servers")
    async def ice_servers(
        user_id: UserId, own: str = "", conversation: str | None = None
    ) -> dict:
        """What the browser needs before calling, if the call is to bring the user's own
        keys for the services `own` names (as `llm,tts,stt`), but none of the keys; also
        tells it when calls are unavailable, or, for a call into `conversation`, when she
        is in a cooldown or has ended it."""
        character_id = None
        if conversation:
            into = await conversation_to_call(conversation, user_id)
            character_id = into.character_id
        return await calls.ice_servers(user_id, named_services(own), character_id)

    @app.post("/api/offer")
    async def offer(
        body: Offer, user_id: UserId, device_timezone: DeviceTimezone = None
    ) -> dict:
        """WebRTC signalling: a new call into one of the user's conversations, on the user's
        own keys it brings, or a renegotiation, which brings none."""
        description = SessionDescription(body.sdp, body.type)
        if body.pc_id is not None:  # renegotiating, possibly on a fresh peer connection
            return await calls.renegotiate(
                user_id, body.pc_id, description, bool(body.restart_pc)
            )
        if body.call is None:
            raise HTTPException(422, "缺少要通话的对话")
        conversation = await conversation_to_call(body.call.conversation_id, user_id)
        return await calls.start(
            user_id,
            conversation,
            characters[conversation.character_id],
            CallOptions(body.call.muted, body.call.quality, device_timezone),
            description,
            body.call.own_keys.brought() if body.call.own_keys else BroughtKeys(),
        )

    @app.patch("/api/offer")
    async def ice_candidates(body: IceCandidates, user_id: UserId) -> dict:
        candidates = [
            IceCandidate(c.candidate, c.sdp_mid, c.sdp_mline_index) for c in body.candidates
        ]
        await calls.add_candidates(user_id, body.pc_id, candidates)
        return {"ok": True}

    def shown_profile(profile: ProducerProfile) -> dict:
        """The profile, and whether the deployer can find cities (`finds_cities`, with a
        QWeather account): without, the city is not shown, nor is it any use."""
        return asdict(profile) | {"finds_cities": backend.config.qweather.on}

    @app.get("/api/profile")
    async def get_profile(user_id: UserId) -> dict:
        return shown_profile(await store.get_profile(user_id))

    @app.put("/api/profile")
    async def update_profile(body: ProfileInput, user_id: UserId) -> dict:
        birthday = body.birthday and Birthday(body.birthday.month, body.birthday.day)
        city = body.city and City(**body.city.model_dump())
        profile = ProducerProfile(
            body.form_of_address, body.gender, body.timezone, birthday, city
        )
        await store.save_profile(user_id, profile)
        return shown_profile(profile)

    async def owned_character(character_id: str, user_id: str):
        character = await backend.character_repository.get(user_id, character_id)
        if character is None:
            raise HTTPException(404, "角色不存在")
        return character

    @app.get("/api/characters")
    async def list_characters(user_id: UserId) -> list[dict]:
        return [shown_character(c) for c in await backend.character_repository.list(user_id)]

    @app.post("/api/characters", status_code=201)
    async def create_character(body: CharacterInput, user_id: UserId) -> dict:
        character = await backend.character_repository.create(user_id, **body.settings())
        return shown_character(character)

    @app.get("/api/characters/{character_id}")
    async def get_character(character_id: str, user_id: UserId) -> dict:
        return shown_character(await owned_character(character_id, user_id))

    @app.get("/api/characters/{character_id}/documents")
    async def list_documents(character_id: str, user_id: UserId) -> list[dict]:
        await owned_character(character_id, user_id)
        return await backend.documents.list(user_id, character_id)

    @app.post("/api/characters/{character_id}/documents", status_code=201)
    async def import_document(character_id: str, body: DocumentInput, user_id: UserId) -> dict:
        await owned_character(character_id, user_id)
        brought = body.own_keys.brought() if body.own_keys else BroughtKeys()
        embedder = backend.own_keys.document_embedder(brought)
        if embedder is None:
            raise HTTPException(400, "请提供自带的向量化密钥")
        try:
            document_id = await backend.documents.import_text(
                user_id, character_id, body.origin, body.text, embedder
            )
        except EmbeddingError:
            raise HTTPException(502, "向量化失败，文本已保存，请重新导入重试") from None
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        return {"id": document_id}

    @app.delete("/api/characters/{character_id}/documents/{document_id}", status_code=204)
    async def delete_document(character_id: str, document_id: str, user_id: UserId) -> None:
        await owned_character(character_id, user_id)
        if not await backend.documents.delete(user_id, character_id, document_id):
            raise HTTPException(404, "文档不存在")

    @app.get("/api/characters/{character_id}/avatar")
    async def character_avatar(character_id: str, user_id: UserId) -> Response:
        character = await owned_character(character_id, user_id)
        if not character.avatar_url:
            raise HTTPException(404, "头像不存在")
        try:
            content, content_type = await fetch_avatar(character.avatar_url)
        except InvalidAvatar:
            raise HTTPException(502, "头像无法获取") from None
        return Response(content, media_type=content_type, headers={
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, max-age=300",
        })

    @app.put("/api/characters/{character_id}")
    async def update_character(character_id: str, body: CharacterInput, user_id: UserId) -> dict:
        character = await backend.character_repository.update(
            user_id, character_id, **body.settings()
        )
        if character is None:
            raise HTTPException(404, "角色不存在")
        return shown_character(character)

    @app.delete("/api/characters/{character_id}", status_code=204)
    async def delete_character(character_id: str, user_id: UserId) -> None:
        await owned_character(character_id, user_id)
        await calls.hang_up(user_id, character_id=character_id)
        if not await backend.character_repository.delete(user_id, character_id):
            raise HTTPException(404, "角色不存在")


    @app.get("/api/characters/{character_id}/affinity")
    async def affinity(character_id: str, user_id: UserId) -> dict | None:
        """Her affinity with the user now, by tier only, and when the cooldown ends if she
        is in one; null while affinity is off."""
        await owned_character(character_id, user_id)
        status = await backend.affinities.status(user_id, character_id)
        return status and status.shown()

    @app.get("/api/memories")
    async def list_memories(user_id: UserId) -> list[dict]:
        """Newest first, each with the name of the character it was told to and whether
        it has been superseded (ADR-0014)."""
        return [
            {
                "id": m.id,
                "text": m.text,
                "source_character_id": m.source_character_id,
                "source_character_name": m.source_character_name,
                "created_at": m.created_at,
                "superseded": m.superseded_by is not None,
            }
            for m in await memory.entries(user_id)
        ]

    @app.delete("/api/memories/{memory_id}", status_code=204)
    async def delete_memory(memory_id: int, user_id: UserId) -> None:
        if not await memory.delete(user_id, memory_id):
            raise HTTPException(404, "记忆不存在")

    @app.delete("/api/memories", status_code=204)
    async def clear_memories(user_id: UserId) -> None:
        await memory.clear(user_id)

    @app.post("/api/conversations", status_code=201)
    async def create_conversation(body: NewConversation, user_id: UserId) -> dict:
        await owned_character(body.character_id, user_id)
        return asdict(await store.create_conversation(user_id, body.character_id))

    @app.get("/api/conversations")
    async def list_conversations(character_id: str, user_id: UserId) -> list[dict]:
        """Her conversations with the user, newest first, the first her current one; each
        with its title, null if it has none, the last thing in it, as the conversation list
        shows it, and whether she has ended it. Those being named are waited for a while."""
        await titles.settle(user_id)
        await owned_character(character_id, user_id)
        listed = await store.list_conversations(user_id, character_id)
        return [
            asdict(c) | {"last_message": last_shown(last), "ended": ended}
            for c, last, ended in listed
        ]

    @app.get("/api/conversations/latest")
    async def latest_conversations(user_id: UserId) -> list[dict]:
        """For the conversation list: each character's newest conversation with the user, the
        last thing in it, a message, a conversation event or a reach-out (null while it has
        none), whether it has a reach-out the user has not seen, and whether she has a letter
        to the user they have not read, in one request."""
        return [
            {
                "character_id": c.character_id,
                "conversation_id": c.id,
                "created_at": c.created_at,
                "last_message": last_shown(last),
                "unseen_reach_out": unseen,
            }
            for c, last, unseen in await store.latest_conversations(user_id)
        ]

    @app.delete("/api/conversations/{conversation_id}", status_code=204)
    async def delete_conversation(conversation_id: str, user_id: UserId) -> None:
        """Delete a past conversation (GLOSSARY.md「历史对话」), for good; her current one is
        not deleted (409)."""
        conversation = await conversation_or_404(conversation_id, user_id)
        try:
            await store.delete_conversation(conversation)
        except IsCurrent:
            raise HTTPException(409, "当前对话不能删除") from None

    @app.get("/api/conversations/{conversation_id}/messages")
    async def list_messages(conversation_id: str, user_id: UserId) -> list[dict]:
        """The conversation's record: its messages, conversation events and reach-outs, in
        order. The user reads it: its reach-outs are seen from now on."""
        conversation = await conversation_or_404(conversation_id, user_id)
        return [recorded(entry) for entry in await store.read_by_user(conversation.id)]

    @app.post("/api/conversations/{conversation_id}/turns")
    async def text_turn(
        conversation_id: str,
        body: TurnInput,
        user_id: UserId,
        device_timezone: DeviceTimezone = None,
    ) -> StreamingResponse:
        conversation = await conversation_or_404(conversation_id, user_id)
        brought = body.own_keys.brought() if body.own_keys else BroughtKeys()
        # Cancelled meanwhile, what is let in never runs, so is settled as left.
        admission = await admissions.admitted(
            admissions.turn(user_id, conversation.character_id, brought),
            lambda let_in: TurnOutcome(let_in.recording, let_in.settle).over(
                cut_short_by_failure=False
            ),
        )
        outcome = TurnOutcome(admission.recording, admission.settle)

        async def events() -> AsyncIterator[str]:
            # Closed as the response is, so that the turn is no longer under way once the user
            # has gone (`Store.taking_turn`).
            async with outcome.running():
                async with aclosing(engine.turn(
                    conversation, body.text, admission.llms, device_timezone,
                )) as turn:
                    async for event in turn:
                        outcome.see(event)
                        if isinstance(event, SegmentDelta):
                            outcome.began_speaking()  # the reply's first words have appeared
                        if isinstance(event, SegmentComplete | SpeechDelta | TurnJudged):
                            continue
                        yield _sse(shown(event))

        return _TurnResponse(events(), lambda: outcome.over(cut_short_by_failure=False))


    return app


class _TurnResponse(StreamingResponse):
    """A text turn's events, `end` called once they are sent or the page is gone, even
    gone before they began, when the stream of them never runs."""

    def __init__(self, events: AsyncIterator[str], end: Callable[[], Awaitable[None]]) -> None:
        super().__init__(
            events,
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
        self._end = end

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            await self._end()


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
