"""The reply format and its streaming parser (ADR-0001, D10).

A character replies in one of two language modes. By default (`bilingual=False`) she
writes plain text in whatever language the conversation goes in, with no tags at all;
each sentence or paragraph a segment, shown as it streams with `lang="text"`. A bilingual
character (`bilingual=True`) answers in segments, each a Japanese line followed by its
Chinese subtitle:

    <ja>こんにちは！</ja><zh>你好！</zh>

Either way the parser turns a stream of arbitrary text chunks into per-segment deltas as
soon as they arrive, so the primary text can reach TTS before the reply is finished, and
says when each segment is complete. The segments keep what the model wrote; the deltas
show it without delivery cues, and the primary text is voiced with them (see
`delivery_cues`).

Both modes keep their text in the same `Segment`: the primary text in `ja`, the subtitle
in `zh` (empty in the plain mode), so the store keeps one shape for both.
"""

import re
from dataclasses import dataclass, field
from typing import Literal

from eidolon.config import FishAudioModel
from eidolon.delivery_cues import PAIRED_TAGS, TAG_READERS, CueFilter

Lang = Literal["ja", "zh", "text"]
"""A delta's language: the paired tags of the bilingual mode, or `text` for plain."""

_LENGTH = """\
# 说话长度
像真人当面说话那样：接对方一句话，通常只回一两句。
- 平时只写一到两段，每段只有一句简短的口语。不写长句，不要把几件事塞进一段，也不要用「首先……其次……」这种条理分明的说法。
- 被要求讲一段事情时（包括回忆过去的事），可以多说几句，但最多四段左右；讲到自然的停顿处就停下，剩下的等对方追问再讲，不要一口气讲完。
- 不必每次都用提问收尾，话说完了自然停下就好。
- 对方一次问了几件事，每件都用一句话简短回应，不要漏掉，这时可以超过两段。
- 话多话少、怎么说仍以人设为准；这里只管一次说多少。
"""

_FEELING = """\
# 情绪与语气提示
让情绪自然地流露在措辞里：感叹词、语气词、停顿、口语化的说法。但口吻和口癖始终以人设为准，不要为了显得有情绪而夸张。
"""

_PLAIN_FORMAT = """\
# 回复格式
直接用文字回复，只写要说的话，不要使用任何标签、标记或格式符号。
用什么语言回复以人设为准；人设没有规定时，对方用什么语言就用什么语言回复。
""" + _LENGTH + _FEELING

_PLAIN_CUES = """\
你说的话会被念出来。情绪明显的地方，可以加上语气提示，告诉配音这里该怎么念：用方括号括起简短的英文描述，放在开头管整段，放在句中管它后面的部分。平常说话、交代事情的地方不加，一次回复里通常只有一两处需要。例如：
[shyly] え、えっと……ありがとう。
そっか……[disappointed] 行けないんだ。
常用的有 [happily] [excitedly] [shyly] [embarrassed] [sadly] [disappointed] [sulking] [angrily] [worried] [surprised] [gently] [teasing] [whispering] [laughing] [sleepy]，也可以自由描述，例如 [laughing nervously]，但不要超过四个英文单词。
- 每段最多两个语气提示；拿不准要不要加时就不加。
- 只用方括号加英文，不要用圆括号、方头括号或其他括号，也不要用日语或中文写提示。"""

_PLAIN_DIRECTED_CUES = """\
你说的话会被念出来，配音会像演员一样照你的指示念。情绪明显的地方，可以加上语气提示，告诉配音这里该怎么念：
- 用方括号括起英文的指示，放在开头管整段，放在句中管它后面的部分。可以像导演给演员说戏那样写一句完整的描述，但不要超过十个英文单词。
- 笑声、叹气、吸气、停顿这些声音，也用方括号写在它出现的地方，例如 [small laugh] [sigh] [shaky breath] [pause]。
- 只想改变几个词的念法时，用成对的标签把这几个词括起来：<whisper>小声</whisper>、<emphasis>加重</emphasis>、<soft>轻柔</soft>、<fast>快</fast>、<slow>慢</slow>、<stress>重读</stress>、<forceful>有力</forceful>。标签要在同一句里关上，不要跨句。
平常说话、交代事情的地方不加，一次回复里通常只有一两处需要。例如：
[shyly, glancing away] え、えっと……ありがとう。
[small laugh] これ、<whisper>みんなには内緒</whisper>だよ？
- 每段最多两三处语气提示；拿不准要不要加时就不加。
- 只用方括号加英文，和上面这几种成对标签；不要用圆括号、方头括号或别的标签，也不要用日语或中文写提示。"""

