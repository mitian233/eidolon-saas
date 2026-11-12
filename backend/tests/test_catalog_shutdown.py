"""A stalled optional price-list download must not prevent server shutdown."""
import asyncio
from datetime import UTC, datetime
from pathlib import Path

import httpx

from eidolon.data_access import Database
from eidolon.price_catalog import Catalog


async def test_shutdown_cancels_stalled_price_catalog_download(tmp_path: Path):
    began = asyncio.Event()
    release = asyncio.Event()
    cancelled = asyncio.Event()

    async def provider(request: httpx.Request) -> httpx.Response:
        began.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return httpx.Response(200, json={})

    database = Database(tmp_path / 'catalog.db')
    catalog = Catalog(database, lambda: datetime(2026, 11, 12, tzinfo=UTC), httpx.MockTransport(provider))
    try:
        catalog.refresh_soon()
        await asyncio.wait_for(began.wait(), 1)
        await asyncio.wait_for(catalog.aclose(), .5)
        assert cancelled.is_set()
    finally:
        await catalog.aclose()
        await database.close()
