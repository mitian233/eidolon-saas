"""Test doubles for external services."""

import asyncio
import hashlib
import io
import json
import secrets
from collections.abc import AsyncGenerator, AsyncIterator, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast, get_args
import zipfile
from http import HTTPStatus
from urllib.parse import parse_qs, unquote, urlencode, urlsplit
from xml.sax.saxutils import escape

import httpx
from websockets.asyncio.server import Server, ServerConnection, serve
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Request, Response
from pipecat.frames.frames import (
    Frame,
    ProposedUserStartedSpeakingFrame,
    ProposedUserStoppedSpeakingFrame,
    TranscriptionFrame,
    TTSAudioRawFrame,
)
from pipecat.services.settings import STTSettings, TTSSettings
from pipecat.services.stt_service import STTService
from pipecat.services.tts_service import TTSService
from pipecat.utils.time import time_now_iso8601

from eidolon.assembly import Backend, build
from eidolon.billing import bill
from eidolon.call import SONIOX_FOLLOW_ON_TIMEOUT, Hearing
from eidolon.characters import Character
from eidolon.config import (
    BailianRegion,
    ChatModelSettings,
    LLMProtocol,
    LLMSettings,
    ReasoningEffort,
    Settings,
    SttKey,
    SttProvider,
)
from eidolon.config import EmbeddingSettings, RerankSettings
from eidolon.embedding import Document, EmbeddingError
from eidolon.rerank import RerankError
from eidolon.emotion import _EMOTION_OPTIONS, _NOD_OPTIONS, Emotion, EmotionAnswer, Nod
from eidolon.identity import Identity, IdentityError, ProviderName
from eidolon.llm import (
    ChatLLM,
    ChatMessage,
    ChatModels,
    LLMError,
    Reasoning,
    Streamed,
    Tool,
    ToolCall,
)
from eidolon.llm.providers import check_chat_models
from eidolon.own_keys import OwnKeyRejected, OwnRetrievalService
from eidolon.s3 import Bucket, S3Settings
from eidolon.affinity_judge import LEVEL as AFFINITY_LEVEL
from eidolon.affinity_judge import CONSIDERATE_QUESTION, MANIPULATION, OUT_OF_LINE
from eidolon.judge import SAID, JudgeError

from eidolon.retrieval import Need

START = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)


class FakeClock:
    """A clock the tests move forward themselves."""

    def __init__(self, now: datetime = START) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)


DEPLOYER_KEY = "test-key"
"""The deployer's chat model key in the tests' settings."""


HANG = object()
"""A chunk in a FakeLLM reply where the model stops sending but never finishes."""


def system_of(prompt: Sequence[ChatMessage]) -> str:
    """What the system messages `prompt` opens with tell the model, as one text: joined by
    a blank line, as the Chat Completions adapter sends them."""
    opening: list[str] = []
    for message in prompt:
        if message.role != "system":
            break
        opening.append(message.content)
    return "\n\n".join(opening)


def context_of(prompt: Sequence[ChatMessage]) -> str:
    """What changes from turn to turn that `prompt` tells the model: the system message
    just before what the user is saying now, its last user message."""
    last = max(i for i, m in enumerate(prompt) if m.role == "user")
    context = prompt[last - 1]
    assert context.role == "system", "no system message before what the user is saying"
    return context.content


class FakeLLM:
    """Records every prompt it receives, the tools offered with it, whether calling them
    was forbidden (`forbidden`) and the API key it came with (`keys`), and replies from a
    script.

    Each scripted reply is a list of text chunks, tool calls and reasoning, streamed in
    order, so tests can split the structured reply at awkward boundaries or have the model
    call a tool; a reply that is an LLMError is raised instead, as a failing service would,
    and a chunk that is one, part-way through the reply. With
    a `delay`, it waits that many seconds before each chunk after the first, as a slow
    model would; at `HANG` it waits forever, and at an `asyncio.Event` till it is set.
    Unless reached through a FakeLLMService, it is the deployer's model. With `tokens`, each
    reply it finishes says it was billed that many input and output tokens, and, with a
    third, that many of the input read from the prompt cache, as a real service does;
    without, it says nothing.
    """

    def __init__(
        self,
        *replies: Sequence[Streamed | object] | LLMError,
        delay: float = 0,
        tokens: tuple[int, int] | tuple[int, int, int] | None = None,
    ) -> None:
        self._replies = [r if isinstance(r, LLMError) else list(r) for r in replies]
        self._delay = delay
        self._tokens = tokens
        self.prompts: list[list[ChatMessage]] = []
        self.tools: list[list[Tool]] = []
        self.forbidden: list[bool] = []
        self.keys: list[str] = []

    def stream(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[Tool] = (),
        *,
        forbid_calls: bool = False,
    ) -> AsyncIterator[Streamed]:
        return self.stream_with(DEPLOYER_KEY, messages, tools, forbid_calls=forbid_calls)

    async def stream_with(
        self,
        key: str,
        messages: Sequence[ChatMessage],
        tools: Sequence[Tool] = (),
        *,
        forbid_calls: bool = False,
    ) -> AsyncIterator[Streamed]:
        self.prompts.append(list(messages))
        self.tools.append(list(tools))
        self.forbidden.append(forbid_calls)
        self.keys.append(key)
        if not self._replies:
            raise AssertionError("FakeLLM ran out of scripted replies")
        reply = self._replies.pop(0)
        if isinstance(reply, LLMError):
            raise reply
        for i, chunk in enumerate(reply):
            if i and self._delay:
                await asyncio.sleep(self._delay)
            if chunk is HANG:
                await asyncio.Event().wait()
            if isinstance(chunk, asyncio.Event):
                await chunk.wait()
                continue
            if isinstance(chunk, LLMError):
                raise chunk
            assert isinstance(chunk, str | ToolCall | Reasoning)
            yield chunk
        if self._tokens is not None:
            bill("tokens", *self._tokens)

    async def aclose(self) -> None:
        pass


