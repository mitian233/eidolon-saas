"""What she is told of the day it is where the user is (GLOSSARY.md「日历」): whether it is
her birthday, if she has one, and whose of the user's other characters' it is. Each line is
told only on its day, in what she is told of now (GLOSSARY.md「此刻」, `HerNow`); none on a
day that is none of them. The user's own birthday goes by their day, and is told by
`producer.now_prompt`.

Only the characters of the same owner are told of together: a user's characters are their
own (D13), and one owner's characters know nothing of another's.

The Tokyo day helpers (`TOKYO`, `tokyo_date`, `venues_on_this_day`) are kept for the modules
that still reckon by the day where the character lives; the prompts themselves no longer
assume any original work's calendar.
"""

from collections.abc import Iterable, Sequence
from datetime import date, datetime
from zoneinfo import ZoneInfo

from eidolon.characters import Character
from eidolon.producer import is_birthday
from eidolon.world import Live, LiveDay, World

TOKYO = ZoneInfo("Asia/Tokyo")

_HER_BIRTHDAY = (
    "今天是你的生日。可以自然地提起一两次，不要每句都提；对方祝福你就接受。"
)


def tokyo_date(now: datetime) -> date:
    """The day it is in Tokyo at `now`."""
    return now.astimezone(TOKYO).date()


def her_birthday(character: Character) -> str | None:
    """Her birthday as she always knows it, the same for every user; None if she has none."""
    if character.birthday is None:
        return None
    return f"你的生日是{character.birthday.month}月{character.birthday.day}日。"


def always_known(character: Character, world_prompt: str | None = None) -> list[str]:
    """What every prompt of hers opens with, the same for every user that day, for a service
    to cache (ADR-0020): her character sheet, her birthday if she has one, then the world
    setting, if any."""
    birthday = her_birthday(character)
    return [
        character.sheet,
        *([birthday] if birthday else []),
        *([world_prompt] if world_prompt else []),
    ]


def today_lines(local: date, character: Character, characters: Iterable[Character]) -> list[str]:
    """What `character` is told of the day it is where the user is, `local`: her birthday,
    and the birthdays of the user's other characters (those of the same owner), each if it
    is the day. A character without a birthday is told of none."""
    lines: list[str] = []
    if character.birthday is not None and is_birthday(character.birthday, local):
        lines.append(_HER_BIRTHDAY)
    others = [
        c.name
        for c in characters
        if c.id != character.id
        and c.owner_id == character.owner_id
        and c.birthday is not None
        and is_birthday(c.birthday, local)
    ]
    if others:
        lines.append(
            f"今天是{'、'.join(others)}的生日。你知道这件事，对方提起时能接上；不用主动提。"
        )
    return lines


def venues_on_this_day(now: datetime, character: Character, world: World | None) -> list[str]:
    """Where the days of the lives `character` stood on in `world` that fell on the day it
    is in Tokyo at `now`, in a year before, were, earliest first."""
    her_lives = world.lives_of(character.name) if world else []
    return [day.venue for _, day in _days_on_this_day(tokyo_date(now), her_lives)]


def _days_on_this_day(
    today: date, her_lives: Sequence[tuple[Live, Sequence[LiveDay]]]
) -> list[tuple[Live, LiveDay]]:
    """The days she stood on that fell on `today`'s month and day in a year before,
    earliest first."""
    found = [
        (live, day) for live, days in her_lives for day in days
        if day.date.year < today.year and (day.date.month, day.date.day) == (today.month, today.day)
    ]
    return sorted(found, key=lambda f: f[1].date)