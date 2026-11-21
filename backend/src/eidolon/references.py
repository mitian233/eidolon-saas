"""Search results for the character and work facts."""

from dataclasses import dataclass
from typing import Literal

ReferenceKind = Literal["fact", "work"]


@dataclass(frozen=True)
class Reference:
    kind: ReferenceKind
    text: str
    origin: str
    """The fact's title, or its text if it has no title."""
    similarity: float
    """Its vector's cosine similarity to the query's: as every source embeds with the same
    embedder, comparable across sources."""
