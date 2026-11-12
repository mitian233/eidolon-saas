"""The reply format in both language modes: plain text by default, paired Japanese and
Chinese tags when the character is bilingual (D10)."""

from eidolon.delivery_cues import voiced, without_cues
from eidolon.reply_format import (
    ReplyParser,
    Segment,
    SegmentComplete,
    SegmentDelta,
    SpeechDelta,
    format_instructions,
    format_reply,
)


def parse(bilingual: bool, *chunks: str):
    parser = ReplyParser(bilingual=bilingual)
    events = [e for chunk in chunks for e in parser.feed(chunk)] + parser.finish()
    shown = [(e.segment, e.lang, e.text) for e in events if isinstance(e, SegmentDelta)]
    voiced = [(e.segment, e.text) for e in events if isinstance(e, SpeechDelta)]
    complete = [e.segment for e in events if isinstance(e, SegmentComplete)]
    return shown, voiced, complete, parser


def test_plain_text_streams_as_text_without_tags():
    shown, voiced, complete, parser = parse(False, "你好，", "今天过得怎么样？")
    assert shown == [(0, "text", "你好，"), (0, "text", "今天过得怎么样？")]
    assert complete == [0]
    assert parser.complete == [Segment(ja="你好，今天过得怎么样？", zh="")]
    assert "".join(text for _, text in voiced) == "你好，今天过得怎么样？"


def test_plain_sentences_complete_as_they_are_written():
    parser = ReplyParser()
    events = parser.feed("第一句。第二句。")
    assert [e.segment for e in events if isinstance(e, SegmentComplete)] == [0, 1]
    assert parser.complete == [Segment(ja="第一句。"), Segment(ja="第二句。")]
    assert parser.finish() == []


def test_plain_paragraphs_complete_at_the_line_break():
    shown, _, complete, parser = parse(False, "第一行\n", "第二行\n")
    assert complete == [0, 1]
    assert parser.complete == [Segment(ja="第一行\n"), Segment(ja="第二行\n")]
    assert "".join(text for _, _, text in shown) == "第一行\n第二行"


def test_plain_completion_waits_for_cues_and_paired_tags_to_close():
    _, _, complete, parser = parse(
        False, "（うれしくって！）おめでとう。<whisper>内緒だよ？</whisper>本当。"
    )
    assert complete == [0, 1]
    assert parser.complete == [
        Segment(ja="（うれしくって！）おめでとう。"),
        Segment(ja="<whisper>内緒だよ？</whisper>本当。"),
    ]


def test_plain_text_is_the_same_whatever_chunks_it_arrives_in():
    text = "第一句。第二句！\n第三句？[shyly] 谢谢。\n"

    def results_of(*chunks: str):
        parser = ReplyParser()
        events = [e for chunk in chunks for e in parser.feed(chunk)] + parser.finish()
        return (
            "".join(e.text for e in events if isinstance(e, SegmentDelta)),
            "".join(e.text for e in events if isinstance(e, SpeechDelta)),
            "".join(s.ja for s in parser.segments),
            [e.segment for e in events if isinstance(e, SegmentComplete)],
            parser.segments,
        )

    whole = results_of(text)
    for size in (1, 2, 3, 5, 7):
        chunks = (text[i : i + size] for i in range(0, len(text), size))
        shown, speech, raw, complete, segments = results_of(*chunks)
        assert (shown, speech, raw) == whole[:3]  # the text, not the chunk sizes it came in
        assert complete == list(range(len(segments)))
        assert all(s.ja.strip() for s in segments)
    assert whole[0] == without_cues(text)
    assert whole[1] == voiced(text)
    assert whole[2] == text


def test_plain_format_reply_joins_segments_as_written_without_separators():
    segments = [Segment(ja="第一句。"), Segment(ja="\n第二句。")]
    assert format_reply(segments, bilingual=False) == "第一句。\n第二句。"


def test_plain_text_voices_the_primary_text_with_cues_and_shows_none():
    shown, voiced, _, parser = parse(False, "[shyly] 谢、", "谢谢。")
    assert shown == [(0, "text", "谢、"), (0, "text", "谢谢。")]
    assert "".join(text for _, text in voiced).startswith("[shyly]")
    assert "".join(text for _, text in voiced).endswith("谢、谢谢。")
    assert parser.complete == [Segment(ja="[shyly] 谢、谢谢。", zh="")]




def test_bilingual_still_pairs_japanese_with_its_subtitle():
    shown, voiced, complete, parser = parse(
        True, "<ja>こんにちは", "！</ja><zh>你好！</zh><ja>元気？</ja><zh>还好吗？</zh>"
    )
    assert shown == [
        (0, "ja", "こんにちは"), (0, "ja", "！"), (0, "zh", "你好！"),
        (1, "ja", "元気？"), (1, "zh", "还好吗？"),
    ]
    assert "".join(text for segment, text in voiced if segment == 0) == "こんにちは！"
    assert "".join(text for segment, text in voiced if segment == 1) == "元気？"
    assert complete == [0, 1]
    assert parser.complete == [
        Segment(ja="こんにちは！", zh="你好！"), Segment(ja="元気？", zh="还好吗？"),
    ]


def test_bilingual_reply_that_ignores_the_format_is_kept_as_japanese():
    _, _, _, parser = parse(True, "えっと、", "ありがとうございます")
    assert parser.complete == [Segment(ja="えっと、ありがとうございます", zh="")]




def test_plain_format_instructions_ask_for_no_tags():
    for voiced_by in (None, "s1", "drama-3"):
        instructions = format_instructions(voiced_by, bilingual=False)
        assert "<ja>" not in instructions and "<zh>" not in instructions


def test_bilingual_format_instructions_keep_the_paired_tags():
    instructions = format_instructions(None, bilingual=True)
    assert "<ja>" in instructions and "<zh>" in instructions


def test_voiced_plain_instructions_offer_cues_and_unvoiced_do_not():
    assert "[shyly]" in format_instructions("s1", bilingual=False)
    assert "[shyly]" not in format_instructions(None, bilingual=False)