from __future__ import annotations

from dataclasses import dataclass


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
    url: str = ""
    source: str = ""


@dataclass(frozen=True)
class LookupResult:
    query: str
    source: str
    entries: tuple[Entry, ...]
    url: str | None = None
