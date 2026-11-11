from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import stat
import tarfile
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.request import Request, urlopen

from kotoba.model import Entry, LookupResult, Sense

_DATASET_NAMES = {"jmdict-eng", "jmdict-eng-common", "kanjidic2-en", "kradfile", "radkfile"}

_LICENSES = {
    "jmdict-eng": ("EDRDG JMdict", "https://www.edrdg.org/jmdict/j_jmdict.html", "CC BY-SA 4.0"),
    "jmdict-eng-common": ("EDRDG JMdict", "https://www.edrdg.org/jmdict/j_jmdict.html", "CC BY-SA 4.0"),
    "kanjidic2-en": ("EDRDG KANJIDIC2", "https://www.edrdg.org/wiki/index.php/KANJIDIC2", "CC BY-SA 4.0"),
    "kradfile": ("EDRDG Kradfile", "https://www.edrdg.org/krad/kradinf.html", "CC BY-SA 4.0"),
    "radkfile": ("EDRDG Radkfile", "https://www.edrdg.org/krad/kradinf.html", "CC BY-SA 4.0"),
}

_MUTUAL_EXCLUSIVE = [{"jmdict-eng", "jmdict-eng-common"}]

_PINNED = {
    "jmdict-eng": "acf4beb64e7a0bb8f44b3aae9bf2b81cb0ecde462fb3679264ef66e92f25c04a",
    "jmdict-eng-common": "85bbc8a41ecfd28f30ac18defa8e98245344a0ab1bf17a76888299279f286f9b",
    "kanjidic2-en": "3a2e9c19abb75f416bdcb2b03818334651419ffdcc7028d1e3e86e697cad0019",
    "kradfile": "0eff6e161fff2ec47431b9fe09158012be638960cede2b67858ec070afa4b743",
    "radkfile": "52303d123f59251f01ffb5e66c6efffcb7814dd5260c0560a1fdb4bb3b7938d6",
}

_DEFAULT_FETCH_TIMEOUT = 120.0

FetchProgress = Callable[[str, str, float | None], None]  # dataset, state, fraction or None


class DictError(Exception):
    pass


def _data_dir() -> Path:
    base = os.environ.get("XDG_DATA_HOME")
    if base:
        return Path(base) / "kotoba" / "dict"
    return Path.home() / ".local" / "share" / "kotoba" / "dict"


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)


def installed() -> dict:
    root = _data_dir()
    result: dict = {}
    if not root.exists():
        return result
    for dataset in _DATASET_NAMES:
        meta_path = root / dataset / "meta.json"
        if meta_path.exists():
            try:
                result[dataset] = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
    return result


def _load_meta(dataset_dir: Path) -> dict | None:
    path = dataset_dir / "meta.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
    return None


def _db_path(dataset_dir: Path) -> Path:
    return dataset_dir / "index.sqlite3"


def _index_size(dataset_dir: Path) -> int:
    total = 0
    for suffix in ("", "-wal", "-shm"):
        path = dataset_dir / ("index.sqlite3" + suffix)
        if path.exists():
            total += path.stat().st_size
    return total


def _connect_index(dataset_dir: Path) -> sqlite3.Connection:
    con = sqlite3.connect(str(_db_path(dataset_dir)))
    con.execute("PRAGMA journal_mode=OFF")
    con.execute("PRAGMA synchronous=NORMAL")
    return con


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _github_latest(fetcher: Callable[[str], dict] | None = None) -> dict:
    if fetcher is not None:
        return fetcher("https://api.github.com/repos/scriptin/jmdict-simplified/releases/latest")
    req = Request(
        "https://api.github.com/repos/scriptin/jmdict-simplified/releases/latest",
        headers={"User-Agent": "kotoba-localdict/0.1.0"},
    )
    with urlopen(req, timeout=30.0) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _asset_for(release: dict, prefix: str) -> dict | None:
    for asset in release.get("assets", []):
        name = asset.get("name", "")
        if name.startswith(prefix) and name.endswith(".json.tgz"):
            return asset
    return None


