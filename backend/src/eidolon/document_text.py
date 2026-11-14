"""Pure text preparation for documents in a character's knowledge base."""

import hashlib


# Passages have at most 1200 characters and do not overlap.
PASSAGE_CHARS = 1200


def normalize_text(text: str) -> str:
    """Normalize line endings and whitespace at the edges of each line."""
    return "\n".join(line.strip() for line in text.splitlines()).strip()


def text_hash(text: str) -> str:
    """A stable identity for text after the same normalization used by chunking."""
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


def passages(text: str, *, max_chars: int = PASSAGE_CHARS) -> list[str]:
    """Group lines into unique passages, splitting lines that exceed the limit."""
    if max_chars < 1:
        raise ValueError("max_chars must be positive")
    text = normalize_text(text)
    if not text:
        return []

    result: list[str] = []
    seen: set[str] = set()
    current = ""

    def add(value: str) -> None:
        value = normalize_text(value)
        if value:
            digest = text_hash(value)
            if digest not in seen:
                seen.add(digest)
                result.append(value)

    for line in text.split("\n"):
        if current and len(current) + 1 + len(line) <= max_chars:
            current += "\n" + line
            continue
        if current:
            add(current)
            current = ""
        while len(line) > max_chars:
            add(line[:max_chars])
            line = line[max_chars:]
        current = line
    add(current)
    return result
