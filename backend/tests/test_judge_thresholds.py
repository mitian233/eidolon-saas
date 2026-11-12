"""The judge model's thresholds, given per model: which group a model's name falls in, what
an unknown model gets, that retrieval and emotion judging use them, and how the emotion
settings override them."""

import logging
import asyncio
import json
from dataclasses import replace

import pytest

import eidolon.judge
import eidolon.live_config
from eidolon.config import EmotionSettings, Settings
from eidolon.judge import (
    JUDGE_THRESHOLDS,
    JudgeThresholds,
    judge_family,
    judge_thresholds_for,
    same_judge_family,
    warn_if_uncalibrated,
)
from eidolon.retrieval import ModelRetrievalJudge
from eidolon.account_api import OwnKeysInput
from tests.fakes import JUDGED_KEYS, FakeLLM, FakeLLMService, build_faked
from tests.test_emotion_judge import EMOTION, NOD, SEGMENT
from tests.test_retrieval_services import MANO

ODD = JudgeThresholds(
    needs_retrieval=0.3, recall=0.7, about_producer=0.9, emotion=0.8, out_of_line=0.6,
    manipulation=0.4, photo=0.2,
)
"""Thresholds none of which is 0.5, to see that each is the one used."""


@pytest.mark.parametrize(
    "model, family",
    [
        ("typesafe/jev-1.13", "jev"),
        ("Cloudflare/Clef-Flash", "clef-flash"),
        ("clef", "clef"),
        ("cloudflare/clef-2", None),  # a new Clef is not judged by the old one's thresholds
        ("decision-model-preview", "decision-model"),
        ("decision-model", "decision-model"),  # out of preview, judged alike until shown not to
        ("decision-modeller", None),
    ],
)
def test_a_models_name_falls_in_its_group(model: str, family: str | None):
    assert judge_family(model) == family


def test_a_known_model_gets_its_groups_thresholds(caplog: pytest.LogCaptureFixture):
    with caplog.at_level(logging.WARNING):
        thresholds = judge_thresholds_for("cloudflare/clef-flash")

    assert thresholds == JUDGE_THRESHOLDS["clef-flash"]
    assert not caplog.records


