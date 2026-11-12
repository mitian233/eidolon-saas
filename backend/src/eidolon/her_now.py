"""What she knows of now (GLOSSARY.md「此刻」), each time she speaks: typing, in a call, or
not talking to the user at all.

`HerNow` gives it in two steps. The first reads her character, and, for a visit, her
affinity. The second gives the lines of now: the time where the user is, how they are
talking, when they were last in touch, whether it is their birthday (`producer.now_prompt`),
the day's birthdays among the user's own characters (`today.today_lines`), and how she
feels toward the user (the affinity lines).

What every prompt of hers opens with (her sheet, her birthday) is not now: it stays the
same all day, for a service to cache (`today.always_known`).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from eidolon.affinity import Affinities, Status
from eidolon.characters import Character
from eidolon.producer import ProducerProfile, Talking, local_date, now_prompt
from eidolon.today import today_lines

Occasion = Talking | Literal["visit"]
"""Where she speaks: typing, in a call, not talking to the user (`apart`), or a visit."""


@dataclass(frozen=True)
class KnownNow:
    """What the first step read of now (GLOSSARY.md「此刻」), for the user's `character`:
    her affinity, read for a visit (None otherwise, or while affinity is off)."""

    character: Character
    affinity: Status | None = None


class HerNow:
    def __init__(
        self,
        characters: Mapping[str, Character],
        affinities: Affinities | None = None,
    ) -> None:
        """Without `affinities`, she reads no affinity for a visit."""
        self._characters = characters
        self._affinities = affinities

    async def read(
        self, user_id: str, character_id: str, device_timezone: str | None, occasion: Occasion
    ) -> KnownNow:
        """The first step, for the user's character on `occasion`: her affinity for a visit,
        None otherwise."""
        affinity = (
            await self._affinities.status(user_id, character_id)
            if occasion == "visit" and self._affinities is not None else None
        )
        return KnownNow(self._characters[character_id], affinity)

    def lines(
        self,
        known: KnownNow,
        occasion: Occasion,
        now: datetime,
        timezone: str,
        profile: ProducerProfile,
        last_contact: datetime | None,
        affinity_lines: Sequence[str],
    ) -> list[str]:
        """The lines of now for `occasion`, at `now`, the user in `timezone` with `profile`,
        last in touch at `last_contact` (None if never, or in a call), she feeling as
        `affinity_lines` say. Joined by new lines, they make one section: the time and the
        rest of `now_prompt`, the day's birthdays, the affinity lines last in it. A visit
        is told only how she feels."""
        if occasion == "visit":
            return list(affinity_lines)
        return [
            now_prompt(profile, now, timezone, occasion, affinity_lines, last_contact),
            *today_lines(local_date(now, timezone), known.character, self._characters.values()),
        ]