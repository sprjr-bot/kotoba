from __future__ import annotations

import gzip
import json
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kotoba.datasets import DatasetDescriptor

MAX_SENSES = 8


def _glosses_for_lang(sense: dict, lang_code: str = "en") -> list[str]:
    raw = sense.get("glosses") or []
    result = []
    for item in raw:
        if isinstance(item, str):
            result.append(item)
        elif isinstance(item, dict):
            if item.get("lang", lang_code) == lang_code:
                result.append(item.get("text", ""))
    return [g for g in result if g]


def _english_glosses(senses: list[dict]) -> list[str]:
    for sense in senses:
        glosses = _glosses_for_lang(sense)
        if glosses:
            return glosses
    return []


def _has_english_gloss(senses: list[dict]) -> bool:
    return any(bool(_glosses_for_lang(sense)) for sense in senses)


def _forms(entry: dict) -> list[dict]:
    forms = []
    for form in entry.get("forms") or []:
        tag = form.get("tags") or []
        if isinstance(tag, str):
            tag = [tag]
        forms.append({"form": form.get("form", ""), "tags": tag})
    return forms


def _sounds(entry: dict) -> list[dict]:
    sounds = []
    for sound in entry.get("sounds") or []:
        ipa = sound.get("ipa")
        if ipa:
            sounds.append({"type": "ipa", "value": ipa})
        for key, label in (("rhymes", "rhyme"), ("homophones", "homophone")):
            vals = sound.get(key) or []
            if isinstance(vals, str):
                vals = [vals]
            for v in vals:
                sounds.append({"type": label, "value": v})
    return sounds


def ingest_kaikki(
    source: Path,
    dataset_dir: Path,
    descriptor: "DatasetDescriptor | None" = None,
    *,
    full_index: bool = False,
) -> None:
    """Stream a Kaikki JSONL gzip into a per-language SQLite index.

    *source* is the path to the raw-wiktextract-data.jsonl.gz archive.
    *descriptor* carries the target lang_code and trim policy.
    """
    target_lang = getattr(descriptor, "language", "") or ""
    trim = not full_index
    max_senses = MAX_SENSES if trim else 0

    db_path = dataset_dir / "index.sqlite3"
    if db_path.exists():
        db_path.unlink()
    dataset_dir.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db_path))
    try:
        con.execute("PRAGMA journal_mode=OFF")
        con.execute("PRAGMA synchronous=NORMAL")
        con.execute(
            "CREATE TABLE entries ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, headword TEXT, lemma TEXT, pos TEXT, "
            "glosses TEXT, forms TEXT, sounds TEXT, tags TEXT, sense_count INTEGER, source TEXT)"
        )
        con.execute("CREATE INDEX idx_entries_headword ON entries(headword)")
        con.execute("CREATE INDEX idx_entries_lemma ON entries(lemma)")
        con.execute("CREATE INDEX idx_entries_pos ON entries(pos)")
        con.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")

        entries = 0
        skipped = 0
        total_senses = 0
        lang_marker = f'"lang_code": "{target_lang}"'.encode()

        with gzip.open(source, "rb") as fh:
            for raw in fh:
                if lang_marker not in raw:
                    skipped += 1
                    continue
                try:
                    obj = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    skipped += 1
                    continue
                if obj.get("lang_code") != target_lang:
                    skipped += 1
                    continue

                if trim and not _has_english_gloss(obj.get("senses") or []):
                    skipped += 1
                    continue

                headword = obj.get("word", "")
                lemma = obj.get("lemma", headword)
                pos = obj.get("pos", "")
                senses = obj.get("senses") or []
                if max_senses:
                    senses = senses[:max_senses]
                glosses = []
                sense_count = 0
                for sense in senses:
                    g = _glosses_for_lang(sense)
                    if g:
                        glosses.extend(g)
                        sense_count += 1
                tags = obj.get("tags") or []
                if isinstance(tags, str):
                    tags = [tags]

                con.execute(
                    "INSERT INTO entries (headword, lemma, pos, glosses, forms, sounds, tags, sense_count, source) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        headword,
                        lemma,
                        pos,
                        json.dumps(glosses, ensure_ascii=False),
                        json.dumps(_forms(obj), ensure_ascii=False),
                        json.dumps(_sounds(obj), ensure_ascii=False),
                        json.dumps(tags, ensure_ascii=False),
                        sense_count,
                        "kaikki",
                    ),
                )
                entries += 1
                total_senses += sense_count

                if entries % 500 == 0:
                    con.commit()

        con.execute("INSERT INTO meta VALUES (?, ?)", ("source", "kaikki"))
        con.execute("INSERT INTO meta VALUES (?, ?)", ("lang", target_lang))
        con.commit()
        print(
            f"indexed kaikki/{target_lang}: {entries} entries, {skipped} skipped, {total_senses} senses"
        )
    finally:
        con.close()
