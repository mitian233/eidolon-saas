"""Shared call-node leases, admission and control messages."""

import asyncio
import sqlite3
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from eidolon.activity import CallEndReason
from eidolon.affinity import EndsFor
from eidolon.clock import Clock
from eidolon.data_access import Database

LEASE_SECONDS = 15.0
STOP_TIMEOUT = 20.0
POLL_INTERVAL = 0.1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS call_nodes (
    node_id TEXT PRIMARY KEY,
    instance_id TEXT NOT NULL,
    expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS active_calls (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    instance_id TEXT NOT NULL,
    state TEXT NOT NULL,
    stop_reason TEXT,
    cooldown_until REAL,
    ended_for TEXT
);
CREATE INDEX IF NOT EXISTS active_calls_user ON active_calls(user_id);
CREATE INDEX IF NOT EXISTS active_calls_conversation ON active_calls(conversation_id);
"""


class CapacityReached(Exception):
    """No call slot is available."""


class AlreadyPlacing(Exception):
    """This user is already placing a call."""


class NodeUnavailable(Exception):
    """A call node is unavailable."""


@dataclass(frozen=True)
class Control:
    call_id: str
    stop_reason: CallEndReason | None
    cooldown_until: datetime | None
    ended_for: EndsFor | None


def _open(db: sqlite3.Connection) -> None:
    db.executescript(_SCHEMA)


def _clean(db: sqlite3.Connection, now: float) -> None:
    # An expired node stops receiving calls. Its old calls still need confirmation.
    db.execute("DELETE FROM call_nodes WHERE expires_at <= ?", (now,))


def _owned(db: sqlite3.Connection, node: str | None, instance: str) -> bool:
    return db.execute(
        "SELECT 1 FROM call_nodes WHERE node_id = ? AND instance_id = ?", (node, instance)
    ).fetchone() is not None


_LIVE_CALLS = (
    " FROM active_calls JOIN call_nodes ON call_nodes.node_id = active_calls.node_id "
    "AND call_nodes.instance_id = active_calls.instance_id"
)


def _admit(db: sqlite3.Connection, user: str, maximum: int | None) -> None:
    if db.execute(
        "SELECT 1" + _LIVE_CALLS + " WHERE user_id = ? AND state = 'placing'", (user,)
    ).fetchone():
        raise AlreadyPlacing("A call is already being placed")
    others = db.execute(
        "SELECT COUNT(DISTINCT user_id)" + _LIVE_CALLS + " WHERE user_id != ?", (user,)
    ).fetchone()[0]
    if maximum is not None and others >= maximum:
        raise CapacityReached("Call capacity reached")


class CallNodes:
    """Coordinate active calls between independent processes sharing a database."""

    def __init__(self, database: Database, node_ids: tuple[str, ...], node_id: str | None, clock: Clock) -> None:
        self._db = database
        self._node_ids = tuple(sorted(node_ids))
        self._node_id = node_id
        self._clock = clock
        self.instance_id = uuid.uuid4().hex
        self._started = False
        database.prepare(_open)

    async def start(self) -> None:
        if self._node_id is None:
            return
        if self._node_id not in self._node_ids:
            raise NodeUnavailable("Unknown call node")
        def register(db: sqlite3.Connection) -> None:
            now = self._clock().timestamp()
            _clean(db, now)
            if self._started:
                if not _owned(db, self._node_id, self.instance_id):
                    raise NodeUnavailable("Call node lease lost")
                return
            if db.execute("SELECT 1 FROM call_nodes WHERE node_id = ?", (self._node_id,)).fetchone():
                raise NodeUnavailable("Call node already registered")
            # Stop the previous process before reusing this ID. Only registration after
            # that stop cleans its old calls; the expiry path never acknowledges them.
            db.execute("DELETE FROM active_calls WHERE node_id = ?", (self._node_id,))
            db.execute(
                "INSERT INTO call_nodes (node_id, instance_id, expires_at) VALUES (?, ?, ?)",
                (self._node_id, self.instance_id, now + LEASE_SECONDS),
            )

        await self._db.write(register)
        self._started = True

    async def choose(self, user_id: str, maximum: int | None) -> str:
        def choose_node(db: sqlite3.Connection) -> str:
            _clean(db, self._clock().timestamp())
            _admit(db, user_id, maximum)
            loads = dict(db.execute(
                "SELECT active_calls.node_id, COUNT(*)" + _LIVE_CALLS + " GROUP BY active_calls.node_id"
            ).fetchall())
            live = {row[0] for row in db.execute("SELECT node_id FROM call_nodes").fetchall()}
            available = [node for node in self._node_ids if node in live]
            if not available:
                raise NodeUnavailable("No call node available")
            return min(available, key=lambda node: (loads.get(node, 0), node))

        return await self._db.write(choose_node)

    async def reserve(
        self, user_id: str, character_id: str, conversation_id: str, maximum: int | None
    ) -> str:
        call_id = uuid.uuid4().hex
        def insert(db: sqlite3.Connection) -> None:
            _clean(db, self._clock().timestamp())
            if not _owned(db, self._node_id, self.instance_id):
                raise NodeUnavailable("Call node lease lost")
            _admit(db, user_id, maximum)
            db.execute(
                "INSERT INTO active_calls "
                "(id, user_id, character_id, conversation_id, node_id, instance_id, state) "
                "VALUES (?, ?, ?, ?, ?, ?, 'placing')",
                (call_id, user_id, character_id, conversation_id, self._node_id, self.instance_id),
            )

        work = asyncio.create_task(self._db.write(insert))
        try:
            await asyncio.shield(work)
        except asyncio.CancelledError:
            try:
                await work
            except Exception:
                pass
            await self.release(call_id)
            raise
        return call_id

    async def activated(self, call_id: str) -> bool:
        def activate(db: sqlite3.Connection) -> bool:
            _clean(db, self._clock().timestamp())
            if not _owned(db, self._node_id, self.instance_id):
                return False
            return db.execute(
                "UPDATE active_calls SET state = 'live' WHERE id = ? AND node_id = ? "
                "AND instance_id = ? AND state = 'placing' AND stop_reason IS NULL "
                "AND cooldown_until IS NULL AND ended_for IS NULL",
                (call_id, self._node_id, self.instance_id),
            ).rowcount == 1

        return await self._db.write(activate)

    async def release(self, call_id: str) -> None:
        await self.release_finished((call_id,))

    async def release_finished(self, call_ids: tuple[str, ...]) -> None:
        def delete(db: sqlite3.Connection) -> None:
            db.executemany(
                "DELETE FROM active_calls WHERE id = ? AND node_id = ? AND instance_id = ?",
                [(call_id, self._node_id, self.instance_id) for call_id in call_ids],
            )

        await self._db.write(delete)

    async def stop(
        self, user_id: str, reason: CallEndReason, *, character_id: str | None = None,
        excluding: str | None = None,
    ) -> None:
        deadline = time.monotonic() + STOP_TIMEOUT

        def request(db: sqlite3.Connection) -> bool:
            where = "user_id = ?"
            params: list[str] = [user_id]
            if character_id is not None:
                where += " AND character_id = ?"
                params.append(character_id)
            if excluding is not None:
                where += " AND id != ?"
                params.append(excluding)
            db.execute(f"UPDATE active_calls SET stop_reason = ? WHERE {where}", (reason, *params))
            return db.execute(f"SELECT 1 FROM active_calls WHERE {where} LIMIT 1", params).fetchone() is not None

        while await self._db.write(request):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise NodeUnavailable("Call node did not stop the call")
            await asyncio.sleep(min(POLL_INTERVAL, remaining))

    async def cool(self, user_id: str, character_id: str, until: datetime) -> None:
        def publish(db: sqlite3.Connection) -> None:
            db.execute(
                "UPDATE active_calls SET cooldown_until = ? WHERE user_id = ? AND character_id = ? "
                "AND instance_id != ?",
                (until.timestamp(), user_id, character_id, self.instance_id),
            )

        await self._db.write(publish)

    async def end(self, conversation_id: str, why: EndsFor) -> None:
        def publish(db: sqlite3.Connection) -> None:
            db.execute(
                "UPDATE active_calls SET ended_for = ? WHERE conversation_id = ? AND instance_id != ?",
                (why, conversation_id, self.instance_id),
            )

        await self._db.write(publish)

    async def heartbeat(self) -> list[Control]:
        def renew(db: sqlite3.Connection) -> list[Control]:
            now = self._clock().timestamp()
            _clean(db, now)
            if not _owned(db, self._node_id, self.instance_id):
                raise NodeUnavailable("Call node lease lost")
            db.execute(
                "UPDATE call_nodes SET expires_at = ? WHERE node_id = ? AND instance_id = ?",
                (now + LEASE_SECONDS, self._node_id, self.instance_id),
            )
            rows = db.execute(
                "SELECT id, stop_reason, cooldown_until, ended_for FROM active_calls "
                "WHERE node_id = ? AND instance_id = ? ORDER BY id",
                (self._node_id, self.instance_id),
            ).fetchall()
            db.execute(
                "UPDATE active_calls SET cooldown_until = NULL, ended_for = NULL "
                "WHERE node_id = ? AND instance_id = ?", (self._node_id, self.instance_id),
            )
            return [
                Control(call_id, cast(CallEndReason | None, reason),
                        datetime.fromtimestamp(until, UTC) if until is not None else None,
                        cast(EndsFor | None, ended))
                for call_id, reason, until, ended in rows
            ]

        return await self._db.write(renew)

    async def count(self) -> int:
        def count_users(db: sqlite3.Connection) -> int:
            _clean(db, self._clock().timestamp())
            return cast(int, db.execute("SELECT COUNT(DISTINCT user_id)" + _LIVE_CALLS).fetchone()[0])

        return await self._db.write(count_users)

    async def aclose(self) -> None:
        def close(db: sqlite3.Connection) -> None:
            db.execute(
                "DELETE FROM active_calls WHERE node_id = ? AND instance_id = ?",
                (self._node_id, self.instance_id),
            )
            db.execute(
                "DELETE FROM call_nodes WHERE node_id = ? AND instance_id = ?",
                (self._node_id, self.instance_id),
            )

        await self._db.write(close)
