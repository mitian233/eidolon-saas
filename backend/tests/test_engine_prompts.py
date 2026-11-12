"""The retained prompt paths are generic: they address the user by the character's own
user address, assume no office or original work, and follow the character's language mode
(D10). The calendar is optional-birthday safe and private to the owner (D13)."""

from typing import Literal

from eidolon.characters import Character
from eidolon.assembly import build
from eidolon.config import Settings
import pytest
from eidolon.producer import Birthday, ProducerProfile, producer_prompt
from eidolon.reply_format import Segment
from eidolon.store import Message
from eidolon.today import always_known


def character(
    *,
    id: str = "c1",
    name: str = "向导",
    owner_id: str = "u1",
    birthday: Birthday | None = None,
    language_mode: Literal["single", "bilingual"] = "single",
) -> Character:
    return Character(
        id=id, name=name, intro="山间向导", voice_id="v1", sheet="# 人设\n你是山间向导。",
        owner_id=owner_id, birthday=birthday, language_mode=language_mode,
    )


@pytest.fixture
async def engine(tmp_path):
    backend = build(Settings(database_path=tmp_path / "prompts.db"))
    try:
        yield backend.engine
    finally:
        await backend.aclose()


def reply(ja: str, zh: str = "") -> Message:
    return Message(
        1, "character", None, ja, zh, "2026-01-01T00:00:00Z", [Segment(ja=ja, zh=zh)],
    )


def test_the_user_is_addressed_by_the_characters_own_address():
    prompt = producer_prompt(ProducerProfile(), "旅人")
    assert "「旅人」" in prompt
    assert "制作人" not in prompt and "事务所" not in prompt and "原作" not in prompt




def test_the_profile_address_overrides_the_characters():
    prompt = producer_prompt(ProducerProfile(form_of_address="老师"), "旅人")
    assert "「老师」" in prompt and "「旅人」" not in prompt


def test_the_prompt_opens_with_the_sheet_and_plain_format_by_default(engine):
    prompt = engine._prompt(
        character(), producer_prompt(ProducerProfile(), "你"), [], {}, [], [], "你好", None, False,
    )
    opening = prompt[0].content
    assert "# 人设" in opening
    assert "<ja>" not in opening and "<zh>" not in opening


def test_plain_history_is_written_back_without_tags(engine):
    prompt = engine._prompt(
        character(), "关于用户", [reply("你好，今天过得怎么样？")], {}, [], [], "在的", None, False,
    )
    assert prompt[2].content == "你好，今天过得怎么样？"


def test_a_character_without_a_birthday_is_told_of_none():
    assert always_known(character()) == ["# 人设\n你是山间向导。"]


def test_a_character_with_a_birthday_is_told_of_it():
    her = character(birthday=Birthday(1, 1))
    assert "你的生日是1月1日。" in always_known(her)