class FakeLLMService:
    """Stands in for the LLM services users bring their own keys to: every model opened on
    it replies from `llm`'s script, recording the key it came with there and the reasoning
    effort it was opened with (`efforts`). Records what was tried before saving
    (`checked`); a key in `rejects` fails the try with that message. The try is the real
    check of the chat model at each of its efforts, on models that pass it without using
    up the script, recording the effort each was tried at (`efforts_checked`); an effort in
    `refused_efforts` fails it with that message."""

    def __init__(self, llm: FakeLLM | None = None) -> None:
        self.llm = llm or FakeLLM()
        self.checked: list[ChatModelSettings] = []
        self.opened: list[LLMSettings] = []
        self.rejects: dict[str, str] = {}
        self.refused_efforts: dict[str, str] = {}
        self.efforts: list[ReasoningEffort | None] = []
        self.efforts_checked: list[ReasoningEffort | None] = []
        self.listed: list[tuple[LLMProtocol, str, str]] = []
        self.models: list[str] = ["model-a", "model-b"]

    def open(self, settings: LLMSettings) -> ChatLLM:
        self.opened.append(settings)
        return _KeyedLLM(self, settings)

    async def list_models(self, protocol: LLMProtocol, base_url: str, api_key: str) -> list[str]:
        """`models`, recording where it was asked and with which key (`listed`); a key in
        `rejects` fails with that message, repeating the key as a service may."""
        self.listed.append((protocol, base_url, api_key))
        if api_key in self.rejects:
            raise LLMError(f"{self.rejects[api_key]} ({api_key})")
        return list(self.models)

    async def check(self, settings: ChatModelSettings) -> None:
        self.checked.append(settings)
        if settings.text.api_key in self.rejects:
            raise LLMError(self.rejects[settings.text.api_key])
        models = ChatModels(_TriedLLM(self, settings.text), _TriedLLM(self, settings.call))
        await check_chat_models(models, settings)

    async def aclose(self) -> None:
        pass


@dataclass
class ScriptedUserLLMService:
    source: FakeLLMService
    scripted: "FakeServiceClients"

    def open(self, settings: LLMSettings) -> ChatLLM:
        self.source.opened.append(settings)
        return _KeyedLLM(self.source, settings, self.scripted)

    async def check(self, settings: ChatModelSettings) -> None:
        await self.source.check(settings)

    async def list_models(self, protocol: LLMProtocol, base_url: str, api_key: str) -> list[str]:
        return await self.source.list_models(protocol, base_url, api_key)

    async def aclose(self) -> None:
        await self.source.aclose()


class _KeyedLLM:
    def __init__(self, service: FakeLLMService, settings: LLMSettings, scripted: "FakeServiceClients | None" = None) -> None:
        self._service = service
        self._settings = settings
        self._scripted = scripted

    async def stream(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[Tool] = (),
        *,
        forbid_calls: bool = False,
    ) -> AsyncIterator[Streamed]:
        self._service.efforts.append(self._settings.reasoning_effort)
        scripted = self._scripted
        if scripted is not None and self._settings.model == "test-user-chat" and self._settings.reasoning_effort == "low":
            body = json.loads(messages[-1].content)
            answer = await scripted.user_judge.answer(self._settings.api_key, body["state"], body["questions"])
            # LLMJudge expects every option, including zero-probability ones.
            for name, question in body["questions"].items():
                if question["type"] != "noul":
                    options = [str(i) for i in range(len(question["criteria"]))] if question["type"] == "score" else question["criteria"]
                    probabilities = answer[name].setdefault("probabilities", {})
                    for option in options:
                        probabilities.setdefault(option, 0.0)
            yield json.dumps(answer, ensure_ascii=False)
            return
        if scripted is not None and self._settings.model == "test-user-memory":
            async for chunk in scripted.background.stream(messages, tools, forbid_calls=forbid_calls):
                yield chunk
            return
        llm = scripted.llm if scripted is not None and self._settings.model == "test-user-chat" else self._service.llm
        async for chunk in llm.stream_with(self._settings.api_key, messages, tools, forbid_calls=forbid_calls):
            yield chunk

    async def aclose(self) -> None:
        pass


class _TriedLLM:
    def __init__(self, service: FakeLLMService, settings: LLMSettings) -> None:
        self._service = service
        self._settings = settings

    async def stream(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[Tool] = (),
        *,
        forbid_calls: bool = False,
    ) -> AsyncIterator[Streamed]:
        effort = self._settings.reasoning_effort
        if effort is not None and effort in self._service.refused_efforts:
            raise LLMError(self._service.refused_efforts[effort])
        self._service.efforts_checked.append(effort)
        return
        yield

    async def aclose(self) -> None:
        pass


