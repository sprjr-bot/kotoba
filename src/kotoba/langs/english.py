from __future__ import annotations

import shutil
import subprocess

from kotoba.langs.base import Language
from kotoba.model import Entry, LookupResult, Sense


class LookupError(Exception):
    pass


def _entry(word: str, pos: str, glosses: list[str]) -> Entry:
    return Entry(
        headword=word,
        reading=None,
        senses=(Sense(pos=(pos,), glosses=tuple(glosses)),),
    )


def _parse(query: str, text: str) -> LookupResult:
    lines = text.splitlines()
    entries: list[Entry] = []
    current_pos: str | None = None
    glosses: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # License banner and header lines contain no colon-separated sense.
        if "WordNet" in stripped and "Copyright" in stripped:
            continue
        if stripped.startswith("This software"):
            continue
        if stripped.startswith(" license"):
            continue

        # New part-of-speech header, e.g. "Noun" or "Overview of noun love".
        if stripped[0].isupper() and not stripped.startswith(" ") and ":" not in stripped:
            if current_pos is not None and glosses:
                entries.append(_entry(query, current_pos, glosses))
                glosses = []
            current_pos = stripped.split()[0].lower()
            continue

        if ":" in stripped:
            if current_pos is None:
                # Default to the first word before any colon as a fallback.
                current_pos = "unknown"
            number, _, gloss = stripped.partition(":")
            gloss = gloss.strip()
            if gloss:
                glosses.append(gloss)

    if current_pos is not None and glosses:
        entries.append(_entry(query, current_pos, glosses))

    return LookupResult(query=query, source="wordnet", entries=tuple(entries))


def _fetch_core(
    query: str,
    limit: int | None,
    which_fn,
) -> LookupResult:
    """Run the ``wn`` CLI and parse the output.

    *which_fn* is the callable used to locate the ``wn`` binary.  It is exposed
    so that the legacy ``kotoba.wordnet`` shim can use its own ``shutil.which``
    and remain patchable by existing tests.
    """
    if not which_fn("wn"):
        raise LookupError("wordnet not installed")

    try:
        proc = subprocess.run(
            ["wn", query, "-over"],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception as exc:
        raise LookupError(f"failed to run wn: {exc}") from exc

    combined = proc.stdout + proc.stderr
    if not combined.strip():
        return LookupResult(query=query, source="wordnet", entries=())

    result = _parse(query, combined)
    if limit:
        return LookupResult(query=query, source="wordnet", entries=result.entries[:limit], url=result.url)
    return result


def fetch(query: str, *, limit: int | None = None) -> LookupResult:
    """Live WordNet lookup. Kept as a module-level helper for backwards compatibility."""
    return _fetch_core(query, limit, shutil.which)


class English(Language):
    code = "wordnet"
    name = "English"
    aliases = ("en", "wordnet")
    api_module = "kotoba.wordnet"

    def datasets(self) -> list[str]:
        return []

    def search(self, query: str, *, limit: int | None = None, offline: bool = False) -> LookupResult:
        if offline:
            return LookupResult(query=query, source=self.code, entries=())
        return fetch(query, limit=limit)

    def api_search(self, query: str, *, limit: int | None = None) -> LookupResult:
        return fetch(query, limit=limit)

    def autodetect(self, text: str) -> bool:
        # Simple heuristic: plain ASCII letters without CJK characters.
        return text.isascii() and any(ch.isalpha() for ch in text)