def test_an_unknown_model_gets_jevs(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setitem(JUDGE_THRESHOLDS, "jev", ODD)

    assert judge_thresholds_for("someone/new-judge") == ODD


def test_only_an_unknown_model_is_warned_of(caplog: pytest.LogCaptureFixture):
    with caplog.at_level(logging.WARNING):
        warn_if_uncalibrated("typesafe/jev-1.14")
        warn_if_uncalibrated("someone/new-judge")

    [warning] = caplog.records
    assert "someone/new-judge" in warning.getMessage()


@pytest.mark.parametrize(
    "set_for, model, holds",
    [
        ("typesafe/jev-1.13", "jev-1.14", True),
        ("typesafe/jev-1.13", "clef", False),
        ("someone/new-judge", "someone/new-judge", True),
        ("someone/new-judge", "jev-1.13", False),
    ],
)
def test_thresholds_set_for_a_model_hold_for_its_family(set_for: str, model: str, holds: bool):
    assert same_judge_family(set_for, model) is holds


@pytest.mark.parametrize(
    "retrieve, recall, about_producer, expected",
    [
        (0.29, 0.69, 0.89, "nothing"),  # 0.5 would have recalled
        (0.29, 0.7, 0.1, "recall"),
        (0.3, 0.1, 0.1, "references"),  # 0.5 would have looked up nothing
        (0.1, 0.1, 0.9, "memories"),
    ],
)
async def test_retrieval_judges_by_the_thresholds_it_is_given(
    retrieve: float, recall: float, about_producer: float, expected: str
):
    answers = {
        "needs_retrieval": {"type": "noul", "noul": retrieve},
        "recall": {"type": "noul", "noul": recall},
        "about_producer": {"type": "noul", "noul": about_producer},
    }
    judge_model = eidolon.judge.LLMJudge(FakeLLM([json.dumps(answers)]))

    assert await ModelRetrievalJudge(judge_model, ODD).judge(MANO, [], "那次比赛") == (expected, None, False)


@pytest.mark.parametrize("model, explicit, expected", [
    ("unknown-user-model", None, "calm"),
    ("unknown-user-model", 0.3, "shy"),
    ("typesafe/clef", None, "shy"),
    ("typesafe/clef", 0.9, "calm"),
])
async def test_user_emotion_prefers_explicit_settings_over_model_and_fallback(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, model: str,
    explicit: float | None, expected: str,
):
    monkeypatch.setitem(JUDGE_THRESHOLDS, "jev", replace(ODD, emotion=0.8))
    monkeypatch.setitem(JUDGE_THRESHOLDS, "clef", replace(ODD, emotion=0.5))
    own = FakeLLMService(FakeLLM([json.dumps({"emotion": EMOTION, "nod": NOD})]))
    backend = build_faked(replace(settings, emotion=EmotionSettings(explicit, 0.2)), own_llm_service=own)
    keys = JUDGED_KEYS | {"llm": {**JUDGED_KEYS["llm"], "model": model}}
    call = backend.own_keys.for_call(OwnKeysInput.model_validate(keys).brought())
    try:
        assert call.emotions is not None
        message = await call.emotions.message(1, 0, SEGMENT)
        assert message is not None and message["emotion"] == expected
        assert own.llm.keys == ["test-user-secret"]
    finally:
        call.release()
        await backend.aclose()


async def test_user_emotion_stops_at_the_configured_timeout(settings: Settings):
    cancelled = asyncio.Event()

    class WaitingLLM(FakeLLM):
        async def stream_with(self, key, messages, tools=(), *, forbid_calls=False):
            try:
                await asyncio.Event().wait()
                yield "unreachable"
            finally:
                cancelled.set()

    backend = build_faked(replace(settings, emotion=EmotionSettings(timeout=0.01)), own_llm_service=FakeLLMService(WaitingLLM()))
    keys = JUDGED_KEYS | {"llm": {**JUDGED_KEYS["llm"], "model": "unknown-user-model"}}
    call = backend.own_keys.for_call(OwnKeysInput.model_validate(keys).brought())
    try:
        assert call.emotions is not None
        assert call.emotions.timeout == 0.01
        assert await call.emotions.message(1, 0, SEGMENT) is None
        assert cancelled.is_set()
    finally:
        call.release()
        await backend.aclose()


def test_judging_is_tuned_from_the_environment(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("JUDGE_EMOTION_MIN_PROBABILITY", "0.6")
    monkeypatch.setenv("JUDGE_EMOTION_TIMEOUT", "2")

    assert EmotionSettings.from_env() == EmotionSettings(min_probability=0.6, timeout=2.0)


def test_judging_defaults_to_the_models_threshold_and_a_second_and_a_half(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("JUDGE_EMOTION_MIN_PROBABILITY", raising=False)
    monkeypatch.setenv("JUDGE_EMOTION_TIMEOUT", "")

    assert EmotionSettings.from_env() == EmotionSettings(min_probability=None, timeout=1.5)


@pytest.mark.parametrize(
    "name, value", [("JUDGE_EMOTION_MIN_PROBABILITY", "1.5"), ("JUDGE_EMOTION_TIMEOUT", "0")]
)
def test_judging_tuned_out_of_range_stops_the_start(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
):
    monkeypatch.setenv(name, value)

    with pytest.raises(RuntimeError, match=name):
        EmotionSettings.from_env()


@pytest.mark.parametrize("name", ["JEV_EMOTION_TIMEOUT", "JEV_EMOTION_MIN_PROBABILITY"])
def test_legacy_emotion_names_are_ignored(monkeypatch: pytest.MonkeyPatch, name: str):
    monkeypatch.setenv(name, "invalid-retired-value")
    monkeypatch.delenv("JUDGE_EMOTION_TIMEOUT", raising=False)
    monkeypatch.delenv("JUDGE_EMOTION_MIN_PROBABILITY", raising=False)
    assert EmotionSettings.from_env() == EmotionSettings()
    assert Settings.from_env().emotion == EmotionSettings()



def test_the_old_names_left_empty_are_no_matter(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("JEV_EMOTION_MIN_PROBABILITY", "")
    monkeypatch.setenv("JEV_EMOTION_TIMEOUT", "")

    assert EmotionSettings.from_env() == EmotionSettings()