class FakeServiceClients:
    """Stands in for making the deployer's service clients from their configuration (see
    `service_clients.ServiceClients`), `.env`'s as well as the admin console's: records
    the settings of every chat model it made (`opened`) and closed (`closed`), as text
    turns use it. Every chat model it makes, as text turns and calls use it, replies from
    `llm`'s script, recording the key it came with there (or is `llm`, if it is not a
    `FakeLLM`) and the reasoning effort it was made with (`efforts`), but passes the
    connectivity check without using up the script, recording the effort it was checked
    at (`efforts_checked`); a key in `rejects`, or an effort in `refused_efforts`, fails
    every request, the check too, with that message.

    Memory models it makes (`memory_opened`, closed in `closed` too) answer from
    `background`, recording the key each request came with (`memory_keys`). Judge models
    it makes (`judges_opened`, `judges_closed`) answer every question as `judge` does,
    recording the key each question came with there."""

    def __init__(self, llm: FakeLLM | None = None) -> None:
        self.llm = llm or FakeLLM()
        self.opened: list[LLMSettings] = []
        self.closed: list[LLMSettings] = []
        self.rejects: dict[str, str] = {}
        self.refused_efforts: dict[str, str] = {}
        self.efforts: list[ReasoningEffort | None] = []
        self.efforts_checked: list[ReasoningEffort | None] = []
        self.background = FakeBackgroundLLM()
        self.memory_opened: list[LLMSettings] = []
        self.memory_keys: list[str] = []
        self.user_judge = FakeJudgeModel()
        self.listed: list[tuple[str, LLMProtocol, str, str]] = []
        self.models: list[str] = ["model-a", "model-b"]

    def chat_models(self, settings: ChatModelSettings) -> ChatModels:
        self.opened.append(settings.text)
        return ChatModels(
            _ConfiguredLLM(self, settings.text, self.closed),
            _ConfiguredLLM(self, settings.call, []),  # closed with the text turns' one
        )

    def memory_llm(self, settings: LLMSettings) -> ChatLLM:
        self.memory_opened.append(settings)
        return _ConfiguredLLM(self, settings, self.closed, memory=True)


    async def list_models(
        self, service: Literal["chat_llm", "memory_llm"], protocol: LLMProtocol,
        base_url: str, api_key: str,
    ) -> list[str]:
        """`models`, recording where it was asked and with which key (`listed`); a key in
        `rejects` fails with that message."""
        self.listed.append((service, protocol, base_url, api_key))
        if api_key in self.rejects:
            raise LLMError(self.rejects[api_key])
        return list(self.models)


class _ConfiguredLLM:
    def __init__(
        self,
        clients: FakeServiceClients,
        settings: LLMSettings,
        closed: list[LLMSettings],
        memory: bool = False,
    ) -> None:
        self._clients = clients
        self._settings = settings
        self._closed = closed
        self._memory = memory

    async def stream(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[Tool] = (),
        *,
        forbid_calls: bool = False,
    ) -> AsyncIterator[Streamed]:
        key, effort = self._settings.api_key, self._settings.reasoning_effort
        if key in self._clients.rejects:
            raise LLMError(self._clients.rejects[key])
        if effort is not None and effort in self._clients.refused_efforts:
            raise LLMError(self._clients.refused_efforts[effort])
        if any(t.name == "ping" for t in tools):  # the connectivity check
            if not self._memory:
                self._clients.efforts_checked.append(effort)
            return
        if self._memory:
            self._clients.memory_keys.append(key)
            async for item in self._clients.background.stream(messages, tools):
                yield item
            return
        self._clients.efforts.append(effort)
        llm = self._clients.llm
        stream = (
            llm.stream_with(key, messages, tools, forbid_calls=forbid_calls)
            if isinstance(llm, FakeLLM)
            else llm.stream(messages, tools, forbid_calls=forbid_calls)
        )
        async for item in stream:
            yield item

    async def aclose(self) -> None:
        self._closed.append(self._settings)


@dataclass(frozen=True)
class Judging:
    """A script for what the judge model makes of one turn's affinity: how likely each
    level is (each level the only one by default, `level`), whether it is out of line,
    whether it tries to dictate her affinity, which of the considerate question's three it
    is if that is asked (unrelated by default); or that the request fails."""

    levels: Mapping[int, float] = field(default_factory=lambda: {2: 1.0})
    out_of_line: bool = False
    manipulation: bool = False
    fails: bool = False
    considerate: int = 1

    def answers(self) -> dict[str, Any]:
        return {
            AFFINITY_LEVEL: {"probabilities": {str(n): p for n, p in self.levels.items()}},
            OUT_OF_LINE: {"noul": 1.0 if self.out_of_line else 0.0},
            MANIPULATION: {"noul": 1.0 if self.manipulation else 0.0},
        }


def level(
    n: int,
    *,
    out_of_line: bool = False,
    manipulation: bool = False,
    fails: bool = False,
    considerate: int = 1,
) -> Judging:
    """A turn judged at level `n` for sure."""
    return Judging({n: 1.0}, out_of_line, manipulation, fails, considerate)