_BILINGUAL_FORMAT = """\
# 回复格式
无论用户用中文还是日语说话，你都只用日语回答，并给每句日语附上中文字幕。
把回复分成段，每段先写日语原文，紧接着写这段的中文字幕，格式如下：
<ja>日语原文</ja><zh>中文字幕</zh>
除了这些标签和标签里的内容，不要输出任何其他文字。
""" + _LENGTH + """\
# 情绪与语气提示
让情绪自然地流露在日语的措辞里：感叹词、语气词、停顿、口语化的说法。但口吻和口癖始终以人设为准，不要为了显得有情绪而夸张。
"""

_CUES = """\
日语原文会被念出来。情绪明显的段，可以在日语原文里加上语气提示，告诉配音这里该怎么念：用方括号括起简短的英文描述，放在段首管整段，放在句中管它后面的部分。平常说话、交代事情的段不加，一次回复里通常只有一两段需要。例如：
<ja>[shyly] え、えっと……ありがとう。</ja><zh>那、那个……谢谢。</zh><ja>明日は十時に集合だよね。</ja><zh>明天是十点集合对吧。</zh>
<ja>そっか……[disappointed] 行けないんだ。</ja><zh>这样啊……去不了了啊。</zh>
常用的有 [happily] [excitedly] [shyly] [embarrassed] [sadly] [disappointed] [sulking] [angrily] [worried] [surprised] [gently] [teasing] [whispering] [laughing] [sleepy]，也可以自由描述，例如 [laughing nervously]，但不要超过四个英文单词。
- 每段最多两个语气提示；拿不准要不要加时就不加。
- 语气提示只写在 <ja> 里；<zh> 只翻译台词，不带语气提示。
- 只用方括号加英文，不要用圆括号、方头括号或其他括号，也不要用日语或中文写提示。"""

_DIRECTED_CUES = """\
日语原文会被念出来，配音会像演员一样照你的指示念。情绪明显的段，可以在日语原文里加上语气提示，告诉配音这里该怎么念：
- 用方括号括起英文的指示，放在段首管整段，放在句中管它后面的部分。可以像导演给演员说戏那样写一句完整的描述，但不要超过十个英文单词。
- 笑声、叹气、吸气、停顿这些声音，也用方括号写在它出现的地方，例如 [small laugh] [sigh] [shaky breath] [pause]。
- 只想改变几个词的念法时，用成对的标签把这几个词括起来：<whisper>小声</whisper>、<emphasis>加重</emphasis>、<soft>轻柔</soft>、<fast>快</fast>、<slow>慢</slow>、<stress>重读</stress>、<forceful>有力</forceful>。标签要在同一句里关上，不要跨句。
平常说话、交代事情的段不加，一次回复里通常只有一两段需要。例如：
<ja>[shyly, glancing away] え、えっと……ありがとう。</ja><zh>那、那个……谢谢。</zh><ja>明日は十時に集合だよね。</ja><zh>明天是十点集合对吧。</zh>
<ja>そっか……[trying to hide her disappointment] 行けないんだ。</ja><zh>这样啊……去不了了啊。</zh>
<ja>[small laugh] これ、<whisper>みんなには内緒</whisper>だよ？</ja><zh>这个，要对大家保密哦？</zh>
- 每段最多两三处语气提示；拿不准要不要加时就不加。
- 语气提示只写在 <ja> 里；<zh> 只翻译台词，不带语气提示。
- 只用方括号加英文，和上面这几种成对标签；不要用圆括号、方头括号或别的标签，也不要用日语或中文写提示。"""


def format_instructions(voiced_by: FishAudioModel | None, *, bilingual: bool = False) -> str:
    """The reply format for a turn of a character in `bilingual` mode or not, voiced, or to
    be read aloud, with `voiced_by`; None for one not voiced at all."""
    if not bilingual:
        if voiced_by is None:
            return _PLAIN_FORMAT
        return _PLAIN_FORMAT + (_PLAIN_DIRECTED_CUES if voiced_by in TAG_READERS else _PLAIN_CUES)
    cues = _DIRECTED_CUES if voiced_by in TAG_READERS else _CUES
    return _BILINGUAL_FORMAT + cues


@dataclass(frozen=True)
class SegmentDelta:
    segment: int
    lang: Lang
    text: str
    type: Literal["delta"] = field(default="delta", init=False)


