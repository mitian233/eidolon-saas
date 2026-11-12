"""Post-turn jobs keep outcomes, never credentials, and run only in the API process."""

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from eidolon import database
from eidolon.characters import Character
from eidolon.config import Settings
from eidolon.data_access import Database
from eidolon.llm import LLMError
from eidolon.memory import Memories
from eidolon.store import Store
from tests.conftest import ClientFactory
from tests.fakes import FakeBackgroundLLM, FakeEmbedder, FakeLLM, FakeReranker
from tests.test_memories import NOW, TZ, World
from tests.test_shared_memory import CAT, memorized
from tests.test_text_turn import send_turn, start_conversation


@pytest.fixture
async def api_database(
    database_target: Path | str, settings: Settings, monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[Database]:
    if isinstance(database_target, str):
        monkeypatch.setenv("DATABASE_URL", database_target)
    db = Database(settings.database_path)
    try:
        yield db
    finally:
        await db.close()


@pytest.fixture
async def job_world(database_target: Path | str) -> AsyncIterator[World]:
    db = Database(database_target)
    try:
        yield await World.made(db, {
            "friend": Character("friend", "朋友", "简介", "voice", "# 人设"),
        })
    finally:
        await db.close()


def remembering(world: World) -> Memories:
    return Memories(
        world.db, world.characters, lambda: NOW,
        embedder=FakeEmbedder(), reranker=FakeReranker("猫"),
    )


async def test_failed_memory_job_is_retried_once_and_marked_failed(
    api_database: Database, make_client: ClientFactory, caplog: pytest.LogCaptureFixture,
):
    gate = asyncio.Event()
    background = FakeLLM(
        [gate, LLMError("secret-key-and-user-text")],
        LLMError("secret-key-and-user-text"),
    )
    client = make_client(
        FakeLLM(["<ja>はい</ja><zh>好的</zh>"]), background_llm=background,
        embedder=FakeEmbedder(), reranker=FakeReranker("猫"),
    )
    conversation = await start_conversation(client)
    try:
        events = await asyncio.wait_for(send_turn(client, conversation, "我有一只猫"), 2)
        assert events[-1]["type"] == "done"
        reply_id = events[-1]["message"]["id"]
    finally:
        gate.set()
    assert (await client.get("/api/memories")).json() == []
    assert "jobs" in await api_database.read(database.tables)
    [job] = await Store(api_database).jobs_for_turn(reply_id)
    assert (job.turn_id, job.type, job.status, job.attempts, job.error) == (
        reply_id, "memory", "failed", 2, "LLMError",
    )
    assert job.created_at <= job.updated_at
    assert "secret-key-and-user-text" not in caplog.text


async def test_retry_can_write_the_memory_and_clear_the_error(job_world: World):
    world = job_world
    conversation = await world.conversation("friend")
    memories = remembering(world)
    try:
        turn = await memories.begin(
            conversation, TZ, FakeBackgroundLLM(LLMError("offline"), memorized(CAT)),
        )
        reply = await world.reply(conversation, "我家的猫叫小白")
        turn.write_down([], "我家的猫叫小白", reply)
        assert [m.text for m in await memories.entries(world.producer)] == [CAT]
        [job] = await world.store.jobs_for_turn(reply.id)
        assert (job.status, job.attempts, job.error) == ("succeeded", 2, None)
    finally:
        await memories.aclose()


async def test_invalid_memory_output_is_a_visible_failure(job_world: World):
    world = job_world
    conversation = await world.conversation("friend")
    memories = remembering(world)
    try:
        turn = await memories.begin(conversation, TZ, FakeBackgroundLLM("not JSON", "not JSON"))
        reply = await world.reply(conversation, "我家的猫叫小白")
        turn.write_down([], "我家的猫叫小白", reply)
        assert await memories.entries(world.producer) == []
        [job] = await world.store.jobs_for_turn(reply.id)
        assert (job.status, job.attempts, job.error) == ("failed", 2, "ValueError")
    finally:
        await memories.aclose()


async def test_memory_off_creates_no_job(job_world: World):
    world = job_world
    conversation = await world.conversation("friend")
    memories = Memories(world.db, world.characters, lambda: NOW)
    try:
        turn = await memories.begin(conversation, TZ, FakeBackgroundLLM(memorized(CAT)))
        reply = await world.reply(conversation, "我家的猫叫小白")
        turn.write_down([], "我家的猫叫小白", reply)
        assert await memories.entries(world.producer) == []
        assert await world.store.jobs_for_turn(reply.id) == []
    finally:
        await memories.aclose()


@pytest.mark.parametrize("answer", [LLMError("secret-title-error"), "「」。"])
async def test_title_failure_is_recorded_after_one_retry(
    api_database: Database, make_client: ClientFactory, answer: str | Exception,
    caplog: pytest.LogCaptureFixture,
):
    client = make_client(
        FakeLLM(*[["<ja>はい</ja><zh>好的</zh>"]] * 3),
        background_llm=FakeBackgroundLLM(answer, answer),
    )
    conversation = await start_conversation(client)
    for _ in range(2):
        await send_turn(client, conversation, "看海")
    events = await send_turn(client, conversation, "看海")
    assert events[-1]["type"] == "done"
    assert (await client.get("/api/conversations?character_id=mano")).json()[0]["title"] is None
    [job] = await Store(api_database).jobs_for_turn(events[-1]["message"]["id"])
    assert (job.type, job.status, job.attempts) == ("title", "failed", 2)
    assert job.error == ("LLMError" if isinstance(answer, Exception) else "ValueError")
    assert "secret-title-error" not in caplog.text


async def test_title_retry_uses_the_same_user_key(
    api_database: Database, make_client: ClientFactory, own_llm,
):
    from tests.test_own_llm import MINE, THINKING

    own_llm.llm = FakeLLM(
        *[["<ja>はい</ja><zh>好的</zh>"]] * 3,
        LLMError("temporary failure"), ["周末去看海"],
    )
    client = make_client(FakeLLM())
    conversation = await start_conversation(client)
    for _ in range(2):
        await send_turn(client, conversation, "看海", own_keys={"llm": THINKING})
    events = await send_turn(client, conversation, "看海", own_keys={"llm": THINKING})
    listed = (await client.get("/api/conversations?character_id=mano")).json()
    assert listed[0]["title"] == "周末去看海"
    [job] = await Store(api_database).jobs_for_turn(events[-1]["message"]["id"])
    assert (job.type, job.status, job.attempts, job.error) == ("title", "succeeded", 2, None)
    assert own_llm.llm.keys == [MINE] * 5


async def test_running_job_is_visible_and_cancelled_without_retry(job_world: World):
    from eidolon.jobs import JobRunner

    world = job_world
    conversation = await world.conversation("friend")
    reply = await world.reply(conversation, "你好")
    began = asyncio.Event()

    async def waiting() -> None:
        began.set()
        await asyncio.Event().wait()

    task = JobRunner(world.store).submit(reply.id, "memory", waiting)
    await asyncio.wait_for(began.wait(), 2)
    [job] = await world.store.jobs_for_turn(reply.id)
    assert (job.status, job.attempts, job.error) == ("running", 1, None)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    cancelled = await world.store.get_job(job.id)
    assert cancelled is not None
    assert (cancelled.status, cancelled.attempts, cancelled.error) == (
        "cancelled", 1, "CancelledError",
    )


async def test_duplicate_submission_across_connections_runs_once(job_world: World, database_target):
    from eidolon.jobs import JobRunner

    world = job_world
    conversation = await world.conversation("friend")
    reply = await world.reply(conversation, "你好")
    other = Database(database_target)
    calls: list[str] = []

    async def doing() -> None:
        calls.append("done")

    try:
        await asyncio.gather(
            JobRunner(world.store).submit(reply.id, "memory", doing),
            JobRunner(Store(other)).submit(reply.id, "memory", doing),
        )
        [job] = await world.store.jobs_for_turn(reply.id)
        assert (job.status, job.attempts, calls) == ("succeeded", 1, ["done"])
    finally:
        await other.close()


async def test_jobs_are_deleted_with_their_conversation_and_user(job_world: World):
    from eidolon.jobs import JobRunner

    world = job_world
    conversation = await world.conversation("friend")
    reply = await world.reply(conversation, "你好")

    async def doing() -> None:
        pass

    await JobRunner(world.store).submit(reply.id, "memory", doing)
    [job] = await world.store.jobs_for_turn(reply.id)
    await world.conversation("friend")  # the earlier conversation may now be deleted
    await world.store.delete_conversation(conversation)
    assert await world.store.get_job(job.id) is None
    current = await world.conversation("friend")
    reply = await world.reply(current, "再见")
    await JobRunner(world.store).submit(reply.id, "title", doing)
    [job] = await world.store.jobs_for_turn(reply.id)
    await world.store.delete_user(world.producer)
    assert await world.store.get_job(job.id) is None


async def test_deletion_before_submission_does_not_run_or_recreate_the_job(job_world: World):
    from eidolon.jobs import JobRunner

    world = job_world
    conversation = await world.conversation("friend")
    reply = await world.reply(conversation, "你好")
    await world.conversation("friend")
    await world.store.delete_conversation(conversation)
    ran = False

    async def doing() -> None:
        nonlocal ran
        ran = True

    await JobRunner(world.store).submit(reply.id, "memory", doing)
    assert not ran
    assert await world.store.jobs_for_turn(reply.id) == []


@pytest.mark.parametrize("step, attempts", [("create_job", 0), ("start_job", 1)])
async def test_cancelling_a_queued_accounting_write_records_cancellation(
    job_world: World, monkeypatch: pytest.MonkeyPatch, step: str, attempts: int,
):
    import threading

    from eidolon.jobs import JobRunner

    world = job_world
    conversation = await world.conversation("friend")
    reply = await world.reply(conversation, "你好")
    entered, release = threading.Event(), threading.Event()
    waiting = asyncio.Event()
    original = getattr(world.store, step)
    blocking: asyncio.Task[None] | None = None
    ran = False

    def occupy_writer(conn) -> None:
        entered.set()
        release.wait()

    async def observed(*args):
        # Keep the real store write; observe it waiting behind a real queued transaction.
        nonlocal blocking
        blocking = asyncio.create_task(world.db.write(occupy_writer))
        await asyncio.to_thread(entered.wait)
        waiting.set()
        return await original(*args)

    async def action() -> None:
        nonlocal ran
        ran = True

    monkeypatch.setattr(world.store, step, observed)
    task = JobRunner(world.store).submit(reply.id, "memory", action)
    try:
        await asyncio.wait_for(waiting.wait(), 2)
        task.cancel()
    finally:
        release.set()
    await asyncio.gather(task, return_exceptions=True)
    if blocking is not None:
        await blocking
    await world.db.write(lambda conn: None)  # queued writes still commit after cancellation
    [job] = await world.store.jobs_for_turn(reply.id)
    assert not ran
    assert (job.status, job.attempts, job.error) == ("cancelled", attempts, "CancelledError")