class FakeJudgeModel:
    """Stands in for the judge model's service: answers what each turn needs as the script
    `needs` says, her emotion in each segment as `feels` does; without them, the retrieval
    questions with the probabilities in `retrieval`, her emotion with those in `emotion`
    and the nod with neither. Answers each turn's affinity questions as the next of
    `judgings` says, as having no effect once they run out, recording what the user said
    (`affinity_asked`). Records the key each request came with and what it asked
    (`asked`: "turn", with or without affinity's questions, "affinity" for those alone,
    "emotion" or "check"), and everything it was told of each (`states`) and asked of it
    (`questions`)."""

    def __init__(self) -> None:
        self.needs: FakeJudge | None = None
        self.feels: FakeJudge | None = None
        self.retrieval = {"needs_retrieval": 0.1, "recall": 0.1, "about_producer": 0.1}
        self.emotion = {"平静": 1.0}
        self.judgings: list[Judging] = []
        self.asked: list[tuple[str, str]] = []
        self.affinity_asked: list[str] = []
        self.states: list[dict[str, Any]] = []
        self.questions: list[dict[str, dict]] = []

    async def answer(
        self, key: str, state: dict[str, Any], questions: dict[str, dict]
    ) -> dict[str, Any]:
        kind = (
            "turn" if "recall" in questions
            else "affinity" if AFFINITY_LEVEL in questions
            else "emotion" if "emotion" in questions
            else "check"
        )
        self.asked.append((key, kind))
        self.states.append(state)
        self.questions.append(questions)
        scripted: dict[str, Any] = {}
        if AFFINITY_LEVEL in questions:
            self.affinity_asked.append(state[SAID])
            judging = self.judgings.pop(0) if self.judgings else Judging()
            if judging.fails:
                raise JudgeError("fake judge model is down")
            scripted = judging.answers()
            if CONSIDERATE_QUESTION in questions:
                scripted[CONSIDERATE_QUESTION] = {"probabilities": {str(judging.considerate): 1.0}}
        if kind == "turn" and self.needs is not None:
            return await self.needs.need(state) | scripted
        if kind == "emotion" and self.feels is not None:
            return await self.feels.feel(state)
        return {
            name: {"noul": self.retrieval.get(name, 0.5)}
            if q.get("type") == "noul"
            else {"probabilities": self.emotion if name == "emotion" else {"都不是": 1.0}}
            for name, q in questions.items()
            if name not in scripted
        } | scripted


USER_LLM = {"base_url": "https://user.example/v1", "api_key": "test-user-secret", "model": "test-user-chat"}
JUDGED_KEYS = {
    "llm": USER_LLM,
    "memory_llm": USER_LLM | {"model": "test-user-memory"},
    "judge_enabled": True,
}
RETRIEVAL_KEYS = JUDGED_KEYS | {
    "embedding": {"base_url": "https://user.example/v1", "api_key": "user-vector-secret", "model": "test-user-embedding", "dimensions": 128},
    "rerank": {"base_url": "https://user.example/v1", "api_key": "user-rerank-secret", "model": "Qwen/Qwen3-Reranker-0.6B"},
}


class FakeUserRetrieval(OwnRetrievalService):
    """External responses for user endpoints explicitly named in test requests."""

    def __init__(self, embedder=None, reranker=None) -> None:
        super().__init__(public_only=False)
        self.embedding_script = embedder or FakeEmbedder()
        self.rerank_script = reranker or FakeReranker()

    def embedder(self, settings: EmbeddingSettings):
        if settings.model == "test-user-embedding":
            return self.embedding_script
        return super().embedder(settings)

    def reranker(self, settings: RerankSettings):
        if settings.api_key == "user-rerank-secret":
            return self.rerank_script
        return super().reranker(settings)

_test_registries: dict[int, Mapping[str, Character]] = {}


def registry_of(backend: Backend) -> Mapping[str, Character]:
    """The test registry `build_faked` was given for this backend, for seeding its
    characters to more users (`conftest.seed_characters`); empty without one."""
    return _test_registries.get(id(backend), {})


def build_faked(
    settings: Settings,
    llm: FakeLLM | None = None,
    *,
    clients: "FakeServiceClients | None" = None,
    background_llm: "FakeBackgroundLLM | None" = None,
    retrieval_judge: "FakeJudge | None" = None,
    emotion_judge: "FakeJudge | None" = None,
    characters: Mapping[str, Character] | None = None,
    **services: Any,
) -> Backend:
    """`build`, with the deployer's models made by `clients` (new ones by default):
    playing the characters from `llm`'s script, writing down memories from
    `background_llm`'s, judging what turns need from `retrieval_judge`'s and her emotions
    from `emotion_judge`'s, either judging both if only one is given. With a judge
    script, `.env` has the judge model `FAKE_JUDGE` unless it has one. `characters` seeds
    the backend's shared mapping with the test registry's definitions, as the database
    would at startup. Any other keyword is an outside service passed on to `build`."""
    clients = clients or FakeServiceClients()
    if llm is not None:
        clients.llm = llm
    if background_llm is not None:
        clients.background = background_llm
    clients.user_judge.needs = retrieval_judge or emotion_judge
    clients.user_judge.feels = emotion_judge or retrieval_judge
    own = services.get("own_llm_service")
    if own is None:
        own = FakeLLMService()
        services["own_llm_service"] = own
    if isinstance(own, FakeLLMService):
        services["own_llm_service"] = ScriptedUserLLMService(own, clients)
    if "own_retrieval_service" not in services:
        services["own_retrieval_service"] = FakeUserRetrieval(services.get("embedder"), services.get("reranker"))
    backend = build(settings, clients=clients, **services)
    _test_registries[id(backend)] = characters or {}
    if characters:
        backend.characters.update(characters)
    return backend


