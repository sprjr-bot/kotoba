from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Sense:
    pos: tuple[str, ...]
    glosses: tuple[str, ...]


@dataclass(frozen=True)
class Entry:
    headword: str
    reading: str | None
    senses: tuple[Sense, ...]
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class LookupResult:
    query: str
    source: Literal["jisho", "wordnet"]
    entries: tuple[Entry, ...]
    url: str | None = None
