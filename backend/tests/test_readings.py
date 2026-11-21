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

MANO = Reading("櫻庭紗季", "さくらば さき", "sa0ku1ra1ba0sa1ki0")
MANO_GIVEN = Reading("紗季", "さき", "sa1ki0")
TSUBASA = Reading("283", "つばさ", "")


def test_the_readings_are_read_in_file_order(tmp_path: Path):
    path = tmp_path / "readings.toml"
    path.write_text(
        '# 读音\n[[readings]]\nwritten = "櫻庭紗季"\nkana = "さくらば さき"\nphonemes = "sa0ku1ra1ba0sa1ki0"\n\n'
        '[[readings]]\nwritten = "283"\nkana = "つばさ"\nphonemes = ""\n',
        encoding="utf-8",
    )

    assert load_readings(path) == (MANO, TSUBASA)


def test_without_a_readings_file_there_are_none(tmp_path: Path):
    assert load_readings(tmp_path / "readings.toml") == ()


@pytest.mark.parametrize(
    "entries, complaint",
    [
        ('[[readings]]\nwritten = "紗季"\nkana = "さき"\n', "phonemes"),
        ('[[readings]]\nwritten = ""\nkana = "さき"\nphonemes = ""\n', "written"),
        (
            '[[readings]]\nwritten = "紗季"\nkana = "さき"\nphonemes = "sa1ki0"\n'
            '[[readings]]\nwritten = "紗季"\nkana = "さき"\nphonemes = ""\n',
            "紗季",
        ),
        ('[[readings]]\nwritten = "紗季"\nkana = "さき"\nphonemes = "<|phoneme_start|>sa1ki0"\n', "phoneme_start"),
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
                {"key": "櫻庭紗季", "value": "sa0ku1ra1ba0sa1ki0", "case_sensitive": True},
                {"key": "紗季", "value": "sa1ki0", "case_sensitive": True},
            ]
        }
    ]
    assert pronunciation_dictionary((TSUBASA,)) is None


def test_what_a_line_uses_is_what_fish_audio_matches_earliest_and_longest_first():
    """Fish Audio matches keys as substrings; where they overlap, the one starting earliest
    wins, and of those the longest."""
    sakuragi = Reading("櫻庭", "さくらば", "sa0ku1ra1ba0")
    music = Reading("音楽", "おんがく", "o0N1ga1ku0")
    music_room = Reading("音楽室", "おんがくしつ", "o0N1ga1ku0shi1tsu0")
    readings = (MANO, sakuragi, MANO_GIVEN, music, music_room, Reading("透", "とおる", ""))

    assert used_in("はじめまして、櫻庭紗季です", readings) == (MANO,)
    assert used_in("紗季です。音楽室の、櫻庭です", readings) == (MANO_GIVEN, music_room, sakuragi)
    assert used_in("紗季、紗季", readings) == (MANO_GIVEN,)
    assert used_in("透明", readings) == ()  # it has no phonemes, so Fish Audio is not told it
    assert used_in("ほわっ", readings) == ()