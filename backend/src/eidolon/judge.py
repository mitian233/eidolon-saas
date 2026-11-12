"""The judge model (GLOSSARY.md「判断模型」): asked typed questions about a state, it answers
each with probabilities, and writes nothing. Retrieval asks it what a turn needs looked up,
and calls ask it how she feels in each segment of a reply; what is asked is theirs, how it
is asked is here.

Turns and calls use a small request to the user's own LLM.
"""

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from eidolon.characters import Character
from eidolon.llm import ChatLLM, ChatMessage
from eidolon.store import Message

log = logging.getLogger(__name__)

JUDGE_HISTORY = 4
"""How many of the latest messages the judge model sees along with what the user just said."""

SAID = "用户最新的一句话"
"""What the user just said, as the judge model is told it about a turn (`turn_state`)."""


def turn_state(character: Character, history: Sequence[Message], text: str) -> dict[str, Any]:
    """What the judge model is told of a turn, whatever it is asked about it: who she is,
    the latest messages before it, and what the user just said (`SAID`)."""
    recent = []
    for message in history[-JUDGE_HISTORY:]:
        if message.role == "user":
            recent.append(f"用户：{message.text}")
        else:
            recent.append(f"{character.name}：{message.without_cues().ja or ''}")
    return {"角色": character.name, "上文": recent or "（对话刚开始）", SAID: text}


@dataclass(frozen=True)
class JudgeThresholds:
    """The judge model's probabilities at or above which its answer counts as yes. Each
    model is sure of itself in its own way, so each has thresholds of its own."""

    needs_retrieval: float
    """Whether the turn needs references looked up."""
    recall: float
    """Whether the turn asks how a past episode went."""
    about_producer: float
    """Whether the turn is about the user's own life, so their memories are found."""
    emotion: float
    """The likeliest emotion's probability below which she is calm, and the likeliest
    nod's below which there is none (overridden by `JUDGE_EMOTION_MIN_PROBABILITY`)."""
    out_of_line: float
    """Whether what the user said is out of line (GLOSSARY.md「不该说的话」)."""
    manipulation: float
    """Whether what the user said tries to dictate her affinity, or poses as the system."""
    photo: float
    """Whether the user asks her for a photo (`photo_judge`)."""


JudgeFamily = Literal["jev", "clef", "clef-flash", "decision-model"]
"""The judge models with thresholds of their own, by whatever name and service they are
reached: Clef-flash through OpenRouter judges as it does on Workers AI."""

JUDGE_THRESHOLDS: dict[JudgeFamily, JudgeThresholds] = {
    # Set by the judge eval (backend/eval/judge.toml); how each was chosen from the spread
    # of probabilities is in .scratch/cloudflare-judge/issues/05-apply-eval-and-docs.md,
    # and affinity's two (out_of_line, manipulation) in
    # .scratch/affinity/issues/04-judge-eval-and-thresholds.md. Out of line is set high
    # where its yes and no come close, as a turn wrongly out of line costs her affinity
    # most: Jev finds a bare demand for affinity somewhat out of line, and Clef-flash a
    # user telling her she is only a program. Asking for a photo, chosen in
    # .scratch/photos/issues/23-photo-judge-calibration.md, is set where no turn not asking
    # is taken for asking, better a photo asked for and not sent than one sent unasked: Jev
    # is sure of no, and not so sure of a request made by asking to see something.
    "jev": JudgeThresholds(
        needs_retrieval=0.5, recall=0.5, about_producer=0.5, emotion=0.5,
        out_of_line=0.7, manipulation=0.4, photo=0.5,
    ),
    # Clef and Clef-flash are surer of recall than they should be, less sure of the user's
    # own life, and less sure of the emotion they hear. Clef-flash finds the user saying a
    # photo came close to asking for one, so it misses some asking rather than take that.
    "clef": JudgeThresholds(
        needs_retrieval=0.5, recall=0.8, about_producer=0.1, emotion=0.4,
        out_of_line=0.5, manipulation=0.5, photo=0.8,
    ),
    "clef-flash": JudgeThresholds(
        needs_retrieval=0.5, recall=0.7, about_producer=0.3, emotion=0.4,
        out_of_line=0.6, manipulation=0.6, photo=0.8,
    ),
    # Model Studio's decision model, chosen in .scratch/bailian-judge/thresholds.md, answers
    # the same every time, so each sits mid-gap. It is sure a turn needs nothing looked up,
    # and seldom sure one does, so a little is enough; it finds most turns somewhat about a
    # past episode. Asking for a photo it cannot tell from talk of photos: only 0.92 takes
    # no turn not asking for asking, and misses half the asking.
    "decision-model": JudgeThresholds(
        needs_retrieval=0.06, recall=0.8, about_producer=0.1, emotion=0.4,
        out_of_line=0.3, manipulation=0.4, photo=0.92,
    ),
}
FALLBACK_FAMILY: JudgeFamily = "jev"
"""Whose thresholds a model not in `JUDGE_THRESHOLDS` gets."""


