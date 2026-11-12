from __future__ import annotations

from urllib.parse import quote

import httpx

from kotoba import datasets, localdict
from kotoba.langs.base import Language
from kotoba.model import Entry, LookupResult, Sense


class LookupError(Exception):
    pass


def _map_entry(item: dict) -> Entry:
    japanese = item.get("japanese", [{}])
    head = japanese[0] if japanese else {}

    tags: list[str] = []
    if item.get("is_common"):
        tags.append("common")
    tags.extend(item.get("jlpt", []))
    tags.extend(item.get("tags", []))

    senses = []
    for sense in item.get("senses", []):
        glosses = tuple(sense.get("english_definitions", []))
        pos = tuple(sense.get("parts_of_speech", []))
        if glosses:
            senses.append(Sense(pos=pos, glosses=glosses))

    return Entry(
        headword=head.get("word") or head.get("reading") or item.get("slug", ""),
        reading=head.get("reading"),
        senses=tuple(senses),
        tags=tuple(tags),
    )


def fetch(query: str, *, timeout: float = 8.0, limit: int = 12) -> LookupResult:
    url = f"https://jisho.org/api/v1/search/words?keyword={quote(query, safe='')}"
    try:
        response = httpx.get(url, timeout=timeout)
    except httpx.RequestError as exc:
        raise LookupError(f"network error: {exc}") from exc

    if response.status_code != 200:
        raise LookupError(f"jisho returned {response.status_code}")

    try:
        payload = response.json()
    except Exception as exc:
        raise LookupError(f"invalid response: {exc}") from exc

    data = payload.get("data", [])
    entries = [_map_entry(item) for item in data[:limit]]

    return LookupResult(
        query=query,
        source="jisho",
        entries=tuple(entries),
        url=f"https://jisho.org/search/{quote(query, safe='')}",
    )


def kanji(literal: str) -> dict | None:
    """Return KANJIDIC2 data for a single kanji literal."""
    return localdict.kanji(literal)


class Japanese(Language):
    code = "jisho"
    name = "Japanese"
    aliases = ("jp", "jisho", "jmdict")
    language_code = "ja"

    def datasets(self) -> list[str]:
        return datasets.enabled_ids(self.language_code)

    def search(self, query: str, *, limit: int | None = None, offline: bool = False) -> LookupResult:
        if offline:
            if localdict.installed():
                return localdict.lookup(query, limit=limit or 12)
            return LookupResult(query=query, source=self.code, entries=())
        return fetch(query, limit=limit or 12)

    def api_search(self, query: str, *, limit: int | None = None) -> LookupResult:
        return fetch(query, limit=limit or 12)

    def render_extras(self, entry: Entry) -> dict:
        return {"reading": entry.reading, "tags": entry.tags}

    def special(self, name: str, query: str) -> dict | None:
        if name == "kanji":
            data = kanji(query)
            return {"kanji": data} if data is not None else None
        return None

    def autodetect(self, text: str) -> bool:
        return any(
            (0x3040 <= ord(ch) <= 0x309F)  # Hiragana
            or (0x30A0 <= ord(ch) <= 0x30FF)  # Katakana
            or (0x4E00 <= ord(ch) <= 0x9FFF)  # CJK Unified Ideographs
            or (0x3400 <= ord(ch) <= 0x4DBF)  # CJK Extension A
            for ch in text
        )
