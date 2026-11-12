"""Jev judging a segment's emotion: what it is asked through TypeSafe's System One endpoint,
how its Choice answers are read, and how judging is configured."""

import httpx
import pytest

from eidolon.emotion import ModelEmotionJudge, SaidSegment, SegmentToJudge
from eidolon.judge import JevJudge, JudgeError
from tests.test_retrieval_services import MANO, client, recording

SEGMENT = SegmentToJudge(
    MANO, "你今天很可爱",
    [SaidSegment("[shyly]ほわっ……", "哇……")],
    SaidSegment("ありがとうございます！", "谢谢！"),
)


def answered(requests: list[dict], answers: dict) -> ModelEmotionJudge:
    body = {"model": "typesafe/jev-1.13-20260917", "answers": answers}
    return ModelEmotionJudge(JevJudge(
        "jev-key", "typesafe/jev-1.13", "http://jev.test/api/v1",
        client(recording(requests, httpx.Response(200, json=body))),
    ))


# Keys in no fixed order, as Jev sends them.
EMOTION = {"type": "choice", "choice": "害羞", "confidence": 0.47, "probabilities": {
    "生气": 0, "难过": 0, "平静": 0, "开心": 0.45, "害羞": 0.54, "惊讶": 0.01, "思考": 0,
}}
NOD = {"type": "choice", "choice": "都不是", "confidence": 0.8, "probabilities": {
    "否定": 0.02, "都不是": 0.9, "同意": 0.08,
}}


async def test_jev_is_asked_both_questions_of_the_segment_at_once():
    requests: list[dict] = []

    await answered(requests, {"emotion": EMOTION, "nod": NOD}).judge_emotion(SEGMENT)

    [request] = requests
    assert request["url"] == "http://jev.test/api/v1/systemone"
    assert request["auth"] == "Bearer jev-key"
    assert request["state"] == {
        "角色": "櫻木真乃",
        "用户这句话": "你今天很可爱",
        "这条回复前面几段": ["[shyly]ほわっ……（哇……）"],
        "这一段台词": "ありがとうございます！",
        "这一段的中文字幕": "谢谢！",
    }
    emotion, nod = request["questions"]["emotion"], request["questions"]["nod"]
    assert emotion["type"] == nod["type"] == "choice"
    assert set(emotion["criteria"]) == {"平静", "开心", "害羞", "惊讶", "难过", "生气", "思考"}
    assert set(nod["criteria"]) == {"同意", "否定", "都不是"}


async def test_the_first_segment_has_none_before_it():
    requests: list[dict] = []
    first = SegmentToJudge(MANO, "早上好", [], SaidSegment("おはよう！", "早上好！"))

    await answered(requests, {"emotion": EMOTION, "nod": NOD}).judge_emotion(first)

    assert requests[0]["state"]["这条回复前面几段"] == "（这是回复的第一段）"


async def test_a_plain_segment_without_a_subtitle_is_judged_as_it_is():
    requests: list[dict] = []
    plain = SegmentToJudge(
        MANO, "你今天很可爱",
        [SaidSegment("[shyly]谢谢……", "")],
        SaidSegment("不客气！", ""),
    )

    await answered(requests, {"emotion": EMOTION, "nod": NOD}).judge_emotion(plain)

    assert requests[0]["state"]["这条回复前面几段"] == ["[shyly]谢谢……"]
    assert requests[0]["state"]["这一段的中文字幕"] == ""


async def test_jevs_answers_are_read_by_option_name():
    answer = await answered([], {"emotion": EMOTION, "nod": NOD}).judge_emotion(SEGMENT)

    assert answer.emotions == {
        "angry": 0, "sad": 0, "calm": 0, "happy": 0.45, "shy": 0.54, "surprised": 0.01,
        "thinking": 0,
    }
    assert answer.nods == {"no": 0.02, None: 0.9, "yes": 0.08}


@pytest.mark.parametrize(
    "answers",
    [
        {"emotion": EMOTION},
        {"emotion": {"type": "choice", "probabilities": {"大哭": 1}}, "nod": NOD},
        {"emotion": EMOTION, "nod": {"type": "noul", "noul": 0.9}},
    ],
    ids=["missing", "no known option", "not a choice"],
)
async def test_answers_that_cannot_be_read_are_reported(answers: dict):
    with pytest.raises(JudgeError, match="nod|emotion"):
        await answered([], answers).judge_emotion(SEGMENT)


async def test_jev_errors_are_reported():
    judge = ModelEmotionJudge(JevJudge(
        "k", "typesafe/jev-1.13", "http://jev.test/api/v1",
        client(lambda _: httpx.Response(429, text="slow down")),
    ))

    with pytest.raises(JudgeError, match="429"):
        await judge.judge_emotion(SEGMENT)

