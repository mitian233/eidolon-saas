"""Readings (GLOSSARY.md「读音」): how names are said in the characters' voices. Every
request to Fish Audio carries those that have phonemes as its pronunciation dictionary;
what it is told to say, and what people see, keep the names as they are written."""

import re
from pathlib import Path

import pytest

from eidolon.readings import (
    Reading,
    ReadingsError,
    load_readings,
    pronunciation_dictionary,
    used_in,
)

MANO = Reading("櫻木真乃", "さくらぎ まの", "sa0ku1ra1gi0ma1no0")
MANO_GIVEN = Reading("真乃", "まの", "ma1no0")
TSUBASA = Reading("283", "つばさ", "")


def test_the_readings_are_read_in_file_order(tmp_path: Path):
    path = tmp_path / "readings.toml"
    path.write_text(
        '# 读音\n[[readings]]\nwritten = "櫻木真乃"\nkana = "さくらぎ まの"\nphonemes = "sa0ku1ra1gi0ma1no0"\n\n'
        '[[readings]]\nwritten = "283"\nkana = "つばさ"\nphonemes = ""\n',
        encoding="utf-8",
    )

    assert load_readings(path) == (MANO, TSUBASA)


def test_without_a_readings_file_there_are_none(tmp_path: Path):
    assert load_readings(tmp_path / "readings.toml") == ()


@pytest.mark.parametrize(
    "entries, complaint",
    [
        ('[[readings]]\nwritten = "真乃"\nkana = "まの"\n', "phonemes"),
        ('[[readings]]\nwritten = ""\nkana = "まの"\nphonemes = ""\n', "written"),
        (
            '[[readings]]\nwritten = "真乃"\nkana = "まの"\nphonemes = "ma1no0"\n'
            '[[readings]]\nwritten = "真乃"\nkana = "まの"\nphonemes = ""\n',
            "真乃",
        ),
        ('[[readings]]\nwritten = "真乃"\nkana = "まの"\nphonemes = "<|phoneme_start|>ma1no0"\n', "phoneme_start"),
        ("[[readings]\n", "格式"),
    ],
)
def test_a_broken_readings_file_is_an_error(tmp_path: Path, entries: str, complaint: str):
    path = tmp_path / "readings.toml"
    path.write_text(entries, encoding="utf-8")

    with pytest.raises(ReadingsError, match=re.escape(complaint)):
        load_readings(path)


def test_the_pronunciation_dictionary_has_every_reading_with_phonemes_case_sensitively():
    assert pronunciation_dictionary((MANO, TSUBASA, MANO_GIVEN)) == [
        {
            "items": [
                {"key": "櫻木真乃", "value": "sa0ku1ra1gi0ma1no0", "case_sensitive": True},
                {"key": "真乃", "value": "ma1no0", "case_sensitive": True},
            ]
        }
    ]
    assert pronunciation_dictionary((TSUBASA,)) is None


def test_what_a_line_uses_is_what_fish_audio_matches_earliest_and_longest_first():
    """Fish Audio matches keys as substrings; where they overlap, the one starting earliest
    wins, and of those the longest."""
    sakuragi = Reading("櫻木", "さくらぎ", "sa0ku1ra1gi0")
    tsubasa = Reading("283", "つばさ", "tsu0ba1sa0")
    pro = Reading("283プロ", "つばさ ぷろ", "tsu0ba1sa0pu1ro0")
    readings = (MANO, sakuragi, MANO_GIVEN, tsubasa, pro, Reading("透", "とおる", ""))

    assert used_in("はじめまして、櫻木真乃です", readings) == (MANO,)
    assert used_in("真乃です。283プロの、櫻木です", readings) == (MANO_GIVEN, pro, sakuragi)
    assert used_in("真乃、真乃", readings) == (MANO_GIVEN,)
    assert used_in("透明", readings) == ()  # it has no phonemes, so Fish Audio is not told it
    assert used_in("ほわっ", readings) == ()