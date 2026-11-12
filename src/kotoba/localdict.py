"""Japanese local-dictionary indices and index-backed lookups.

Dataset tables, release resolution, downloads and hash policy live in
:mod:`kotoba.datasets`; this module keeps the SQLite index builders, the
lookup helpers, and thin backwards-compatible wrappers over the dataset
pipeline.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Callable

from kotoba import datasets
from kotoba.datasets import DictError
from kotoba.model import Entry, LookupResult, Sense

# Backwards-compatible aliases: paths and sizes are owned by the dataset layer.
_data_dir = datasets.data_dir
_dataset_dir = datasets.dataset_dir
_index_size = datasets.index_size
_load_meta = datasets.read_meta

FetchProgress = datasets.FetchProgress

__all__ = [
    "DictError",
    "build_jmdict_index",
    "build_kanjidic2_index",
    "build_kradfile_index",
    "build_radkfile_index",
    "installed",
    "install",
    "remove",
    "reindex",
    "update",
    "status",
    "lookup",
    "kanji",
]


def _db_path(dataset_dir: Path) -> Path:
    return datasets.db_path(dataset_dir)


def _connect_index(dataset_dir: Path) -> sqlite3.Connection:
    con = sqlite3.connect(str(_db_path(dataset_dir)))
    con.execute("PRAGMA journal_mode=OFF")
    con.execute("PRAGMA synchronous=NORMAL")
    return con


# --------------------------------------------------------------------------- #
# index builders


def _parse_gloss(g: dict) -> str:
    return g.get("text", "")


def build_jmdict_index(json_path: Path, dataset_dir: Path) -> None:
    """Build the JMdict SQLite index from a ``words[]`` JSON file."""
    db = _db_path(dataset_dir)
    if db.exists():
        db.unlink()
    con = _connect_index(dataset_dir)
    try:
        con.execute("CREATE TABLE entries (id INTEGER PRIMARY KEY, headword TEXT, reading TEXT, common INTEGER)")
        con.execute("CREATE TABLE forms (text TEXT, entry_id INTEGER, kind TEXT)")
        con.execute("CREATE INDEX idx_forms_text ON forms(text)")
        con.execute("CREATE INDEX idx_forms_entry ON forms(entry_id)")
        con.execute("CREATE TABLE senses (entry_id INTEGER, ord INTEGER, pos TEXT, glosses TEXT)")
        con.execute("CREATE INDEX idx_senses_entry ON senses(entry_id)")
        con.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")

        with open(json_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        words = data.get("words", [])
        for i, word in enumerate(words):
            entry_id = int(word.get("id", i))
            kanji_forms = word.get("kanji", [])
            kana_forms = word.get("kana", [])
            common = any(k.get("common") for k in kanji_forms) or any(k.get("common") for k in kana_forms)

            head_kanji = next((k["text"] for k in kanji_forms if k.get("text")), None)
            head_reading = None
            if head_kanji:
                # pick first kana that applies to this kanji or wildcard
                for k in kana_forms:
                    applies = k.get("appliesToKanji", [])
                    if "*" in applies or head_kanji in applies:
                        head_reading = k["text"]
                        break
                if head_reading is None and kana_forms:
                    head_reading = kana_forms[0]["text"]
            else:
                if kana_forms:
                    head_kanji = kana_forms[0]["text"]

            con.execute(
                "INSERT INTO entries VALUES (?, ?, ?, ?)",
                (entry_id, head_kanji or "", head_reading or "", int(common)),
            )
            for k in kanji_forms:
                text = k.get("text")
                if text:
                    con.execute("INSERT INTO forms VALUES (?, ?, ?)", (text, entry_id, "kanji"))
            for k in kana_forms:
                text = k.get("text")
                if text:
                    con.execute("INSERT INTO forms VALUES (?, ?, ?)", (text, entry_id, "kana"))
            for ord_, sense in enumerate(word.get("sense", [])):
                pos = json.dumps(sense.get("partOfSpeech", []))
                glosses = json.dumps([_parse_gloss(g) for g in sense.get("gloss", []) if _parse_gloss(g)])
                con.execute("INSERT INTO senses VALUES (?, ?, ?, ?)", (entry_id, ord_, pos, glosses))
            if i % 500 == 0:
                con.commit()
        con.execute("INSERT INTO meta VALUES (?, ?)", ("source", "jmdict"))
        con.commit()
    finally:
        con.close()


def build_kanjidic2_index(json_path: Path, dataset_dir: Path) -> None:
    """Build the KANJIDIC2 SQLite index from a ``characters[]`` JSON file."""
    db = _db_path(dataset_dir)
    if db.exists():
        db.unlink()
    con = _connect_index(dataset_dir)
    try:
        con.execute(
            "CREATE TABLE kanji (literal TEXT PRIMARY KEY, stroke_count INTEGER, grade INTEGER, "
            "frequency INTEGER, jlpt INTEGER, on_readings TEXT, kun_readings TEXT, meanings TEXT, radicals TEXT)"
        )
        with open(json_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        for char in data.get("characters", []):
            literal = char.get("literal", "")
            misc = char.get("misc", {})
            strokes = misc.get("strokeCounts", [0])[0]
            grade = misc.get("grade")
            freq = misc.get("frequency")
            jlpt = misc.get("jlptLevel")
            on_readings: list[str] = []
            kun_readings: list[str] = []
            meanings: list[str] = []
            rm = char.get("readingMeaning", {})
            groups = rm.get("rmgroup", []) if isinstance(rm, dict) else []
            for group in groups:
                for r in group.get("reading", []):
                    t = r.get("type", "")
                    v = r.get("value", "")
                    if t == "ja_on":
                        on_readings.append(v)
                    elif t == "ja_kun":
                        kun_readings.append(v)
                for m in group.get("meaning", []):
                    if isinstance(m, dict):
                        if m.get("lang", "en") == "en":
                            meanings.append(m.get("value", ""))
                    elif isinstance(m, str):
                        meanings.append(m)
            radicals = [str(r.get("value")) for r in char.get("radicals", []) if r.get("value") is not None]
            con.execute(
                "INSERT INTO kanji VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    literal,
                    strokes,
                    grade,
                    freq,
                    jlpt,
                    json.dumps(on_readings),
                    json.dumps(kun_readings),
                    json.dumps(meanings),
                    json.dumps(radicals),
                ),
            )
        con.commit()
    finally:
        con.close()


def build_kradfile_index(json_path: Path, dataset_dir: Path) -> None:
    """Build the Kradfile component index."""
    db = _db_path(dataset_dir)
    if db.exists():
        db.unlink()
    con = _connect_index(dataset_dir)
    try:
        con.execute("CREATE TABLE components (kanji TEXT PRIMARY KEY, parts TEXT)")
        with open(json_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        for literal, parts in data.get("kanji", {}).items():
            con.execute("INSERT INTO components VALUES (?, ?)", (literal, json.dumps(parts)))
        con.commit()
    finally:
        con.close()


def build_radkfile_index(json_path: Path, dataset_dir: Path) -> None:
    """Build the Radkfile radical index."""
    db = _db_path(dataset_dir)
    if db.exists():
        db.unlink()
    con = _connect_index(dataset_dir)
    try:
        con.execute("CREATE TABLE radical_kanji (radical TEXT, kanji TEXT, strokes INTEGER)")
        con.execute("CREATE INDEX idx_radical ON radical_kanji(radical)")
        con.execute("CREATE INDEX idx_kanji ON radical_kanji(kanji)")
        with open(json_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        for radical, info in data.get("radicals", {}).items():
            strokes = info.get("strokeCount", 0)
            for k in info.get("kanji", []):
                con.execute("INSERT INTO radical_kanji VALUES (?, ?, ?)", (radical, k, strokes))
        con.commit()
    finally:
        con.close()


# --------------------------------------------------------------------------- #
# dataset operations (thin wrappers over kotoba.datasets)


def installed() -> dict:
    return datasets.installed()


def install(
    dataset: str,
    *,
    latest: bool = False,
    accept_new_dump: bool = False,
    purge_cache: bool = False,
    refresh: bool = False,
    fetcher: Callable[[str], dict] | None = None,
    progress: FetchProgress | None = None,
) -> dict:
    return datasets.install(
        dataset,
        latest=latest,
        accept_new_dump=accept_new_dump,
        purge_cache=purge_cache,
        refresh=refresh,
        fetcher=fetcher,
        progress=progress,
    )


def remove(dataset: str) -> bool:
    return datasets.remove(dataset)


def reindex(dataset: str) -> dict:
    return datasets.reindex(dataset)


def reindex_all() -> list[dict]:
    return datasets.reindex_all()


def update(fetcher: Callable[[str], dict] | None = None, progress: FetchProgress | None = None) -> list[dict]:
    return datasets.update(fetcher=fetcher, progress=progress)


def status() -> list[dict]:
    return datasets.status()


# --------------------------------------------------------------------------- #
# index-backed lookups


def _installed_with_index(dataset: str) -> tuple[Path, dict] | None:
    dataset_dir = _dataset_dir(dataset)
    meta = datasets.installed_meta(dataset)
    if meta and _db_path(dataset_dir).exists():
        return dataset_dir, meta
    return None


def _jmdict_installed() -> tuple[Path, dict] | None:
    for key in ("jmdict-eng", "jmdict-eng-common"):
        found = _installed_with_index(key)
        if found is not None:
            return found
    return None


def _kanjidic_installed() -> tuple[Path, dict] | None:
    return _installed_with_index("kanjidic2-en")


def _krad_installed() -> tuple[Path, dict] | None:
    return _installed_with_index("kradfile")


def _radk_installed() -> tuple[Path, dict] | None:
    return _installed_with_index("radkfile")


def _jmdict_entry(con: sqlite3.Connection, entry_id: int) -> Entry | None:
    row = con.execute("SELECT headword, reading, common FROM entries WHERE id = ?", (entry_id,)).fetchone()
    if row is None:
        return None
    headword, reading, common = row
    tags: list[str] = []
    if common:
        tags.append("common")
    sense_rows = con.execute(
        "SELECT pos, glosses FROM senses WHERE entry_id = ? ORDER BY ord", (entry_id,)
    ).fetchall()
    senses = []
    for pos_json, glosses_json in sense_rows:
        pos = tuple(json.loads(pos_json))
        glosses = tuple(json.loads(glosses_json))
        if glosses:
            senses.append(Sense(pos=pos, glosses=glosses))
    return Entry(
        headword=headword,
        reading=reading or None,
        senses=tuple(senses),
        tags=tuple(tags),
        url="",
        source="jmdict",
    )


def lookup(query: str, limit: int = 12) -> LookupResult:
    installed_info = _jmdict_installed()
    if installed_info is None:
        return LookupResult(query=query, source="jmdict", entries=())
    dataset_dir, meta = installed_info
    con = _connect_index(dataset_dir)
    try:
        found: list[int] = []
        # tier 1: exact, kanji before kana
        rows = con.execute(
            "SELECT DISTINCT entry_id FROM forms WHERE text = ? AND kind = 'kanji' ORDER BY entry_id",
            (query,),
        ).fetchall()
        found.extend(r[0] for r in rows)
        rows = con.execute(
            "SELECT DISTINCT entry_id FROM forms WHERE text = ? AND kind = 'kana' ORDER BY entry_id",
            (query,),
        ).fetchall()
        found.extend(r[0] for r in rows if r[0] not in found)
        # tier 2: prefix
        if len(found) < limit:
            rows = con.execute(
                "SELECT DISTINCT entry_id FROM forms WHERE text LIKE ? || '%' ORDER BY entry_id",
                (query,),
            ).fetchall()
            for r in rows:
                if r[0] not in found:
                    found.append(r[0])
        # tier 3: substring
        if len(found) < limit:
            rows = con.execute(
                "SELECT DISTINCT entry_id FROM forms WHERE text LIKE '%' || ? || '%' ORDER BY entry_id",
                (query,),
            ).fetchall()
            for r in rows:
                if r[0] not in found:
                    found.append(r[0])

        if not found:
            return LookupResult(query=query, source="jmdict", entries=())

        placeholders = ",".join("?" * len(found))
        rank_rows = con.execute(
            f"SELECT id, headword FROM entries WHERE id IN ({placeholders}) ORDER BY common DESC, LENGTH(headword) ASC, id ASC",
            tuple(found),
        ).fetchall()
        ids = [r[0] for r in rank_rows[:limit]]
        entries = []
        for entry_id in ids:
            entry = _jmdict_entry(con, entry_id)
            if entry:
                entries.append(entry)
        url = meta.get("source_url", "")
        return LookupResult(query=query, source="jmdict", entries=tuple(entries), url=url)
    finally:
        con.close()


def kanji(literal: str) -> dict | None:
    kanji_info = _kanjidic_installed()
    if kanji_info is None:
        return None
    dataset_dir, _ = kanji_info
    con = _connect_index(dataset_dir)
    try:
        row = con.execute(
            "SELECT stroke_count, grade, frequency, jlpt, on_readings, kun_readings, meanings, radicals "
            "FROM kanji WHERE literal = ?",
            (literal,),
        ).fetchone()
        if row is None:
            return None
        stroke_count, grade, frequency, jlpt, on_json, kun_json, meanings_json, radicals_json = row
        components = []
        krad_info = _krad_installed()
        if krad_info:
            kcon = _connect_index(krad_info[0])
            try:
                c = kcon.execute("SELECT parts FROM components WHERE kanji = ?", (literal,)).fetchone()
                if c:
                    components = json.loads(c[0])
            finally:
                kcon.close()
        return {
            "literal": literal,
            "stroke_count": stroke_count,
            "grade": grade,
            "frequency": frequency,
            "jlpt": jlpt,
            "on_readings": json.loads(on_json),
            "kun_readings": json.loads(kun_json),
            "meanings": json.loads(meanings_json),
            "radicals": json.loads(radicals_json),
            "components": components,
        }
    finally:
        con.close()
