"""Characters as the conversation sees them: each one's character sheet in her prompts,
a character added to the registry to talk to, a deleted character's conversation gone,
and her facts split by heading."""

import pytest

from eidolon.characters import Fact, parse_facts
from tests.conftest import KOGANE_SHEET, MANO_SHEET, Characters, ClientFactory
from tests.fakes import FakeLLM
from tests.test_text_turn import send_turn, start_conversation


@pytest.mark.parametrize(
    ("character", "sheet", "other_sheet"),
    [("mano", MANO_SHEET, KOGANE_SHEET), ("kogane", KOGANE_SHEET, MANO_SHEET)],
)
async def test_each_character_talks_with_her_own_character_sheet(
    make_client: ClientFactory, character: str, sheet: str, other_sheet: str
):
    llm = FakeLLM(["<ja>はい</ja><zh>好</zh>"])
    client = make_client(llm)
    conversation_id = await start_conversation(client, character)

    await send_turn(client, conversation_id, "你好")

    system = llm.prompts[0][0]
    assert sheet in system.content
    assert other_sheet not in system.content


async def test_a_character_added_to_the_registry_can_be_talked_to(
    make_client: ClientFactory, characters: Characters
):
    characters.add("hiori", "風野灯織", "# 人设\n你是風野灯織。", intro="认真的努力家")
    llm = FakeLLM(["<ja>はい</ja><zh>好</zh>"])
    client = make_client(llm)

    listed = (await client.get("/api/characters")).json()
    conversation_id = await start_conversation(client, "hiori")
    await send_turn(client, conversation_id, "你好")

    assert [c["id"] for c in listed] == ["mano", "kogane", "hiori"]
    assert "你是風野灯織。" in llm.prompts[0][0].content


async def test_conversation_with_a_deleted_character_is_gone(
    make_client: ClientFactory, characters: Characters
):
    characters.add("hiori", "風野灯織", "# 人设\n你是風野灯織。")
    client = make_client(FakeLLM())
    conversation_id = await start_conversation(client, "hiori")

    assert (await client.delete("/api/characters/hiori")).status_code == 204
    res = await client.post(f"/api/conversations/{conversation_id}/turns", json={"text": "你好"})

    assert res.status_code == 404
    assert res.json()["detail"] == "对话不存在"


def test_character_facts_are_split_by_heading(characters: Characters):
    characters.add(
        "hiori", "風野灯織", "sheet",
        facts="# 档案\n生日是2月27日。\n\n# 人物关系\n\n## 櫻木真乃\n同组合的伙伴。\n### 趣事\n一起去看鸟。\n",
    )

    assert characters["hiori"].facts == (
        Fact("档案", "档案\n生日是2月27日。"),
        Fact("人物关系 / 櫻木真乃", "人物关系 / 櫻木真乃\n同组合的伙伴。"),
        Fact("人物关系 / 櫻木真乃 / 趣事", "人物关系 / 櫻木真乃 / 趣事\n一起去看鸟。"),
    )


def test_text_before_any_heading_is_an_untitled_fact():
    assert parse_facts("生日是2月27日。\n\n# 档案\n身高155cm。") == (
        Fact(None, "生日是2月27日。"),
        Fact("档案", "档案\n身高155cm。"),
    )