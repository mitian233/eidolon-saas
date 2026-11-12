"""What she knows of now (GLOSSARY.md「此刻」), as the slim `HerNow` gives it: the time where
the user is, how they are talking, the day's birthdays among the user's own characters, and
how she feels toward them. No schedule, weather, cycle or moments (D12)."""

from datetime import UTC, datetime

from eidolon.characters import Character
from eidolon.her_now import HerNow, KnownNow, Occasion
from eidolon.producer import Birthday, ProducerProfile

NOW = datetime(2026, 9, 25, 12, 30, tzinfo=UTC)  # a Friday
SHANGHAI = "Asia/Shanghai"


def char(id: str, name: str, *, owner: str = "u1", birthday: Birthday | None = None) -> Character:
    return Character(id, name, "简介", "v1", "# 人设", owner_id=owner, birthday=birthday)


def her_now(*characters: Character) -> HerNow:
    return HerNow({c.id: c for c in characters})


async def lines(occasion: Occasion, *characters: Character, affinity_lines=()) -> str:
    now = her_now(*characters)
    known = await now.read("u1", characters[0].id, None, occasion)
    return "\n".join(now.lines(
        known, occasion, NOW, SHANGHAI, ProducerProfile(), None, affinity_lines,
    ))


async def test_typing_tells_the_time_and_that_they_are_typing():
    text = await lines("typing", char("c1", "向导"))
    assert text.startswith("# 此刻\n现在是 2026年9月25日")
    assert "对方正在用文字和你聊天" in text
    assert f"对方所在时区 {SHANGHAI}" in text


async def test_in_a_call_tells_the_call():
    assert "对方正在和你打电话" in await lines("in_call", char("c1", "向导"))


async def test_apart_tells_they_are_not_talking():
    assert "你们这会儿没在说话" in await lines("apart", char("c1", "向导"))


async def test_a_visit_tells_only_how_she_feels():
    text = await lines("visit", char("c1", "向导"), affinity_lines=["你现在很开心"])
    assert text == "你现在很开心"


async def test_the_affinity_lines_come_last():
    text = await lines("typing", char("c1", "向导"), affinity_lines=["你现在很开心"])
    assert text.endswith("你现在很开心")


async def test_a_character_without_a_birthday_is_told_of_none():
    assert "生日" not in await lines("typing", char("c1", "向导"))


async def test_her_birthday_is_told_on_the_day():
    text = await lines("typing", char("c1", "向导", birthday=Birthday(9, 25)))
    assert "今天是你的生日" in text


async def test_only_the_owners_characters_birthdays_are_told():
    text = await lines(
        "typing",
        char("c1", "向导"),
        char("c2", "同伴", birthday=Birthday(9, 25)),
        char("c3", "别人", owner="u2", birthday=Birthday(9, 25)),
    )
    assert "今天是同伴的生日" in text
    assert "别人" not in text


async def test_a_visit_reads_no_affinity_without_affinities():
    known = await her_now(char("c1", "向导")).read("u1", "c1", None, "visit")
    assert known == KnownNow(char("c1", "向导"), None)