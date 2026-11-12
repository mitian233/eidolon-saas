"""The admin console's configuration, under `/api/admin/config`, for admins only: the live
configuration (`live_config`) as `.env` has it and as it is in effect, changing an item
and restoring it to `.env`'s (ADR-0013). Of a key, only its last 4 characters are ever
shown; a key left out of a change stays as it is. What cannot be changed here
(`live_config.READ_ONLY`) is refused, saying why."""

from typing import Any

from fastapi import Body, FastAPI, HTTPException
from pydantic import BaseModel, ValidationError

from eidolon.admin_api import Admin
from eidolon.assembly import Backend
from eidolon.live_config import AFFINITY, BAR, CYCLES, LIMITS, LETTERS, MOMENTS, REACH_OUTS, READ_ONLY, REGISTRATION, SCHEDULE, ConfigInvalid, ConfigRejected, KeysReadOnly, Unavailable





class LimitsInput(BaseModel):
    """Each a whole number from 0 up, 0 for no limit, and whether each service is one of
    the exempting keys, true or false, not all false; checked by the live configuration,
    which says what is wrong in so many words."""

    turns_per_hour: Any
    calls_per_hour: Any
    photos_per_hour: Any
    visits_per_hour: Any
    read_alouds_per_hour: Any
    call_minutes: Any
    turns_per_call: Any
    concurrent_calls: Any
    history_turns: Any
    exempting_llm: Any
    exempting_tts: Any
    exempting_stt: Any


class AffinityInput(BaseModel):
    """Whether affinity and gifts are on, true or false; checked by the live configuration."""

    enabled: Any


class ReachOutsInput(BaseModel):
    """Whether characters reach out to users, true or false, and how many times a day each
    user at most, a whole number from 1 up; checked by the live configuration."""

    enabled: Any
    per_day: Any


class LettersInput(BaseModel):
    """Whether characters write letters on their occasions, true or false; checked by the
    live configuration."""

    enabled: Any


class MomentsInput(BaseModel):
    """Whether characters post moments, true or false, how many a day each user at most, a
    whole number from 1 up, which map their places link to, and how many of each user's
    comments a day they reply to, a whole number from 1 up, each of the last two unchanged
    if not given; checked by the live configuration."""

    enabled: Any
    per_day: Any
    map: Any = None
    replies_per_day: Any = None


class ScheduleInput(BaseModel):
    """Whether each week's jobs are published for producers to schedule, true or false;
    checked by the live configuration."""

    enabled: Any


class CyclesInput(BaseModel):
    """Whether her cycle has a part in how she is, true or false; checked by the live
    configuration."""

    enabled: Any


class BarInput(BaseModel):
    """Whether the bar is open, true or false; checked by the live configuration."""

    enabled: Any



class RegistrationInput(BaseModel):
    """Who may sign up, `open` or `invite`; checked by the live configuration."""

    mode: Any


INPUTS: dict[str, type[BaseModel]] = {
    LIMITS: LimitsInput,
    AFFINITY: AffinityInput,
    REACH_OUTS: ReachOutsInput,
    LETTERS: LettersInput,
    MOMENTS: MomentsInput,
    SCHEDULE: ScheduleInput,
    CYCLES: CyclesInput,
    BAR: BarInput,
    REGISTRATION: RegistrationInput,
}


def _change(body: BaseModel) -> dict[str, Any]:
    """Drop optional moments fields when they are not part of the change."""
    change = body.model_dump()
    for field in ("map", "replies_per_day"):
        if field in change and change[field] is None:
            del change[field]
    return change


def add_admin_config_routes(app: FastAPI, backend: Backend) -> None:
    config = backend.config

    def item_or_error(item: str) -> str:
        if item in READ_ONLY:
            raise HTTPException(403, f"这一项只能在服务器上改：{READ_ONLY[item]}")
        if item not in INPUTS:
            raise HTTPException(404, "没有这项配置")
        return item

    @app.get("/api/admin/config")
    def get_config(_: Admin) -> dict:
        return config.describe()

    @app.put("/api/admin/config/{item}")
    async def save(item: str, _: Admin, body: dict = Body()) -> dict:  # noqa: B008
        """Try the item and, if it works, run every turn and call from now on on it."""
        item = item_or_error(item)
        try:
            parsed = INPUTS[item].model_validate(body)
        except ValidationError as e:
            raise HTTPException(422, e.errors(include_url=False, include_context=False)) from None
        try:
            await config.save(item, _change(parsed))
        except KeysReadOnly as e:
            raise HTTPException(409, str(e)) from None
        except Unavailable as e:
            raise HTTPException(409, str(e)) from None
        except ConfigInvalid as e:
            raise HTTPException(422, str(e)) from None
        except ConfigRejected as e:
            raise HTTPException(422, f"试调失败，没有保存：{e}") from None
        return config.describe()


    @app.delete("/api/admin/config/{item}")
    async def restore(item: str, _: Admin) -> dict:
        """Back to `.env`'s, from the next turn and call on."""
        item = item_or_error(item)
        try:
            await config.restore(item)
        except Unavailable as e:
            raise HTTPException(409, str(e)) from None
        return config.describe()

