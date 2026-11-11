from __future__ import annotations

from urllib.parse import quote

import httpx

from kotoba.model import Entry, LookupResult, Sense


class LookupError(Exception):
    pass


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
