"""What she knows of now (GLOSSARY.md「此刻」), as the slim `HerNow` gives it: the time where
the user is, how they are talking, the day's birthdays among the user's own characters, and
how she feels toward them. No schedule, weather, cycle or moments (D12)."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from eidolon.character_repository import CharacterRepository
from eidolon.characters import Character
from eidolon.data_access import Database
from eidolon.her_now import HerNow, Occasion
from eidolon.producer import Birthday, ProducerProfile
from eidolon.store import Store
from tests.conftest import seed_database_character

NOW = datetime(2026, 9, 25, 12, 30, tzinfo=UTC)  # a Friday
SHANGHAI = "Asia/Shanghai"


def char(id: str, name: str, *, owner: str = "u1", birthday: Birthday | None = None) -> Character:
    return Character(id, name, "简介", "v1", "# 人设", owner_id=owner, birthday=birthday)


@pytest.fixture
async def database(tmp_path: Path):
    db = Database(tmp_path / "eidolon.db")
    try:
        yield db
    finally:
        await db.close()


async def her_now(database: Database, *characters: Character) -> tuple[HerNow, str]:
    store = Store(database)
    repository = CharacterRepository(database)
    owners: dict[str, str] = {}
    for character in characters:
        owner = character.owner_id
        assert owner is not None
        if owner not in owners:
            owners[owner] = (await store.create_user(owner)).id
        await seed_database_character(database, repository, owners[owner], character.id, character)
    return HerNow(repository), owners["u1"]


async def lines(database: Database, occasion: Occasion, *characters: Character, affinity_lines=()) -> str:
    now, user_id = await her_now(database, *characters)
    known = await now.read(user_id, characters[0].id, None, occasion)
    return "\n".join(now.lines(
        known, occasion, NOW, SHANGHAI, ProducerProfile(), None, affinity_lines,
    ))


async def test_typing_tells_the_time_and_that_they_are_typing(database: Database):
    text = await lines(database, "typing", char("c1", "向导"))
    assert text.startswith("# 此刻\n现在是 2026年9月25日")
    assert "对方正在用文字和你聊天" in text
    assert f"对方所在时区 {SHANGHAI}" in text


async def test_in_a_call_tells_the_call(database: Database):
    assert "对方正在和你打电话" in await lines(database, "in_call", char("c1", "向导"))


async def test_apart_tells_they_are_not_talking(database: Database):
    assert "你们这会儿没在说话" in await lines(database, "apart", char("c1", "向导"))


async def test_a_visit_tells_only_how_she_feels(database: Database):
    text = await lines(database, "visit", char("c1", "向导"), affinity_lines=["你现在很开心"])
    assert text == "你现在很开心"


async def test_the_affinity_lines_come_last(database: Database):
    text = await lines(database, "typing", char("c1", "向导"), affinity_lines=["你现在很开心"])
    assert text.endswith("你现在很开心")


async def test_a_character_without_a_birthday_is_told_of_none(database: Database):
    assert "生日" not in await lines(database, "typing", char("c1", "向导"))


async def test_her_birthday_is_told_on_the_day(database: Database):
    text = await lines(database, "typing", char("c1", "向导", birthday=Birthday(9, 25)))
    assert "今天是你的生日" in text


async def test_only_the_owners_characters_birthdays_are_told(database: Database):
    text = await lines(
        database,
        "typing",
        char("c1", "向导"),
        char("c2", "同伴", birthday=Birthday(9, 25)),
        char("c3", "别人", owner="u2", birthday=Birthday(9, 25)),
    )
    assert "今天是同伴的生日" in text
    assert "别人" not in text


async def test_a_visit_reads_no_affinity_without_affinities(database: Database):
    now, user_id = await her_now(database, char("c1", "向导"))
    known = await now.read(user_id, "c1", None, "visit")
    assert known.character.id == "c1"
    assert known.character.owner_id == user_id
    assert known.affinity is None