"""Record post-turn work; execute it here while this process still holds the turn's key.

A job gets at most two attempts. Only its outcome is durable: no callable, input,
endpoint or key goes into the database, and another process never picks it up.
The submitting service retains the returned task until shutdown or completion.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable

from eidolon.activity import detached
from eidolon.store import JobType, Store

log = logging.getLogger(__name__)


class JobRunner:
    def __init__(self, store: Store) -> None:
        self._store = store

    def submit(
        self, turn_id: int, kind: JobType, action: Callable[[], Awaitable[None]],
    ) -> asyncio.Task[None]:
        """Start without waiting for the action or its accounting; retain only in memory."""
        return detached().run(asyncio.ensure_future, self._run(turn_id, kind, action))

    async def _run(
        self, turn_id: int, kind: JobType, action: Callable[[], Awaitable[None]],
    ) -> None:
        try:
            await self._execute(turn_id, kind, action)
        except Exception as error:
            # Accounting failures cannot turn a completed conversation into a failed one.
            log.warning("recording %s job for turn %s failed: %s",
                        kind, turn_id, type(error).__name__)

    async def _execute(
        self, turn_id: int, kind: JobType, action: Callable[[], Awaitable[None]],
    ) -> None:
        creating = asyncio.ensure_future(self._store.create_job(turn_id, kind))
        try:
            # Database.write commits even if its waiter is cancelled. Retain the result
            # so shutdown can mark the resulting row instead of losing its id.
            job = await asyncio.shield(creating)
            if job is None:  # duplicate submission, or the reply was deleted meanwhile
                return
            for _ in range(2):
                if not await self._store.start_job(job.id):
                    return
                try:
                    await action()
                except Exception as error:
                    # A provider's exception text can repeat a key, endpoint or user input.
                    reason = type(error).__name__
                    await self._store.finish_job(job.id, "failed", reason)
                    log.warning("%s job %s failed: %s", kind, job.id, reason)
                else:
                    await self._store.finish_job(job.id, "succeeded")
                    return
        except asyncio.CancelledError:
            job = await creating
            if job is not None:
                await self._store.finish_job(job.id, "cancelled", "CancelledError")
            raise
