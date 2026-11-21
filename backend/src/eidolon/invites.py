"""Invite links (GLOSSARY.md「邀请链接」): while the deployment takes only those invited
(GLOSSARY.md「注册方式」, ADR-0006 revised 2026-10-29), a new identity signs up only through
one an admin made. Each may be used a number of times, `MAX_USES` at most and never without
end, for a link anyone could use for ever would be signing up open to all; and may expire.

A use is counted only as it makes a new user, in the same write (`admit`), so that two
signing up at once through its last use cannot both; deleting the user does not give it
back. Who signed up through which link is kept (`invited_users`), for admins to tell
through which a stranger came in: it is the user's, deleted with them, and goes when the
link is deleted. The links are kept as they are, not hashed, so that admins can copy them
again: each is 128 random bits, and backups are encrypted.
"""

import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from eidolon.clock import Clock
from eidolon.data_access import Database
from eidolon.database import by_name
from eidolon.store import Admit

MAX_USES = 100
"""How many times a link may be used at most."""

State = Literal["usable", "used_up", "expired"]

NotInvitedReason = Literal["not_invited", "invite_invalid"]
"""Why signing up was refused: no invite link was brought; or the one brought cannot be
used, being none such, deleted, expired or used up."""

_SCHEMA = """
-- An invite link an admin made (GLOSSARY.md「邀请链接」): `code` is what its address carries;
-- `note` the admin's, say for whom or where it was sent; how many times it may be used and
-- has been; `expires_at` NULL for never.
CREATE TABLE IF NOT EXISTS invites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    note TEXT,
    max_uses INTEGER NOT NULL,
    used INTEGER NOT NULL DEFAULT 0,
    expires_at TEXT,
    created_at TEXT NOT NULL
);
-- The invite link each user signed up through, if any.
CREATE TABLE IF NOT EXISTS invited_users (
    user_id TEXT PRIMARY KEY REFERENCES users(id),
    invite_id INTEGER NOT NULL REFERENCES invites(id)
);
CREATE INDEX IF NOT EXISTS invited_users_by_invite ON invited_users(invite_id);
"""


class NotInvited(Exception):
    """Signing up takes an invite link that can be used, saying why it was refused."""

    def __init__(self, reason: NotInvitedReason) -> None:
        super().__init__(reason)
        self.reason: NotInvitedReason = reason


@dataclass(frozen=True)
class Invited:
    """A user who signed up through a link, by the name they signed up with."""

    user_id: str
    name: str


@dataclass(frozen=True)
class Invite:
    id: int
    code: str
    note: str | None
    max_uses: int
    used: int
    expires_at: str | None
    """ISO 8601; None for never."""
    created_at: str
    invited: tuple[Invited, ...] = ()
    """Those who signed up through it and are still users, the earliest first."""

    def state(self, now: datetime) -> State:
        if self.used >= self.max_uses:
            return "used_up"
        if self.expires_at is not None and datetime.fromisoformat(self.expires_at) <= now:
            return "expired"
        return "usable"


class Invites:
    def __init__(self, db: Database, clock: Clock) -> None:
        self._db = db
        db.prepare(lambda conn: conn.executescript(_SCHEMA))
        self._clock = clock

    async def create(self, note: str | None, max_uses: int, lifetime: timedelta | None) -> Invite:
        """A new link, usable `max_uses` times (1 to `MAX_USES`) for `lifetime` from now, or
        for ever with None."""
        if not 1 <= max_uses <= MAX_USES:
            raise ValueError(f"max_uses {max_uses} is not from 1 to {MAX_USES}")
        now = self._clock()
        return await self._db.write(
            _create, secrets.token_urlsafe(16), note, max_uses,
            None if lifetime is None else (now + lifetime).isoformat(), now.isoformat(),
        )

    async def all(self) -> list[Invite]:
        """Every link, the newest first, with who signed up through each."""
        return await self._db.read(_all)

    async def delete(self, invite_id: int) -> bool:
        """Delete the link, at once unusable, and who signed up through it with it; False if
        there is none such."""
        return await self._db.write(_delete, invite_id)

    async def of_user(self, user_id: str) -> Invite | None:
        """The link the user signed up through, if they did through one still kept."""
        return await self._db.read(_of_user, user_id)

    def admit(self, code: str | None, *, allow_first_user: bool) -> Admit:
        """Check and count an invite in the same write that creates the user.

        Without an admin list the first user can sign in to find their admin identity.
        Raises NotInvited to undo the write when registration is refused."""
        now = self._clock()

        def admitting(db: sqlite3.Connection, user_id: str) -> None:
            if allow_first_user:
                [(users,)] = db.execute("SELECT COUNT(*) FROM users")
                if users == 1:
                    return
            if code is None:
                raise NotInvited("not_invited")
            row = by_name(db).execute(
                f"SELECT {_COLUMNS} FROM invites WHERE code = ?", (code,)
            ).fetchone()
            if row is None or Invite(**row).state(now) != "usable":
                raise NotInvited("invite_invalid")
            db.execute("UPDATE invites SET used = used + 1 WHERE id = ?", (row["id"],))
            db.execute(
                "INSERT INTO invited_users (user_id, invite_id) VALUES (?, ?)",
                (user_id, row["id"]),
            )

        return admitting


_COLUMNS = "id, code, note, max_uses, used, expires_at, created_at"


def _create(
    db: sqlite3.Connection, code: str, note: str | None, max_uses: int,
    expires_at: str | None, created_at: str,
) -> Invite:
    cursor = db.execute(
        "INSERT INTO invites (code, note, max_uses, expires_at, created_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (code, note, max_uses, expires_at, created_at),
    )
    assert cursor.lastrowid is not None
    return Invite(cursor.lastrowid, code, note, max_uses, 0, expires_at, created_at)


def _all(db: sqlite3.Connection) -> list[Invite]:
    invited: dict[int, list[Invited]] = {}
    for invite_id, user_id, name in db.execute(
        "SELECT i.invite_id, u.id, u.name FROM invited_users i JOIN users u ON u.id = i.user_id"
        " ORDER BY u.created_at, u.rowid"
    ):
        invited.setdefault(invite_id, []).append(Invited(user_id, name))
    return [
        Invite(**row, invited=tuple(invited.get(row["id"], ())))
        for row in by_name(db).execute(f"SELECT {_COLUMNS} FROM invites ORDER BY id DESC")
    ]


def _delete(db: sqlite3.Connection, invite_id: int) -> bool:
    db.execute("DELETE FROM invited_users WHERE invite_id = ?", (invite_id,))
    return db.execute("DELETE FROM invites WHERE id = ?", (invite_id,)).rowcount > 0


def _of_user(db: sqlite3.Connection, user_id: str) -> Invite | None:
    row = by_name(db).execute(
        f"SELECT {', '.join(f'i.{c}' for c in _COLUMNS.split(', '))} FROM invites i"
        " JOIN invited_users u ON u.invite_id = i.id WHERE u.user_id = ?",
        (user_id,),
    ).fetchone()
    return Invite(**row) if row else None