@dataclass(frozen=True)
class SegmentComplete:
    """Segment `segment` has all it will get. Stays on the server: a call needs to know
    when a reply has a complete segment, the browser does not."""

    segment: int
    type: Literal["segment-complete"] = field(default="segment-complete", init=False)


@dataclass(frozen=True)
class SpeechDelta:
    """More of segment `segment`'s primary text to voice, sent along with the `SegmentDelta`
    that shows it: the same words, but with their delivery cues. Stays on the server."""

    segment: int
    text: str
    type: Literal["speech-delta"] = field(default="speech-delta", init=False)


ParserEvent = SegmentDelta | SpeechDelta | SegmentComplete

_TAGS = ("<ja>", "<zh>")

_PLAIN_BOUNDARY = re.compile(r"[。！？!?\n]")
"""Sentence punctuation or a line break in plain text."""

_PLAIN_TAG = re.compile(rf"<(/?)(?:{'|'.join(PAIRED_TAGS)})>")
_PLAIN_TAGS = tuple(f"<{t}>" for t in PAIRED_TAGS) + tuple(f"</{t}>" for t in PAIRED_TAGS)


@dataclass
class Segment:
    """One segment of a reply: its primary text (`ja`) and its subtitle (`zh`, empty in the
    plain mode). The store keeps both columns for either mode."""

    ja: str = ""
    zh: str = ""