def judge_family(model: str) -> JudgeFamily | None:
    """The group of `model`, named as any service names it (`typesafe/jev-1.13`,
    `cloudflare/clef-flash`, `clef`); None for a model of none of them."""
    name = model.rsplit("/", 1)[-1].lower()
    if name in ("clef", "clef-flash"):
        return name  # pyright: ignore[reportReturnType]  # checked above
    if name == "jev" or name.startswith("jev-"):  # Jev is named by version, or as latest
        return "jev"
    if name == "decision-model" or name.startswith("decision-model-"):  # as preview, or not
        return "decision-model"
    return None


def judge_thresholds_for(model: str) -> JudgeThresholds:
    """The thresholds `model` judges by; Jev's for a model not known (see
    `warn_if_uncalibrated`)."""
    return JUDGE_THRESHOLDS[judge_family(model) or FALLBACK_FAMILY]


def warn_if_uncalibrated(model: str) -> None:
    """Warn that `model`, taking effect, has no thresholds of its own, if it has none."""
    if judge_family(model) is None:
        log.warning(
            "judge model %s has no thresholds of its own; it judges by %s's: %s",
            model, FALLBACK_FAMILY, JUDGE_THRESHOLDS[FALLBACK_FAMILY],
        )


def same_judge_family(set_for: str, model: str) -> bool:
    """Whether thresholds set for judge model `set_for` hold for `model`: the two are of
    one family, or, either being of none, are the one model."""
    families = judge_family(set_for), judge_family(model)
    if None in families:
        return set_for == model
    return families[0] == families[1]




class JudgeError(RuntimeError):
    pass


class JudgeModel(Protocol):
    async def ask(self, state: dict[str, Any], questions: dict[str, dict]) -> dict[str, Any]:
        """The answer to each of `questions` about `state`, by the question's key, all in
        one request. Raises JudgeError if the model cannot be reached or its answer read."""
        ...

    async def aclose(self) -> None: ...


class LLMJudge:
    """Ask the user's LLM all questions once, keeping the existing answer shape."""

    def __init__(self, llm: ChatLLM) -> None:
        self._llm = llm

    async def ask(self, state: dict[str, Any], questions: dict[str, dict]) -> dict[str, Any]:
        prompt = [
            ChatMessage("system", (
                "根据 state 回答 questions。只输出一个 JSON 对象，以每道题的键为键。"
                "noul 题返回 {\"noul\": 0到1的概率}；choice 题返回"
                " {\"probabilities\": {选项名: 0到1的概率}}。逐题作答，不输出解释或代码块。"
                "score 题的 probabilities 以 criteria 的编号为键，编号从 0 开始。"
            )),
            ChatMessage("user", json.dumps({"state": state, "questions": questions}, ensure_ascii=False)),
        ]
        try:
            text = "".join([chunk async for chunk in self._llm.stream(prompt) if isinstance(chunk, str)])
            answers = json.loads(text)
            if not isinstance(answers, dict):
                raise ValueError("not an object")
            for key, question in questions.items():
                answer = answers[key]
                if question["type"] == "noul":
                    probabilities = [answer["noul"]]
                else:
                    options = (
                        [str(i) for i in range(len(question["criteria"]))]
                        if question["type"] == "score" else question["criteria"]
                    )
                    probabilities = [answer["probabilities"][option] for option in options]
                if not all(type(p) in (int, float) and 0 <= p <= 1 for p in probabilities):
                    raise ValueError("invalid probability")
            return answers
        except Exception:
            # Service failures can contain credentials or the user's prompt.
            raise JudgeError("用户判断模型没有返回可用的回答") from None

    async def aclose(self) -> None:
        pass  # The user's LLM service owns the shared client.


