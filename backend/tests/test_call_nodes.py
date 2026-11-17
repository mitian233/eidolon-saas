from __future__ import annotations

import asyncio
import threading
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from typing import AsyncIterator

import pytest

from eidolon.call_nodes import AlreadyPlacing, CallNodes, CapacityReached, NodeUnavailable
from eidolon.data_access import Database
from tests.fakes import FakeClock


@asynccontextmanager
async def nodes(target: Path | str) -> AsyncIterator[tuple[CallNodes, CallNodes, CallNodes, FakeClock, Database]]:
    clock = FakeClock()
    db1, db2 = Database(target), Database(target)
    first = CallNodes(db1, ("a", "b"), "a", clock)
    second = CallNodes(db2, ("a", "b"), "b", clock)
    api = CallNodes(db1, ("a", "b"), None, clock)
    try:
        await first.start()
        await second.start()
        await api.start()
        yield first, second, api, clock, db1
    finally:
        await first.aclose()
        await second.aclose()
        await api.aclose()
        await db1.close()
        await db2.close()


async def test_concurrent_admission_and_replacement_share_capacity(database_target: Path | str):
    async with nodes(database_target) as (a, b, api, _, _):
        results = await asyncio.gather(
            a.reserve("one", "c", "v1", 1), b.reserve("two", "c", "v2", 1),
            return_exceptions=True,
        )
        assert sum(isinstance(result, str) for result in results) == 1
        assert sum(isinstance(result, CapacityReached) for result in results) == 1
        owner = a if isinstance(results[0], str) else b
        other = b if owner is a else a
        user = "one" if owner is a else "two"
        claim = results[0] if owner is a else results[1]
        assert isinstance(claim, str)
        with pytest.raises(AlreadyPlacing):
            await other.reserve(user, "c", "v3", 1)
        with pytest.raises(AlreadyPlacing):
            await api.choose(user, 1)
        assert await owner.activated(claim)
        assert await api.count() == 1
        replacement = await other.reserve(user, "c", "v3", 1)
        assert await api.count() == 1
        assert await api.choose("new", None) == "a"
        await other.release(replacement)
        await owner.release(claim)
        assert await api.count() == 0


async def test_stop_waits_for_owner_and_controls_are_delivered_once(database_target: Path | str):
    async with nodes(database_target) as (a, b, api, clock, _):
        claim = await a.reserve("one", "c", "v", None)
        assert await a.activated(claim)
        until = clock.now + timedelta(hours=2)
        await b.cool("one", "c", until)
        await api.end("v", "fed_up")
        controls = await a.heartbeat()
        assert len(controls) == 1
        assert (controls[0].call_id, controls[0].cooldown_until, controls[0].ended_for) == (
            claim, until, "fed_up"
        )
        assert (await a.heartbeat())[0].cooldown_until is None
        assert (await a.heartbeat())[0].ended_for is None
        stopping = asyncio.create_task(api.stop("one", "left"))
        try:
            for _ in range(100):
                controls = await a.heartbeat()
                if controls[0].stop_reason:
                    break
                await asyncio.sleep(0.01)
            assert controls[0].stop_reason == "left"
            assert not stopping.done()
            assert (await a.heartbeat())[0].stop_reason == "left"
            await a.release(claim)
            await asyncio.wait_for(stopping, 2)
        finally:
            if not stopping.done():
                stopping.cancel()
                await asyncio.gather(stopping, return_exceptions=True)


async def test_expired_instance_cannot_renew_or_restart_and_duplicate_is_refused(database_target: Path | str):
    async with nodes(database_target) as (a, _, api, clock, db):
        duplicate = CallNodes(db, ("a", "b"), "a", clock)
        unknown = CallNodes(db, ("a", "b"), "unknown", clock)
        with pytest.raises(NodeUnavailable):
            await duplicate.start()
        with pytest.raises(NodeUnavailable):
            await unknown.start()
        claim = await a.reserve("one", "c", "v", None)
        clock.advance(seconds=20)
        assert await api.count() == 0
        with pytest.raises(NodeUnavailable):
            await a.heartbeat()
        with pytest.raises(NodeUnavailable):
            await a.start()
        assert not await a.activated(claim)
        await duplicate.start()
        await api.stop("one", "deleted")
        await a.aclose()
        assert await api.choose("one", None) == "a"
        await duplicate.aclose()

async def test_stop_timeout_keeps_claim_and_excluding_avoids_self_wait(
    database_target: Path | str, monkeypatch: pytest.MonkeyPatch
):
    import eidolon.call_nodes as registry

    monkeypatch.setattr(registry, "STOP_TIMEOUT", 0.05)
    async with nodes(database_target) as (a, _, api, clock, _):
        claim = await a.reserve("one", "c", "v", None)
        await api.stop("one", "deleted", excluding=claim)
        with pytest.raises(NodeUnavailable):
            await api.stop("one", "deleted")
        assert await api.count() == 1
        assert (await a.heartbeat())[0].stop_reason == "deleted"
        clock.advance(seconds=20)
        assert await api.count() == 0
        with pytest.raises(NodeUnavailable):
            await api.stop("one", "deleted")
        await a.release(claim)
        await api.stop("one", "deleted")


async def test_stopped_placing_cannot_activate_and_cancelled_reservation_releases(database_target: Path | str):
    async with nodes(database_target) as (a, _, api, _, db):
        claim = await a.reserve("one", "c", "v", 1)
        stopping = asyncio.create_task(api.stop("one", "left"))
        try:
            for _ in range(100):
                controls = await a.heartbeat()
                if controls[0].stop_reason:
                    break
                await asyncio.sleep(0.01)
            assert not await a.activated(claim)
            await a.release(claim)
            await asyncio.wait_for(stopping, 2)
        finally:
            if not stopping.done():
                stopping.cancel()
                await asyncio.gather(stopping, return_exceptions=True)

        entered, unblock = threading.Event(), threading.Event()
        def hold(_db):
            entered.set()
            unblock.wait(5)
        blocking = asyncio.create_task(db.write(hold))
        await asyncio.to_thread(entered.wait, 5)
        reservation = asyncio.create_task(a.reserve("two", "c", "v2", 1))
        await asyncio.sleep(0)
        reservation.cancel()
        unblock.set()
        await blocking
        with pytest.raises(asyncio.CancelledError):
            await reservation
        assert await api.count() == 0
        new = await a.reserve("three", "c", "v3", 1)
        await a.release(new)
