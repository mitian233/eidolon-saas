"""Public notices and the admin's disposition, independent of user accounts."""

import hashlib
import sqlite3
import uuid
from dataclasses import dataclass
from typing import Literal

from eidolon.clock import Clock
from eidolon.data_access import Database

ReportCategory = Literal["copyright", "illegal", "abuse", "other"]
ReportStatus = Literal["open", "resolved", "dismissed"]

LIMIT = 5
WINDOW_SECONDS = 600

_SCHEMA = """
CREATE TABLE IF NOT EXISTS reports (
    id TEXT PRIMARY KEY,
    category TEXT NOT NULL CHECK (category IN ('copyright', 'illegal', 'abuse', 'other')),
    target TEXT NOT NULL,
    details TEXT NOT NULL,
    contact TEXT,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'resolved', 'dismissed')),
    note TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    processed_at TEXT
);
CREATE INDEX IF NOT EXISTS reports_by_status ON reports(status, created_at DESC);
CREATE INDEX IF NOT EXISTS reports_by_time ON reports(created_at DESC);

CREATE TABLE IF NOT EXISTS report_rate_limits (
    bucket INTEGER NOT NULL,
    source TEXT NOT NULL,
    count INTEGER NOT NULL,
    PRIMARY KEY (bucket, source)
);
"""

_COLUMNS = "id, category, target, details, contact, status, note, created_at, updated_at, processed_at"


@dataclass(frozen=True)
class Report:
    id: str
    category: ReportCategory
    target: str
    details: str
    contact: str | None
    status: ReportStatus
    note: str | None
    created_at: str
    updated_at: str
    processed_at: str | None


@dataclass(frozen=True)
class ReportPage:
    reports: list[Report]
    total: int


class ReportRateLimited(Exception):
    def __init__(self, retry_after: int) -> None:
        self.retry_after = retry_after


class Reports:
    def __init__(self, db: Database, clock: Clock) -> None:
        self._db = db
        self._clock = clock
        db.prepare(lambda conn: conn.executescript(_SCHEMA))

    async def submit(
        self, source: str, category: ReportCategory, target: str, details: str, contact: str | None,
    ) -> str:
        now = self._clock()
        bucket, elapsed = divmod(int(now.timestamp()), WINDOW_SECONDS)
        source_digest = hashlib.sha256(f"{bucket}:{source}".encode()).hexdigest()
        at = now.isoformat()

        def insert(db: sqlite3.Connection) -> str:
            row = db.execute(
                "SELECT count FROM report_rate_limits WHERE bucket = ? AND source = ?",
                (bucket, source_digest),
            ).fetchone()
            if row and row[0] >= LIMIT:
                raise ReportRateLimited(WINDOW_SECONDS - elapsed)
            db.execute(
                "INSERT INTO report_rate_limits (bucket, source, count) VALUES (?, ?, 1) "
                "ON CONFLICT (bucket, source) DO UPDATE SET count = report_rate_limits.count + 1",
                (bucket, source_digest),
            )
            report_id = uuid.uuid4().hex
            db.execute(
                "INSERT INTO reports (id, category, target, details, contact, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (report_id, category, target, details, contact or None, at, at),
            )
            return report_id

        return await self._db.write(insert)

    async def forget_old_limits(self) -> None:
        bucket = int(self._clock().timestamp()) // WINDOW_SECONDS
        await self._db.write(lambda db: db.execute("DELETE FROM report_rate_limits WHERE bucket < ?", (bucket,)))

    async def list(self, status: ReportStatus | None, offset: int, limit: int) -> ReportPage:
        where = " WHERE status = ?" if status is not None else ""
        params = (status,) if status is not None else ()

        def select(db: sqlite3.Connection) -> ReportPage:
            total = db.execute(f"SELECT COUNT(*) FROM reports{where}", params).fetchone()[0]
            rows = db.execute(
                f"SELECT {_COLUMNS} FROM reports{where} ORDER BY created_at DESC, rowid DESC LIMIT ? OFFSET ?",
                (*params, limit, offset),
            )
            return ReportPage([Report(*row) for row in rows], total)

        return await self._db.read(select)

    async def update(
        self, report_id: str, *, status: ReportStatus | None, note: str | None, replace_note: bool,
    ) -> Report | None:
        at = self._clock().isoformat()

        def update(db: sqlite3.Connection) -> Report | None:
            row = db.execute(f"SELECT {_COLUMNS} FROM reports WHERE id = ?", (report_id,)).fetchone()
            if row is None:
                return None
            report = Report(*row)
            new_status = status or report.status
            new_note = (note or None) if replace_note else report.note
            if (new_status, new_note) == (report.status, report.note):
                return report
            processed_at = report.processed_at
            if new_status != report.status:
                processed_at = None if new_status == "open" else at
            db.execute(
                "UPDATE reports SET status = ?, note = ?, updated_at = ?, processed_at = ? WHERE id = ?",
                (new_status, new_note, at, processed_at, report_id),
            )
            return Report(
                report.id, report.category, report.target, report.details, report.contact,
                new_status, new_note, report.created_at, at, processed_at,
            )

        return await self._db.write(update)
