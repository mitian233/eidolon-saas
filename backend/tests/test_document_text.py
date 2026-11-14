import pytest

from eidolon.document_text import normalize_text, passages, text_hash


def test_empty_text_has_no_passages() -> None:
    assert passages(" \r\n\t\n ") == []


def test_lines_are_normalized_and_grouped_within_limit() -> None:
    assert passages("  first  \r\n second\r\nthird ", max_chars=12) == [
        "first\nsecond",
        "third",
    ]
    assert normalize_text(" first \r\n second ") == "first\nsecond"


def test_long_single_line_is_split_without_overlap() -> None:
    text = "a" * 1200 + "b" * 1200 + "c"
    assert passages(text) == ["a" * 1200, "b" * 1200, "c"]


def test_duplicate_passages_are_removed_after_normalization() -> None:
    assert passages("  same \r\nother\r\nsame", max_chars=5) == ["same", "other"]
    assert text_hash(" same \r\n text ") == text_hash("same\ntext")
    assert text_hash("same") != text_hash("different")


def test_repeated_import_has_stable_passages_and_hashes() -> None:
    text = "one\ntwo\n" + "z" * 13 + "\nthree"
    first = passages(text, max_chars=7)
    second = passages(text, max_chars=7)
    assert first == second
    assert [text_hash(part) for part in first] == [text_hash(part) for part in second]
    assert all(len(part) <= 7 for part in first)


def test_invalid_limit_is_rejected() -> None:
    with pytest.raises(ValueError, match="positive"):
        passages("text", max_chars=0)