@dataclass
class ReplyParser:
    """Turns a stream of the model's text into segment events, in the character's language
    mode: plain text as sentence and paragraph segments shown with `lang="text"`, or paired
    `<ja><zh>` tags."""

    bilingual: bool = False
    segments: list[Segment] = field(default_factory=list)
    _buffer: str = ""
    _inside: Literal["ja", "zh"] | None = None
    _stray: str = ""
    _said_complete: int = 0  # how many segments are known to be complete
    _line: CueFilter = field(default_factory=CueFilter)  # the open tag's content, the whole reply's in plain
    _events: list[ParserEvent] = field(default_factory=list)
    _plain_break: bool = False  # the next plain text opens a new segment
    _plain_space: str = ""  # whitespace between sentences, waiting for the next one
    _tag_depth: int = 0  # paired delivery tags left open in the plain text
    _tag_tail: str = ""  # a suffix that could be the start of a paired tag

    @property
    def complete(self) -> list[Segment]:
        """The segments said to be complete so far, leaving out any half-written one."""
        return self.segments[: self._said_complete]

    def feed(self, chunk: str) -> list[ParserEvent]:
        if not self.bilingual:
            self._plain_feed(chunk)
            return self._hand_over()
        self._buffer += chunk
        while True:
            if self._inside is None:
                if not self._open_next_tag():
                    return self._hand_over()
            else:
                closed = self._take_content(self._inside)
                if not closed:
                    return self._hand_over()
                self._end_line(self._inside)
                if self._inside == "zh":
                    self._complete_up_to(len(self.segments))
                self._inside = None

    def finish(self) -> list[ParserEvent]:
        """Flush what is left at the end of a stream; the parser can then go on with the
        next stream of the same reply. A bilingual reply that ignored the format becomes
        one Japanese segment."""
        if not self.bilingual:
            if self._plain_space:
                self.segments[-1].ja += self._plain_space
                self._plain_space = ""
            self._end_line("ja")
            self._plain_break = bool(self.segments)
            self._tag_depth, self._tag_tail = 0, ""
        elif self._inside is not None:
            keep = _partial_suffix(self._buffer, (f"</{self._inside}>",))
            text = self._buffer[: len(self._buffer) - keep]
            if text:
                self._append(self._inside, text)
            self._end_line(self._inside)
        elif not self.segments and (self._stray + self._buffer).strip():
            self._append("ja", (self._stray + self._buffer).strip())
            self._end_line("ja")
        self._buffer, self._inside, self._stray = "", None, ""
        self._complete_up_to(len(self.segments))
        return self._hand_over()

    def _plain_feed(self, chunk: str) -> None:
        """Stream each chunk immediately, completing sentences outside delivery cues."""
        start = 0
        for end in _PLAIN_BOUNDARY.finditer(chunk):
            self._plain_append(chunk[start:end.end()])
            self._plain_complete()
            start = end.end()
        if start < len(chunk):
            self._plain_append(chunk[start:])

    def _plain_append(self, text: str) -> None:
        if self._plain_break:
            if not text.strip():
                self._plain_space += text  # no segment of whitespace alone
                return
            self.segments.append(Segment())
            self._plain_break = False
            text = self._plain_space + text
            self._plain_space = ""
        self._append("ja", text)
        self._scan_tags(text)

    def _plain_complete(self) -> None:
        """Complete the segment whose ending has just been seen, unless a delivery cue or
        paired tag is still open in it, or it is whitespace only."""
        if not self._line.in_cue and not self._tag_depth and self.segments[-1].ja.strip():
            self._complete_up_to(len(self.segments))
            self._plain_break = True

    def _scan_tags(self, text: str) -> None:
        """Count the paired delivery tags left open, a chunk possibly ending in the middle
        of one: the start of a tag is held over till the rest of it arrives."""
        text = self._tag_tail + text
        last_end = 0
        for tag in _PLAIN_TAG.finditer(text):
            self._tag_depth = max(0, self._tag_depth + (1 if not tag[1] else -1))
            last_end = tag.end()
        keep = _partial_suffix(text[last_end:], _PLAIN_TAGS)
        self._tag_tail = text[len(text) - keep :] if keep else ""

    def _open_next_tag(self) -> bool:
        starts: list[tuple[int, Literal["ja", "zh"]]] = [
            (i, name) for name in ("ja", "zh") if (i := self._buffer.find(f"<{name}>")) >= 0
        ]
        if not starts:
            keep = _partial_suffix(self._buffer, _TAGS)
            self._stray += self._buffer[: len(self._buffer) - keep]
            self._buffer = self._buffer[len(self._buffer) - keep :]
            return False
        start, lang = min(starts)
        self._stray += self._buffer[:start]
        self._buffer = self._buffer[start + len(f"<{lang}>") :]
        if lang == "ja" or not self.segments or self.segments[-1].zh:
            self._complete_up_to(len(self.segments))
            self.segments.append(Segment())
        self._inside = lang
        self._line = CueFilter()
        return True

    def _take_content(self, lang: Literal["ja", "zh"]) -> bool:
        """Take what there is of the open tag's content; True if the tag closed."""
        close = f"</{lang}>"
        end = self._buffer.find(close)
        closed = end >= 0
        if not closed:
            end = len(self._buffer) - _partial_suffix(self._buffer, (close,))
        text = self._buffer[:end]
        self._buffer = self._buffer[end + len(close) :] if closed else self._buffer[end:]
        if text:
            self._append(lang, text)
        return closed

    def _append(self, lang: Literal["ja", "zh"], text: str) -> None:
        if not text:
            return
        if not self.segments:
            self.segments.append(Segment())
        segment = self.segments[-1]
        setattr(segment, lang, getattr(segment, lang) + text)
        self._show(lang, *self._line.feed(text))

    def _end_line(self, lang: Literal["ja", "zh"]) -> None:
        self._show(lang, *self._line.finish())
        self._line = CueFilter()

    def _show(self, lang: Literal["ja", "zh"], shown: str, voiced: str) -> None:
        """Show what the reply's text has come to, and voice its primary text."""
        if shown:
            delta_lang: Lang = lang if self.bilingual else "text"
            self._events.append(SegmentDelta(len(self.segments) - 1, delta_lang, shown))
        if lang == "ja" and voiced:
            self._events.append(SpeechDelta(len(self.segments) - 1, voiced))

    def _complete_up_to(self, segments: int) -> None:
        """Say the first `segments` segments are complete, those not said to be already."""
        self._events += [SegmentComplete(i) for i in range(self._said_complete, segments)]
        self._said_complete = max(self._said_complete, segments)

    def _hand_over(self) -> list[ParserEvent]:
        """The events since the last were handed over."""
        events, self._events = self._events, []
        return events


def format_reply(segments: list[Segment], *, bilingual: bool = True) -> str:
    """Write segments back as the model wrote them, for earlier replies in the prompt:
    with their paired tags in the bilingual mode, as plain text otherwise."""
    if not bilingual:
        return "".join(s.ja for s in segments if s.ja)
    return "".join(f"<ja>{s.ja}</ja><zh>{s.zh}</zh>" for s in segments)


def _partial_suffix(text: str, tags: tuple[str, ...]) -> int:
    """Length of the longest suffix of `text` that could be the start of one of `tags`."""
    for size in range(min(len(text), max(len(t) for t in tags) - 1), 0, -1):
        if any(t.startswith(text[-size:]) for t in tags):
            return size
    return 0