def _resolve_assets(release: dict) -> dict:
    mapping = {
        "jmdict-eng": "jmdict-eng-3",
        "jmdict-eng-common": "jmdict-eng-common-",
        "kanjidic2-en": "kanjidic2-en-",
        "kradfile": "kradfile-",
        "radkfile": "radkfile-",
    }
    assets: dict = {}
    for key, prefix in mapping.items():
        asset = _asset_for(release, prefix)
        if asset is None:
            continue
        assets[key] = asset
    if not assets:
        raise DictError("release contains no recognized assets")
    return assets


def _download(url: str, dest: Path, progress: FetchProgress | None = None, label: str = "") -> None:
    label = label or url
    if url.startswith("file://"):
        src = url[7:]
        shutil.copyfile(src, dest)
        return
    req = Request(url, headers={"User-Agent": "kotoba-localdict/0.1.0"})
    with urlopen(req, timeout=_DEFAULT_FETCH_TIMEOUT) as resp:
        total = resp.headers.get("Content-Length")
        total = int(total) if total else None
        _ensure_dir(dest.parent)
        fd, tmp = tempfile.mkstemp(dir=dest.parent, prefix=".download-", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as fh:
                received = 0
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    fh.write(chunk)
                    received += len(chunk)
                    if total and progress:
                        progress(label, "downloading", received / total)
            os.replace(tmp, dest)
        except Exception:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass
            raise


def _extract_json(tar_path: Path, dest_dir: Path) -> Path:
    with tarfile.open(tar_path, "r:gz") as tf:
        members = [m for m in tf.getmembers() if m.name.endswith(".json")]
        if not members:
            raise DictError("archive contains no .json file")
        tf.extractall(path=dest_dir, members=members[:1])
        extracted = dest_dir / members[0].name
    return extracted


def _parse_gloss(g: dict) -> str:
    return g.get("text", "")


def _build_jmdict_index(json_path: Path, dataset_dir: Path, dataset: str) -> None:
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


def _build_kanjidic2_index(json_path: Path, dataset_dir: Path) -> None:
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


def _build_kradfile_index(json_path: Path, dataset_dir: Path) -> None:
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


def _build_radkfile_index(json_path: Path, dataset_dir: Path) -> None:
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


def _indexer(dataset: str) -> Callable[[Path, Path], None]:
    if dataset in ("jmdict-eng", "jmdict-eng-common"):
        return lambda json_path, dataset_dir: _build_jmdict_index(json_path, dataset_dir, dataset)
    if dataset == "kanjidic2-en":
        return _build_kanjidic2_index
    if dataset == "kradfile":
        return _build_kradfile_index
    if dataset == "radkfile":
        return _build_radkfile_index
    raise DictError(f"no indexer for {dataset}")


def _dataset_dir(dataset: str) -> Path:
    return _data_dir() / dataset


def install(
    dataset: str,
    *,
    latest: bool = False,
    fetcher: Callable[[str], dict] | None = None,
    progress: FetchProgress | None = None,
) -> dict:
    if dataset not in _DATASET_NAMES:
        raise DictError(f"unknown dataset: {dataset}")

    release = _github_latest(fetcher)
    assets = _resolve_assets(release)
    asset = assets[dataset]
    url = asset["browser_download_url"]
    asset_name = asset["name"]
    version = release.get("tag_name", "unknown")
    expected = _PINNED.get(dataset)

    dataset_dir = _dataset_dir(dataset)
    _ensure_dir(dataset_dir)

    # mutual exclusion: remove conflicting jmdict variants
    for group in _MUTUAL_EXCLUSIVE:
        if dataset in group:
            for other in group:
                if other != dataset and _dataset_dir(other).exists():
                    remove(other)

    archive_path = dataset_dir / asset_name
    _download(url, archive_path, progress=progress, label=dataset)
    actual = _sha256_file(archive_path)
    if not latest and expected is not None and actual != expected:
        archive_path.unlink(missing_ok=True)
        raise DictError(
            f"hash mismatch for {dataset}: expected {expected}, got {actual}; upstream may have moved"
        )

    extracted = _extract_json(archive_path, dataset_dir)
    _indexer(dataset)(extracted, dataset_dir)
    extracted.unlink(missing_ok=True)

    license_name, source_url, license_id = _LICENSES[dataset]
    attribution = f"{license_name} from EDRDG ({license_id})"
    meta = {
        "name": dataset,
        "version": version,
        "asset": asset_name,
        "sha256": actual,
        "archive_bytes": archive_path.stat().st_size,
        "index_bytes": _index_size(dataset_dir),
        "size": archive_path.stat().st_size + _index_size(dataset_dir),
        "source_url": source_url,
        "license": license_id,
        "attribution": attribution,
        "retrieved_at": _now(),
    }
    (dataset_dir / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if latest and (expected is None or actual != expected):
        print(f"installed {dataset} {version} with sha256 {actual} — verify and update pinned hash if acceptable")

    return meta


def remove(dataset: str) -> bool:
    dataset_dir = _dataset_dir(dataset)
    if not dataset_dir.exists():
        return False
    shutil.rmtree(dataset_dir)
    return True


def reindex(dataset: str) -> dict:
    dataset_dir = _dataset_dir(dataset)
    meta = _load_meta(dataset_dir)
    if meta is None:
        raise DictError(f"no installed metadata for {dataset}")
    archive = dataset_dir / meta["asset"]
    if not archive.exists():
        raise DictError(f"stored archive missing for {dataset}")
    extracted = _extract_json(archive, dataset_dir)
    _indexer(dataset)(extracted, dataset_dir)
    extracted.unlink(missing_ok=True)
    return meta


def update(fetcher: Callable[[str], dict] | None = None, progress: FetchProgress | None = None) -> list[dict]:
    installed_names = list(installed().keys())
    results: list[dict] = []
    for dataset in installed_names:
        if _dataset_dir(dataset).exists():
            results.append(install(dataset, latest=False, fetcher=fetcher, progress=progress))
    return results


def _jmdict_installed() -> tuple[Path, dict] | None:
    for key in ("jmdict-eng", "jmdict-eng-common"):
        dataset_dir = _dataset_dir(key)
        meta = _load_meta(dataset_dir)
        if meta and _db_path(dataset_dir).exists():
            return dataset_dir, meta
    return None


def _kanjidic_installed() -> tuple[Path, dict] | None:
    dataset_dir = _dataset_dir("kanjidic2-en")
    meta = _load_meta(dataset_dir)
    if meta and _db_path(dataset_dir).exists():
        return dataset_dir, meta
    return None


def _krad_installed() -> tuple[Path, dict] | None:
    dataset_dir = _dataset_dir("kradfile")
    meta = _load_meta(dataset_dir)
    if meta and _db_path(dataset_dir).exists():
        return dataset_dir, meta
    return None


def _radk_installed() -> tuple[Path, dict] | None:
    dataset_dir = _dataset_dir("radkfile")
    meta = _load_meta(dataset_dir)
    if meta and _db_path(dataset_dir).exists():
        return dataset_dir, meta
    return None


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
        version = meta.get("version", "")
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


def status() -> list[dict]:
    result = []
    total = 0
    for dataset, meta in installed().items():
        dataset_dir = _data_dir() / dataset
        archive_bytes = meta.get("archive_bytes")
        index_bytes = meta.get("index_bytes")
        if index_bytes is None:
            index_bytes = _index_size(dataset_dir)
        if archive_bytes is None:
            archive_bytes = (dataset_dir / meta.get("asset", "")).stat().st_size if meta.get("asset") and (dataset_dir / meta["asset"]).exists() else 0
        size = archive_bytes + index_bytes
        total += size
        info = {
            "name": dataset,
            "version": meta.get("version", ""),
            "archive_bytes": archive_bytes,
            "index_bytes": index_bytes,
            "size": size,
            "source_url": meta.get("source_url", ""),
            "license": meta.get("license", ""),
            "attribution": meta.get("attribution", ""),
        }
        result.append(info)
    if result:
        result.append({
            "name": "total",
            "version": "",
            "archive_bytes": sum(r["archive_bytes"] for r in result if r["name"] != "total"),
            "index_bytes": sum(r["index_bytes"] for r in result if r["name"] != "total"),
            "size": total,
        })
    return result