class FakeBackgroundLLM:
    """Stands in for the background model: answers each request with the next scripted
    reply, and with no memories once the script runs out; a reply that is an exception
    is raised instead, one that is a function is called with the prompt, as one text, for
    the answer. Records every prompt it receives. With a `gate`, it answers only once the
    gate is open, like a slow model."""

    NOTHING = '{"memories": []}'

    def __init__(
        self, *replies: str | Exception | Callable[[str], str], gate: asyncio.Event | None = None
    ) -> None:
        self._replies = list(replies)
        self._gate = gate
        self.prompts: list[list[ChatMessage]] = []

    async def stream(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[Tool] = (),
        *,
        forbid_calls: bool = False,
    ) -> AsyncIterator[Streamed]:
        self.prompts.append(list(messages))
        reply = self._replies.pop(0) if self._replies else self.NOTHING
        if callable(reply):
            reply = reply("\n".join(m.content for m in messages))
        if self._gate is not None:
            await self._gate.wait()
        if isinstance(reply, Exception):
            raise reply
        for i in range(0, len(reply), 7):  # in chunks, as a streaming model would
            yield reply[i : i + 7]

    async def aclose(self) -> None:
        pass


def zipped(files: dict[str, bytes]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return out.getvalue()


DEPLOYER_SONIOX_KEY = "deployer-soniox-key"
DEPLOYER_FISH_KEY = "deployer-fish-key"
"""The deployer's speech keys in the tests' settings."""


class FakeSTT(STTService):
    """Stands in for speech recognition in one call, on `key`: ignores the microphone and
    hears what the test says the user said, the way Soniox reports an utterance."""

    def __init__(self, key: SttKey) -> None:
        super().__init__(ttfs_p99_latency=0.1, settings=STTSettings(model=None, language=None))
        self.key = key
        self.api_key = key.api_key

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame | None, None]:
        yield None

    async def hear(self, text: str) -> None:
        """The user said `text`: an utterance starts, is transcribed, and ends."""
        await self.broadcast_frame(ProposedUserStartedSpeakingFrame)
        await self.push_frame(TranscriptionFrame(text, "user", time_now_iso8601(), finalized=True))
        await self.broadcast_frame(ProposedUserStoppedSpeakingFrame)

    async def start_talking(self) -> None:
        """The user starts saying something, which never comes to any words."""
        await self.broadcast_frame(ProposedUserStartedSpeakingFrame)

    async def break_down(self, error: str = "fake speech recognition is down") -> None:
        """Fail as a rejected API key would: for good, saying `error`."""
        await self.push_error(error, force_treat_as_permanent=True)


class FakeTTS(TTSService):
    """Stands in for Fish Audio in one call, on `api_key` with `model`: records what it is
    asked to voice, and in which voice, and says a moment of silence for each."""

    def __init__(self, api_key: str, model: str, voice_id: str, sample_rate: int) -> None:
        super().__init__(
            sample_rate=sample_rate, settings=TTSSettings(model=model, voice=None, language=None)
        )
        self.api_key = api_key
        self.model = model
        self.voice_id = voice_id
        self.voiced: list[str] = []

    async def break_down(self, error: str = "fake speech synthesis is down") -> None:
        """Fail as a rejected API key would: for good, saying `error`."""
        await self.push_error(error, force_treat_as_permanent=True)

    async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame | None, None]:
        self.voiced.append(text)
        samples = self.sample_rate // 10
        yield TTSAudioRawFrame(b"\0\0" * samples, self.sample_rate, 1, context_id=context_id)


class FakeSpeech:
    """Stands in for speech recognition and Fish Audio: the speech services of each call
    started, in order, each with the key it was made with, recognition waiting
    `follow_on_timeout` for follow-ons (Soniox's, unless set). Set `down` to have the
    services fail to be made at all. Records the keys tried before saving, by the service
    they are for (`checked`: "tts", "soniox" or "bailian"), and the model each key for
    Fish Audio was tried with (`tts_models`); a key in `rejects` fails its
    try with that message. A DashScope key works in its region in `regions`, Beijing if
    not there. Records, for each service made or key tried, whether it was on a user's own
    key (`own`: ("stt" | "tts" | "check_stt" | "check_tts", own)), and each word voiced as
    the service status tries Fish Audio, by key, model and voice (`voiced`), failing on a
    key in `rejects` as well."""

    def __init__(self) -> None:
        self.own: list[tuple[str, bool]] = []
        self.follow_on_timeout = SONIOX_FOLLOW_ON_TIMEOUT
        self.stts: list[FakeSTT] = []
        self.ttss: list[FakeTTS] = []
        self.down = False
        self.checked: list[tuple[str, str]] = []
        self.tts_models: list[str] = []
        self.rejects: dict[str, str] = {}
        self.regions: dict[str, BailianRegion] = {}
        self.voiced: list[tuple[str, str, str]] = []

    def stt(self, key: SttKey, *, own: bool) -> Hearing:
        self.own.append(("stt", own))
        if self.down:
            raise RuntimeError("fake speech services are down")
        self.stts.append(FakeSTT(key))
        return Hearing(self.stts[-1], self.follow_on_timeout)

    def tts(
        self, api_key: str, model: str, voice_id: str, sample_rate: int, *, own: bool
    ) -> FakeTTS:
        self.own.append(("tts", own))
        self.ttss.append(FakeTTS(api_key, model, voice_id, sample_rate))
        return self.ttss[-1]

    async def check_stt(self, provider: SttProvider, api_key: str, *, own: bool) -> SttKey:
        self.own.append(("check_stt", own))
        self._try(provider, api_key)
        if provider == "bailian":
            return SttKey(provider, api_key, self.regions.get(api_key, "beijing"))
        return SttKey(provider, api_key)

    async def check_tts(self, api_key: str, model: str, *, own: bool) -> None:
        self.own.append(("check_tts", own))
        self.tts_models.append(model)
        self._try("tts", api_key)

    async def voice_a_word(self, api_key: str, model: str, voice_id: str) -> None:
        self.voiced.append((api_key, model, voice_id))
        if api_key in self.rejects:
            raise RuntimeError(self.rejects[api_key])

    def _try(self, service: str, api_key: str) -> None:
        self.checked.append((service, api_key))
        if api_key in self.rejects:
            raise OwnKeyRejected(self.rejects[api_key])


