"""The health check: whether the backend can serve, which it cannot unless it reads
the database in time; needing no session, for compose to ask it."""

import sqlite3
import time
from pathlib import Path

import psycopg
import pytest
from psycopg import sql

import eidolon.app
from eidolon.assembly import Backend
from eidolon.database import readable
from tests.conftest import ClientFactory
from tests.fakes import FakeLLM


async def test_the_backend_is_healthy_while_it_reads_the_database(make_client: ClientFactory):
    res = await make_client(FakeLLM(), user=None).get("/api/health")

    assert (res.status_code, res.json()) == (200, {"ok": True})


async def test_health_recovers_after_postgres_starts_accepting_connections_again(
    postgres_url: str, make_client: ClientFactory, monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("DATABASE_URL", postgres_url)
    client = make_client(FakeLLM(), user=None)
    backend: Backend = client._transport.app.state.backend  # pyright: ignore[reportAttributeAccessIssue]
    assert (await client.get("/api/health")).status_code == 200

    with psycopg.connect(postgres_url, autocommit=True) as target:
        database_name = target.info.dbname
    name = sql.Identifier(database_name)
    with psycopg.connect(postgres_url, dbname="postgres", autocommit=True) as admin:
        admin.execute(sql.SQL("ALTER DATABASE {} ALLOW_CONNECTIONS false").format(name))
        try:
            terminated = admin.execute(
                "SELECT pg_terminate_backend(pid, 5000) FROM pg_stat_activity WHERE datname = %s",
                (database_name,),
            ).fetchall()
            assert terminated and all(ended for (ended,) in terminated)
            unavailable = await client.get("/api/health")
            assert (unavailable.status_code, unavailable.json()) == (503, {"ok": False})
            with pytest.raises(sqlite3.OperationalError):
                await backend.store.create_user("During outage")
        finally:
            admin.execute(sql.SQL("ALTER DATABASE {} ALLOW_CONNECTIONS true").format(name))

    available = await client.get("/api/health")
    assert (available.status_code, available.json()) == (200, {"ok": True})
    user = await backend.store.create_user("After outage")
    assert await backend.store.list_users() == [user]


async def test_the_backend_is_not_healthy_when_it_cannot_read_the_database(
    make_client: ClientFactory, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(eidolon.app, "readable", lambda path: False)

    res = await make_client(FakeLLM(), user=None).get("/api/health")

    assert (res.status_code, res.json()) == (503, {"ok": False})


async def test_the_backend_is_not_healthy_when_reading_takes_too_long(
    make_client: ClientFactory, monkeypatch: pytest.MonkeyPatch
):
    def slow(path: Path) -> bool:
        time.sleep(0.3)
        return True

    monkeypatch.setattr(eidolon.app, "readable", slow)
    monkeypatch.setattr(eidolon.app, "HEALTH_TIMEOUT", 0.05)

    res = await make_client(FakeLLM(), user=None).get("/api/health")

    assert res.status_code == 503


def test_a_file_that_is_not_a_database_is_not_readable(tmp_path: Path):
    broken = tmp_path / "eidolon.db"
    broken.write_bytes(b"not a database, though long enough to look like a header" * 4)

    assert not readable(broken)


def test_a_missing_database_is_not_readable_and_not_made(tmp_path: Path):
    missing = tmp_path / "eidolon.db"

    assert not readable(missing)
    assert not missing.exists()
