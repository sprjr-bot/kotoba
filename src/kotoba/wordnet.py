from __future__ import annotations

import shutil
import subprocess

from kotoba.model import Entry, LookupResult, Sense


class LookupError(Exception):
    pass


def fetch(query: str, *, limit: int | None = None) -> LookupResult:
    if not shutil.which("wn"):
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


def _entry(word: str, pos: str, glosses: list[str]) -> Entry:
    return Entry(
        headword=word,
        reading=None,
        senses=(Sense(pos=(pos,), glosses=tuple(glosses)),),
    )
