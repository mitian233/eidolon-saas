"""Characters available for conversation, as the engine sees them.

A character is a row in the database (`character_repository.CharacterRepository`): a user
creates her with a name, a persona sheet, an optional introduction, avatar URL, greeting,
voice, colour, form of address for the user, language mode and optional birthday and age.
The repository produces this `Character` view from the row; the engine and the modules it
mounts read it, never the database directly. The platform stores only addresses for assets
(the avatar URL), never the files themselves.

The fields below that name local files (`avatar`, `background`, `scsp_avatar`, `signature`,
`sheet_path`) or the original's catalogs (`idol_id`, `default_outfit`, the bar and gift and
photo fields) stay for the modules that still read them; a database character leaves them
at their defaults.

Character facts are Markdown; each section under a heading is one fact (`parse_facts`),
retrieved on its own when a turn calls for it.

"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from eidolon.delivery_cues import without_cues
from eidolon.producer import Birthday
from eidolon.readings import Reading

DRAFT_MARKER = "<!-- 人设草稿：由后台模型根据剧情生成，尚未校对。校对完成后删除这一行。 -->"


class CharacterConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Fact:
    """One entry of a character's facts: the section under a heading."""

    title: str | None
    """The headings above it, e.g. `人物关系 / 風野灯織`; None for text before any heading."""
    text: str
    """The entry as it is retrieved, headed by its title."""

    @property
    def headings(self) -> list[str]:
        """The headings above it, the outermost first; none for text before any heading."""
        return self.title.split(" / ") if self.title is not None else []

    @property
    def body(self) -> str:
        """What is under its heading, without its title."""
        return self.text.split("\n", 1)[1].strip() if self.title is not None else self.text


@dataclass(frozen=True)
class ScriptedLine:
    """A line she says on the landing page: written beforehand and reviewed, voiced once in
    her voice; never part of any turn."""

    text: str
    """In Japanese as it is voiced, delivery cues and all (`delivery_cues`)."""
    subtitle: str
    """Its Chinese subtitle."""
    readings: tuple[Reading, ...] = ()
    """The readings Fish Audio uses voicing it (`readings.used_in`), from the readings file
    beside the configuration."""

    @property
    def ja(self) -> str:
        """In Japanese as people see it, without its delivery cues."""
        return without_cues(self.text)


@dataclass(frozen=True)
class Greeting(ScriptedLine):
    """What she says to a producer she meets for the first time, on the landing page."""


@dataclass(frozen=True)
class CallOpener(ScriptedLine):
    """What she says first once the visitor answers her call, in the landing page's demo: to
    a producer she already knows, calling him."""


