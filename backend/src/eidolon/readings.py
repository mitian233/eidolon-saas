"""Readings (GLOSSARY.md「读音」): how names are said in the characters' voices, e.g. 天井努
as あまい つとむ, 283プロ as つばさプロ.

They are in a readings file the deployer keeps (`readings.toml`): each entry is a name
as it is written, its reading in kana for people to read and change, and the phonemes
Fish Audio is told (OpenJTalk's romaji with pitch digits, as `ha0shi1ga0`). The bundled
file and its drafting command are gone with the 283 content; the mechanism stays for
names a deployment wants said right. The server reads it as it starts; the admin
console cannot change it.

Every request to Fish Audio, read-alouds' (`read_aloud`) and the calls' (`call.FishTTS`),
on the deployer's key or a user's own, carries every entry with phonemes as its
pronunciation dictionary (`pronunciation_dictionary`). Fish Audio matches the keys in
what it is told to say as written, so what it says, and what people see, keep the names
as they are written. It skips a dictionary it cannot use without saying so: whether a
name is said right is for people to hear.
"""

import tomllib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

READINGS_FILE = "readings.toml"
"""The file's name, in the directory of the character configuration."""

_PHONEME_TAGS = ("<|phoneme_start|>", "<|phoneme_end|>")
"""Fish Audio's inline phoneme tags, which a dictionary's values must not have."""


class ReadingsError(RuntimeError):
    """The readings file cannot be read."""


@dataclass(frozen=True)
class Reading:
    written: str
    """The name as it is written: Fish Audio's key, matched as a substring, case and all."""
    kana: str
    """How it is read, in kana, surname and given name apart (`さくらぎ まの`)."""
    phonemes: str
    """What Fish Audio is told it is read as; empty until drafted, and then not sent."""


def readings_path(characters_path: Path) -> Path:
    """Where the readings file is: beside the character configuration."""
    return characters_path.parent / READINGS_FILE


def load_readings(path: Path) -> tuple[Reading, ...]:
    """The readings in the file at `path`, in file order; none if there is no file. Raises
    ReadingsError if it is broken."""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return ()
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as e:
        raise ReadingsError(f"读音文件 {path} 格式有误：{e}") from None
    entries = data.get("readings", [])
    if not isinstance(entries, list):
        raise ReadingsError(f"读音文件 {path} 的条目应写成 [[readings]]")
    readings: dict[str, Reading] = {}
    for number, entry in enumerate(entries, 1):
        reading = _parse(entry, f"读音文件 {path} 的第 {number} 条")
        if reading.written in readings:
            raise ReadingsError(f"读音文件 {path} 里「{reading.written}」出现了不止一次")
        readings[reading.written] = reading
    return tuple(readings.values())


def _parse(entry: object, label: str) -> Reading:
    if not isinstance(entry, dict):
        raise ReadingsError(f"{label}应写成 [[readings]]")
    fields = {}
    for name in ("written", "kana", "phonemes"):
        value = entry.get(name)
        if not isinstance(value, str):
            raise ReadingsError(f"{label}缺少 {name}（字符串，音素还没生成时写空字符串）")
        fields[name] = value.strip()
    if not fields["written"]:
        raise ReadingsError(f"{label}的 written 是空的")
    if any(tag in fields["phonemes"] for tag in _PHONEME_TAGS):
        raise ReadingsError(f"{label}的 phonemes 不能带 {' 或 '.join(_PHONEME_TAGS)}，只写音素串")
    return Reading(**fields)


def pronunciation_dictionary(readings: Iterable[Reading]) -> list[dict] | None:
    """`readings` as a Fish Audio request's `pronunciation_dictionary`, those with phonemes;
    None if none have."""
    items = [
        {"key": r.written, "value": r.phonemes, "case_sensitive": True}
        for r in readings
        if r.phonemes
    ]
    return [{"items": items}] if items else None


def used_in(text: str, readings: Sequence[Reading]) -> tuple[Reading, ...]:
    """The readings Fish Audio uses saying `text`, in the order it first comes to each: of
    the keys found in it, where they overlap, the one starting earliest, and of those the
    longest. Those without phonemes it is not told."""
    by_written = {r.written: r for r in readings if r.phonemes}
    lengths = sorted({len(w) for w in by_written}, reverse=True)
    used: dict[str, Reading] = {}
    start = 0
    while start < len(text):
        for length in lengths:
            if (reading := by_written.get(text[start:start + length])) is not None:
                used.setdefault(reading.written, reading)
                start += length
                break
        else:
            start += 1
    return tuple(used.values())
