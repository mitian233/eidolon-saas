"""Public notices and their disposition through the admin API."""

import asyncio
from dataclasses import replace
from pathlib import Path
from typing import cast

import httpx
import pytest
from fastapi import FastAPI

from eidolon.config import Settings
from tests.conftest import SITE, ClientFactory
from tests.fakes import FakeClock, FakeIdentityProvider, FakeLLM
from tests.test_admin_users import admin_client
from tests.test_admin_users import settings  # noqa: F401

NOTICE = {"category": "copyright", "target": "示例头像", "details": "我是图片作者，请核实使用情况。"}


@pytest.fixture
def report_settings(settings: Settings, database_target: Path | str) -> Settings:
    return replace(settings, database_path=cast(Path, database_target))


async def test_anyone_can_submit_and_only_admins_can_handle_reports(
    report_settings: Settings, make_client: ClientFactory, github: FakeIdentityProvider,
):
    admin = await admin_client(make_client, github, settings=report_settings)
    guest = make_client(FakeLLM(), None, settings=report_settings)
    member = make_client(FakeLLM(), settings=report_settings)
    queue = "/api/admin/reports"
    for client in (guest, member):
        assert (await client.get(queue)).status_code == 404
    response = await guest.post("/api/reports", json=NOTICE | {"contact": " author@example.test "})
    assert response.status_code == 201, response.text
    assert set(response.json()) == {"id"}
    report_id = response.json()["id"]
    path = f"{queue}/{report_id}"
    response = await member.post("/api/reports", json=NOTICE | {"category": "abuse"})
    assert response.status_code == 201, response.text
    other_id = response.json()["id"]
    for client in (guest, member):
        assert (await client.patch(path, json={"status": "resolved"})).status_code == 404

    listing = (await admin.get(queue, params={"status": "open", "limit": 1})).json()
    assert listing["total"] == 2
    assert [report["id"] for report in listing["reports"]] == [other_id]
    response = await admin.get(queue, params={"status": "open", "limit": 1, "offset": 1})
    [report] = response.json()["reports"]
    assert report["id"] == report_id
    assert report["contact"] == "author@example.test"
    assert report["processed_at"] is None
    assert all(report[key] == value for key, value in NOTICE.items())

    handled = await admin.patch(path, json={"status": "resolved", "note": " 已移除外链 "})
    assert handled.status_code == 200, handled.text
    assert handled.json()["status"] == "resolved"
    assert handled.json()["note"] == "已移除外链"
    assert handled.json()["processed_at"] is not None
    assert (await admin.get(queue, params={"status": "resolved"})).json()["reports"] == [handled.json()]
    assert (await admin.get(queue, params={"status": "open"})).json()["total"] == 1
    assert (await admin.patch(path, json={"status": "dismissed"})).json()["note"] == "已移除外链"
    reopened = await admin.patch(path, json={"status": "open", "note": None})
    assert reopened.json()["note"] is None
    assert reopened.json()["processed_at"] is None
    assert (await admin.patch(f"{queue}/missing", json={"status": "dismissed"})).status_code == 404


async def test_public_reports_reject_blank_oversized_or_invalid_fields(
    report_settings: Settings, make_client: ClientFactory,
):
    guest = make_client(FakeLLM(), None, settings=report_settings)
    for replacement in (
        {"category": "unknown"}, {"target": "　 "}, {"target": "字" * 2049},
        {"details": "x" * 4001}, {"contact": "x" * 321}, {"details": "空\0字"},
    ):
        res = await guest.post("/api/reports", json=NOTICE | replacement)
        assert res.status_code == 422, res.text
    res = await guest.post("/api/reports", content=b" " * 100_000)
    assert res.status_code == 413, res.text


async def test_report_limit_is_shared_between_api_instances_and_resets(
    report_settings: Settings, make_client: ClientFactory,
):
    clock = FakeClock()
    first = make_client(FakeLLM(), None, settings=report_settings, clock=clock)
    second = make_client(FakeLLM(), None, settings=report_settings, clock=clock)
    results = await asyncio.gather(*(
        client.post("/api/reports", json=NOTICE) for client in (first, second) * 3
    ))
    assert sorted(response.status_code for response in results) == [201] * 5 + [429]
    [refused] = [response for response in results if response.status_code == 429]
    assert 0 < int(refused.headers["retry-after"]) <= 600

    transport = first._transport
    assert isinstance(transport, httpx.ASGITransport)
    app = cast(FastAPI, transport.app)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=("198.51.100.42", 1234)),
        base_url="http://test", headers=SITE,
    ) as other_network:
        assert (await other_network.post("/api/reports", json=NOTICE)).status_code == 201
    clock.advance(minutes=10)
    assert (await first.post("/api/reports", json=NOTICE)).status_code == 201