@dataclass(frozen=True)
class Character:
    id: str
    name: str
    intro: str
    voice_id: str
    sheet: str
    """Her persona: the full text the engine prompts with."""
    avatar: Path | None = None
    color: str = "#64748b"
    """Her image colour as lower-case `#rrggbb`; a slate default for characters without one."""
    birthday: Birthday | None = None
    """Her birthday, if she has one; February 29 falls on February 28 in a year without it,
    as the producer's does (`producer.is_birthday`)."""
    age: int | None = None
    """Her age, if given; whether she is under 18 is what her cycle goes by (`cycles`)."""
    background: Path | None = None
    """The picture behind her call screen; None shows a gradient of her image colour."""
    scsp_avatar: Path | None = None
    """Her avatar in SCSP's set, which users can switch to in settings; None, and they see
    her usual avatar either way."""
    signature: Path | None = None
    """Her handwritten signature, at the end of her letters; None, and she signs with her
    name in the letter's hand."""
    speakers: tuple[str, ...] = ()
    """Names her lines are credited to in story scripts, e.g. 真乃."""
    facts: tuple[Fact, ...] = ()
    """Her character facts, one entry per section of her facts file."""
    sheet_path: Path | None = None
    idol_id: int | None = None
    """Who she is in the original's Spine mirror (`idolId` in `spine_manifest.json`)."""
    default_outfit: str | None = None
    """The outfit her stand wears unless the user picks another, as `<category>/<enzaId>`:
    `stand/1030010010` is her everyday clothes on that card, `stand_costume/...` its stage
    costume. Its files are at `spine/idols/<category>/<enzaId>/` under the stand assets."""
    greeting: Greeting | None = None
    """Her greeting on the landing page; None shows her there without one."""
    call_opener: CallOpener | None = None
    """Her call opener on the landing page; None, and her call there has no words."""
    short_name: str | None = None
    """What the original calls her, the end of her name, e.g. 真乃; None shows her name."""
    name_zh: str | None = None
    """Her name in simplified Chinese as the community writes it, e.g. 八宫巡."""
    name_kana: str | None = None
    """Her full name in hiragana, family name and given name a space apart, e.g. さくらぎ まの."""
    name_romaji: str | None = None
    """Her full name in romaji, family name first, a space apart, e.g. Sakuragi Mano."""
    liked_gifts: tuple[str, ...] = ()
    """The gifts she likes, by identifier in the gift catalog; giving her one raises
    affinity more. Never told to the user."""
    place_likes: tuple[str, ...] | None = None
    """The kinds of place she likes, as the place pool names them (`park`); None, none
    given."""
    bar_flavors: tuple[str, ...] = ()
    """The flavors she likes at the bar, as the drink catalog names them (`sweet`)."""
    bar_kind: str | None = None
    """The kind of drink she likes, as the drink catalog names it (`girly`); None, no kind."""
    bar_favorites: tuple[str, ...] = ()
    """The drinks she loves, by identifier in the drink catalog."""
    bar_disliked_flavor: str | None = None
    """The flavor she will never order; None, none."""
    bar_tolerance: str | None = None
    """How well she holds her drink: `weak`, `medium` or `strong`; None only until
    `drink_catalog.check_bar_tastes` refuses it."""
    photo_tag: str | None = None
    """Her character tag as Danbooru writes it, e.g. `sakuragi mano`, for her photos."""
    photo_appearance: str | None = None
    """Her looks as tags, e.g. `brown hair, medium hair, brown eyes`, for her photos."""
    owner_id: str | None = None
    """The user who created her; None for a character not kept in the database."""
    avatar_url: str | None = None
    """Her avatar as an external URL the platform only stores; None shows none."""
    user_address: str = "你"
    """What she calls the user in her prompts; 「你」 by default."""
    language_mode: Literal["single", "bilingual"] = "single"
    """Whether her replies are one language (`single`, the default) or paired Japanese and
    Chinese (`bilingual`, `<ja><zh>`)."""

    @property
    def photographed(self) -> bool:
        """Whether she can send photos: she has both her character tag and her looks."""
        return self.photo_tag is not None and self.photo_appearance is not None


def in_idol_order(characters: Iterable[Character]) -> list[Character]:
    """The characters in the order of their idol numbers in the original, those without one
    after them as given."""
    return sorted(characters, key=lambda c: (c.idol_id is None, c.idol_id or 0))


def signature_url(character: Character) -> str | None:
    """Where the browser gets her signature; None without one."""
    return f"/api/characters/{character.id}/signature" if character.signature else None


def is_draft(sheet: str) -> bool:
    """Whether a sheet is a draft nobody has reviewed yet."""
    return sheet.lstrip().startswith(DRAFT_MARKER)


_HEADING = re.compile(r"(#{1,6})\s+(.+?)\s*#*\s*")


def parse_facts(markdown: str) -> tuple[Fact, ...]:
    """Split a facts file into entries: the text under each heading, titled with the
    headings above it (e.g. `人物关系 / 風野灯織`). Headings with nothing under them
    make no entry."""
    facts: list[Fact] = []
    titles: list[str] = []
    body: list[str] = []

    def flush() -> None:
        text = "\n".join(body).strip()
        if text:
            title = " / ".join(titles) or None
            facts.append(Fact(title, f"{title}\n{text}" if title else text))
        body.clear()

    for line in markdown.splitlines():
        if heading := _HEADING.fullmatch(line):
            flush()
            del titles[len(heading.group(1)) - 1 :]
            titles.append(heading.group(2))
        else:
            body.append(line)
    flush()
    return tuple(facts)