@dataclass
class DashScopeTask:
    """A recognition task DashScope ran: in which region, the `run-task` that started it,
    each packet of audio it was sent, and whether it was told to finish."""

    region: BailianRegion
    run_task: dict
    audio: list[bytes] = field(default_factory=list)
    finished: bool = False


class FakeDashScope:
    """Stands in for DashScope's realtime speech recognition (阿里云百炼) in both its
    regions, over a real WebSocket on localhost: a key in `keys` works only in its region,
    and is refused anywhere else at the handshake (HTTP 401), as DashScope does. A task
    with a model in `not_enabled` fails before it starts. Once a task starts it is sent the
    `sentences` given, each as a `result-generated`, and then fails with `failure`
    (`error_code`, `error_message`), if set; told to finish, it finishes. Set `down` to
    have every handshake fail (HTTP 503). Records every handshake's region (`handshakes`)
    and every task started (`tasks`)."""

    def __init__(self) -> None:
        self.keys: dict[str, BailianRegion] = {}
        self.not_enabled: set[str] = set()
        self.sentences: list[dict] = []
        self.failure: tuple[str, str] | None = None
        self.down = False
        self.handshakes: list[BailianRegion] = []
        self.tasks: list[DashScopeTask] = []
        self.urls: dict[BailianRegion, str] = {}
        self._server: Server | None = None

    async def start(self) -> None:
        self._server = await serve(
            self._serve, "127.0.0.1", 0, process_request=self._handshake
        )
        port = self._server.sockets[0].getsockname()[1]
        self.urls = {r: f"ws://127.0.0.1:{port}/{r}" for r in get_args(BailianRegion)}

    async def aclose(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    def _handshake(self, connection: ServerConnection, request: Request) -> Response | None:
        region = _region(request.path)
        self.handshakes.append(region)
        if self.down:
            return connection.respond(HTTPStatus.SERVICE_UNAVAILABLE, "Service Unavailable\n")
        key = (request.headers.get("Authorization") or "").removeprefix("bearer ")
        if self.keys.get(key) != region:
            return connection.respond(HTTPStatus.UNAUTHORIZED, "Unauthorized\n")
        return None

    async def _serve(self, connection: ServerConnection) -> None:
        assert connection.request is not None
        region = _region(connection.request.path)
        task: DashScopeTask | None = None

        async def send(event: str, payload: dict | None = None, **header: str) -> None:
            assert task is not None
            task_id = task.run_task["header"]["task_id"]
            message = {
                "header": {"task_id": task_id, "event": event, "attributes": {}, **header},
                "payload": payload or {},
            }
            await connection.send(json.dumps(message, ensure_ascii=False))

        try:
            async for message in connection:
                if isinstance(message, bytes):
                    assert task is not None
                    task.audio.append(message)
                    continue
                request = json.loads(message)
                action = request["header"]["action"]
                if action == "run-task":
                    task = DashScopeTask(region, request)
                    if request["payload"]["model"] in self.not_enabled:
                        await send(
                            "task-failed", error_code="ModelNotFound",
                            error_message="Model not found (or not enabled)",
                        )
                        return
                    self.tasks.append(task)
                    await send("task-started")
                    for sentence in self.sentences:
                        await send("result-generated", {"output": {"sentence": sentence}})
                    if self.failure is not None:
                        code, why = self.failure
                        await send("task-failed", error_code=code, error_message=why)
                        return
                elif action == "finish-task":
                    assert task is not None
                    task.finished = True
                    await send("task-finished", {"output": {}})
                    return
        except ConnectionClosed:
            pass


def _region(path: str) -> BailianRegion:
    """The region a fake DashScope URL is of."""
    return cast(BailianRegion, path.strip("/"))


def sentence(text: str, end: bool = False, **fields: object) -> dict:
    """A sentence of DashScope's `result-generated`, as far as the recognition has heard it."""
    return {"sentence_id": 1, "text": text, "sentence_end": end, "words": []} | fields


class FakeIdentityProvider:
    """Stands in for Google or GitHub: the test says which identity the next sign-in there
    is (`will_identify`). Records the callback URL of every sign-in; set `down` to have it
    fail as an unreachable provider would."""

    AUTHORIZE_URL = "https://provider.invalid/authorize"

    def __init__(self, name: ProviderName) -> None:
        self.name: ProviderName = name
        self.callbacks: list[str] = []
        self.down = False
        self._identities: dict[str, Identity] = {}

    def will_identify(self, identity: Identity) -> str:
        """The code the provider will send back for this identity."""
        code = secrets.token_hex(4)
        self._identities[code] = identity
        return code

    def authorize_url(self, state: str, redirect_uri: str) -> str:
        query = urlencode({"provider": self.name, "state": state, "redirect_uri": redirect_uri})
        return f"{self.AUTHORIZE_URL}?{query}"

    async def identify(self, code: str, redirect_uri: str) -> Identity:
        self.callbacks.append(redirect_uri)
        if self.down:
            raise IdentityError(f"fake {self.name} is down")
        if code not in self._identities:
            raise IdentityError(f"fake {self.name} does not know the code {code}")
        return self._identities.pop(code)

    async def aclose(self) -> None:
        pass


class FakeEmbedder:
    """Embeds text as counts of a few keywords, so the nearest passages are the ones
    sharing the query's keywords. Records every document (its text, and its title in
    `titles`) and query it embeds; set `down` to have it fail as an unreachable service
    would, or set `documents_down` to have it fail embedding documents only. A query among
    `hanging` is never answered: whoever asked gives up on it, which
    is recorded (`abandoned`)."""

    KEYWORDS = (
        "鳩", "公園", "優勝", "長崎", "ちゃんぽん", "写真", "負け", "猫", "北海道",
        "destination", "ドーム", "WING",
    )

    def __init__(self, model: str = "fake-embedding") -> None:
        self.model = model
        self.documents: list[str] = []
        self.titles: list[str | None] = []
        self.queries: list[str] = []
        self.down = False
        self.documents_down = False
        self.hanging: set[str] = set()
        self.abandoned: list[str] = []

    async def embed_documents(self, documents: Sequence[Document]) -> list[list[float]]:
        if self.down or self.documents_down:
            raise EmbeddingError("fake embedding service is down")
        self.documents.extend(d.text for d in documents)
        self.titles.extend(d.title for d in documents)
        return [self._vector(d.text) for d in documents]

    async def embed_query(self, text: str) -> list[float]:
        if self.down:
            raise EmbeddingError("fake embedding service is down")
        self.queries.append(text)
        if text in self.hanging:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.abandoned.append(text)
                raise
        return self._vector(text)

    def _vector(self, text: str) -> list[float]:
        return [0.01] + [float(text.count(k)) for k in self.KEYWORDS]


class FakeJudge:
    """A script for the judge model (`FakeJudgeModel.needs` and `.feels`): every turn
    needs `answer`, or the judge model fails if it is None; it answers the yes-or-no
    questions with probabilities of 1 or 0, which any thresholds read as `answer`.
    Records the character's name and the user's words of each turn asked about (`asked`).
    Once told to `hold`, it answers no turn (or none of those where the user said one of
    what it was told) until told to `let_go`, `holding` set while it is held up answering.

    Asked about segments' emotions, it answers each in turn from `emotions`: an answer,
    None to fail, or `HANG` never to answer; calm and neither nodding nor not once they
    run out. Records what it was told of each segment (`segments`)."""

    def __init__(
        self,
        answer: Need | None = "references",
        emotions: Sequence[EmotionAnswer | object | None] = (),
    ) -> None:
        self.answer: Need | None = answer
        self.asked: list[tuple[str, str]] = []  # (character's name, text)
        self.emotions = list(emotions)
        self.segments: list[AskedSegment] = []
        self.holding = asyncio.Event()
        self._held: asyncio.Event | None = None
        self._holding_for: set[str] = set()

    def hold(self, *said: str) -> None:
        self._held = asyncio.Event()
        self._holding_for = set(said)

    def let_go(self) -> None:
        if self._held is not None:
            self._held.set()
            self._held = None
        self.holding.clear()

    async def need(self, state: dict[str, Any]) -> dict[str, Any]:
        self.asked.append((state["角色"], state[SAID]))
        held = self._held
        if held is not None and (not self._holding_for or state[SAID] in self._holding_for):
            self.holding.set()
            await held.wait()
        if self.answer is None:
            raise JudgeError("fake judge model is down")
        yes = {"references": "needs_retrieval", "recall": "recall", "memories": "about_producer"}
        return {
            question: {"noul": 1.0 if yes.get(self.answer) == question else 0.0}
            for question in ("needs_retrieval", "recall", "about_producer")
        }

    async def feel(self, state: dict[str, Any]) -> dict[str, Any]:
        self.segments.append(AskedSegment(
            state["角色"], state["用户这句话"], state["这条回复前面几段"], state["这一段台词"],
            state["这一段的中文字幕"],
        ))
        answer = self.emotions.pop(0) if self.emotions else feeling("calm")
        if answer is None:
            raise JudgeError("fake judge model is down")
        if answer is HANG:
            await asyncio.Event().wait()
        assert isinstance(answer, EmotionAnswer)
        return {
            "emotion": {"probabilities": _named(answer.emotions, _EMOTION_OPTIONS)},
            "nod": {"probabilities": _named(answer.nods, _NOD_OPTIONS)},
        }


@dataclass(frozen=True)
class AskedSegment:
    """What the judge model was told of a segment: the character's name, what the user
    said, the reply's segments before it (each its Japanese and, in brackets, its
    subtitle; a note if there are none), and the segment's Japanese and subtitle."""

    character: str
    user_said: str
    before: list[str] | str
    ja: str
    zh: str


def _named(probabilities: Mapping[Any, float], options: Mapping[str, tuple[Any, str]]) -> dict:
    """`probabilities` by the names the judge model gives the options."""
    return {name: probabilities[o] for name, (o, _) in options.items() if o in probabilities}


def feeling(
    emotion: Emotion,
    probability: float = 0.9,
    nod: Nod | None = None,
    nod_probability: float = 0.9,
) -> EmotionAnswer:
    """An answer about a segment's emotion: `emotion` with `probability`, and `nod` with
    `nod_probability`, the rest shared out among the other options."""
    others = [e for e in get_args(Emotion) if e != emotion]
    emotions = {emotion: probability, **{e: (1 - probability) / len(others) for e in others}}
    no_nod = (1 - nod_probability) / 2
    nods: dict[Nod | None, float] = {"yes": no_nod, "no": no_nod, None: no_nod}
    nods[nod] = nod_probability
    return EmotionAnswer(emotions, nods)


class FakeReranker:
    """Ranks documents containing `prefer` first (scoring them 0.9), otherwise keeping the
    order it was given (scoring the rest `others`). Records every call; set `down` to have
    it fail them as a service still failing when asked again would."""

    def __init__(self, prefer: str = "", others: float = 0.5) -> None:
        self.prefer = prefer
        self.others = others
        self.calls: list[tuple[str, list[str]]] = []
        self.down = False

    async def rerank(
        self, query: str, documents: Sequence[str], top_n: int
    ) -> list[tuple[int, float]]:
        self.calls.append((query, list(documents)))
        if self.down:
            raise RerankError("fake rerank service is down")
        order = sorted(range(len(documents)), key=lambda i: self.prefer not in documents[i])
        return [(i, 0.9 if self.prefer in documents[i] else self.others) for i in order[:top_n]]


class KeywordReranker:
    """Scores each document by the first of its keywords it contains, others `rest`."""

    model = "fake-reranker"

    def __init__(self, scores: dict[str, float], rest: float = 0.05) -> None:
        self.scores = scores
        self.rest = rest

    async def rerank(
        self, query: str, documents: Sequence[str], top_n: int
    ) -> list[tuple[int, float]]:
        scored = [
            (i, next((s for k, s in self.scores.items() if k in d), self.rest))
            for i, d in enumerate(documents)
        ]
        return sorted(scored, key=lambda r: -r[1])[:top_n]


class FakeCatalog:
    """The price catalogs online, models.dev's and OpenRouter's, as `price_catalog` fetches
    them over HTTP (`transport`): what the test sets, empty by default, or failing. Counts
    the times both were fetched (`fetches`)."""

    def __init__(
        self, models_dev: dict | None = None, openrouter: list[dict] | None = None
    ) -> None:
        self.models_dev = models_dev or {}
        self.openrouter = openrouter or []
        self.failing = False
        self.fetches = 0

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        if self.failing:
            return httpx.Response(503, text="unavailable")
        if request.url.host == "models.dev":
            return httpx.Response(200, json=self.models_dev)
        assert request.url.host == "openrouter.ai", request.url
        self.fetches += 1
        return httpx.Response(200, json={"data": self.openrouter})


class FakeBucket:
    """An S3-compatible bucket at http://storage.test/<name> (path-style) that keeps what
    it is sent, lists two keys a page (those under the prefix asked for), and refuses
    unsigned requests."""

    def __init__(self, name: str = "stands") -> None:
        self.name = name
        self.objects: dict[str, tuple[bytes, dict[str, str]]] = {}
        self.puts: list[str] = []
        self.deletes: list[str] = []
        self.down = False
        self.lists_by_marker = False
        """List as the original List Objects does (Tencent COS): pages by `marker`,
        whatever `list-type` asks for."""

    def bucket(self, **settings) -> Bucket:
        return Bucket(
            S3Settings("http://storage.test", self.name, "key-id", "secret", **settings),
            transport=httpx.MockTransport(self.handle),
        )

    def handle(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            return httpx.Response(503, text="<Error><Code>SlowDown</Code></Error>")
        if not request.headers.get("Authorization", "").startswith("AWS4-HMAC-SHA256 Credential=key-id/"):
            return httpx.Response(403, text="<Error><Code>AccessDenied</Code></Error>")
        path = urlsplit(str(request.url)).path
        assert path == f"/{self.name}" or path.startswith(f"/{self.name}/"), path
        key = unquote(path.removeprefix(f"/{self.name}").removeprefix("/"))
        if request.method == "PUT":
            body = request.read()
            assert request.headers["x-amz-content-sha256"] == hashlib.sha256(body).hexdigest()
            assert request.headers["Content-Length"] == str(len(body))
            assert "Transfer-Encoding" not in request.headers
            self.objects[key] = (body, dict(request.headers))
            self.puts.append(key)
            return httpx.Response(200, headers={"ETag": f'"{hashlib.md5(body).hexdigest()}"'})
        if request.method == "DELETE":
            self.objects.pop(key, None)
            self.deletes.append(key)
            return httpx.Response(204)
        query = parse_qs(urlsplit(str(request.url)).query)
        assert request.method == "GET" and query["list-type"] == ["2"]
        prefix = query.get("prefix", [""])[0]
        keys = sorted(key for key in self.objects if key.startswith(prefix))
        if self.lists_by_marker:
            marker = query.get("marker", [""])[0]
            start = sum(1 for key in keys if key <= marker) if marker else 0
        else:
            start = int(query.get("continuation-token", ["0"])[0])
        page = keys[start : start + 2]
        more = start + 2 < len(keys)
        contents = "".join(
            f"<Contents><Key>{escape(key)}</Key>"
            f"<ETag>&quot;{hashlib.md5(self.objects[key][0]).hexdigest()}&quot;</ETag>"
            f"<Size>{len(self.objects[key][0])}</Size></Contents>"
            for key in page
        )
        token = f"<NextContinuationToken>{start + 2}</NextContinuationToken>" if more else ""
        if self.lists_by_marker:
            token = f"<NextMarker>{escape(page[-1])}</NextMarker>" if more else ""
        return httpx.Response(
            200,
            text='<?xml version="1.0" encoding="UTF-8"?>'
            '<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
            f"<IsTruncated>{'true' if more else 'false'}</IsTruncated>{token}{contents}</ListBucketResult>",
        )
