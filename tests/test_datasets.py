import gzip
import hashlib
import json
import os
import sqlite3
import tarfile
import tempfile
from pathlib import Path
from typing import Callable

import pytest

from kotoba import datasets, localdict


def _make_tgz_json(dest: Path, member_name: str, payload: dict | list) -> None:
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        tmp_path = Path(tmp.name)
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with tarfile.open(dest, "w:gz") as tf:
        tf.add(tmp_path, arcname=member_name)
    tmp_path.unlink()


def _jmdict_payload() -> dict:
    return {
        "words": [
            {
                "id": "1",
                "kana": [{"text": "ねこ", "tags": [], "appliesToKanji": ["猫"]}],
                "kanji": [{"common": True, "text": "猫", "tags": []}],
                "sense": [
                    {
                        "antonym": [],
                        "appliesToKanji": [],
                        "appliesToKana": [],
                        "dialect": [],
                        "field": [],
                        "gloss": [{"lang": "eng", "text": "cat"}],
                        "info": [],
                        "misc": [],
                        "partOfSpeech": ["n"],
                        "related": [],
                        "restrictions": [],
                        "senseIndex": 0,
                        "tags": [],
                    }
                ],
                "priority": 0,
            }
        ]
    }


def _kanjidic_payload() -> dict:
    return {
        "characters": [
            {
                "literal": "猫",
                "misc": {"grade": 4, "strokeCounts": [11]},
                "readingMeaning": {
                    "groups": [
                        {
                            "readings": [
                                {"type": "ja_on", "text": "ビョウ"},
                                {"type": "ja_kun", "text": "ねこ"},
                            ],
                            "meanings": [{"lang": "en", "text": "cat"}],
                        }
                    ],
                    "nanori": [],
                },
                "radicals": {"classical": 94, "nelson_c": 94},
            }
        ]
    }


@pytest.fixture
def fresh_dirs(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    return tmp_path


def _asset_name(name: str) -> str:
    return f"{datasets.descriptor(name).asset_prefix}{datasets.descriptor(name).version}.json.tgz"


@pytest.fixture
def assets(tmp_path: Path):
    base = tmp_path / "assets"
    base.mkdir()
    payloads = {
        "jmdict-eng": _jmdict_payload(),
        "jmdict-eng-common": _jmdict_payload(),
        "kanjidic2-en": _kanjidic_payload(),
    }
    paths: dict[str, Path] = {}
    for name, payload in payloads.items():
        archive = base / _asset_name(name)
        _make_tgz_json(archive, f"{name}.json", payload)
        paths[name] = archive
    return paths


def _fetcher(assets: dict[str, Path]) -> Callable[[str], dict]:
    by_name = {path.name: path for path in assets.values()}

    def fetch(url: str) -> dict:
        if "api.github.com/repos/scriptin/jmdict-simplified" in url:
            return {
                "tag_name": "3.6.2",
                "assets": [
                    {
                        "name": name,
                        "browser_download_url": f"file://{path}",
                    }
                    for name, path in by_name.items()
                ],
            }
        raise RuntimeError(f"no fixture for {url}")
    return fetch


@pytest.fixture
def pinned(assets, monkeypatch):
    hashes = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in assets.items()}
    registry = datasets.registry()
    for name, digest in hashes.items():
        monkeypatch.setattr(registry[name], "sha256", digest)
    return hashes


def test_install_jmdict(fresh_dirs, assets, pinned):
    meta = datasets.install("jmdict-eng", fetcher=_fetcher(assets))
    assert meta["descriptor_id"] == "jmdict-eng"
    assert meta["sha256"] == pinned["jmdict-eng"]
    db = datasets.dataset_dir("jmdict-eng") / "index.sqlite3"
    assert db.exists()
    con = sqlite3.connect(str(db))
    try:
        row = con.execute("SELECT headword, reading FROM entries WHERE headword = '猫'").fetchone()
        assert row == ("猫", "ねこ")
    finally:
        con.close()


def test_hash_mismatch_aborts(fresh_dirs, assets, pinned):
    registry = datasets.registry()
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(registry["jmdict-eng"], "sha256", "0" * 64)
    with pytest.raises(datasets.DictError) as exc:
        datasets.install("jmdict-eng", fetcher=_fetcher(assets))
    assert "accept-new-dump" in str(exc.value)
    assert not datasets.dataset_dir("jmdict-eng").exists()
    monkeypatch.undo()


def test_accept_new_dump_bypasses_pin(fresh_dirs, assets, pinned):
    registry = datasets.registry()
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(registry["jmdict-eng"], "sha256", "0" * 64)
    meta = datasets.install("jmdict-eng", fetcher=_fetcher(assets), accept_new_dump=True)
    assert meta["sha256"] != "0" * 64
    assert datasets.dataset_dir("jmdict-eng").exists()
    monkeypatch.undo()


def test_conflicts_replace_existing(fresh_dirs, assets, pinned):
    datasets.install("jmdict-eng", fetcher=_fetcher(assets))
    assert datasets.dataset_dir("jmdict-eng").exists()
    registry = datasets.registry()
    registry["jmdict-eng-common"].conflicts_with = ["jmdict-eng"]
    datasets.install("jmdict-eng-common", fetcher=_fetcher(assets))
    assert not datasets.dataset_dir("jmdict-eng").exists()
    assert datasets.dataset_dir("jmdict-eng-common").exists()


def test_cache_reuse_across_languages(fresh_dirs, assets, pinned, monkeypatch):
    downloaded_urls: list[str] = []
    original_download = datasets._download

    def tracked_download(url, dest, progress=None, label=""):
        downloaded_urls.append(url)
        return original_download(url, dest, progress=progress, label=label)

    monkeypatch.setattr(datasets, "_download", tracked_download)
    datasets.install("jmdict-eng", fetcher=_fetcher(assets))
    datasets.install("jmdict-eng-common", fetcher=_fetcher(assets))
    assert len(downloaded_urls) == 2
    assert datasets.download_dir().exists()
    datasets.clear_download_cache()
    assert not datasets.download_dir().exists()


def test_legacy_meta_migrated(fresh_dirs, tmp_path: Path):
    data_root = Path(os.environ["XDG_DATA_HOME"]) / "kotoba" / "dict"
    legacy_dir = data_root / "jmdict-eng"
    legacy_dir.mkdir(parents=True)
    meta = {
        "name": "jmdict-eng",
        "version": "3.6.2",
        "asset": "jmdict-eng-3.6.2.json.tgz",
        "sha256": "a" * 64,
        "archive_bytes": 100,
        "index_bytes": 200,
        "size": 300,
        "source_url": "https://example.com",
        "license": "CC BY-SA 4.0",
        "attribution": "EDRDG",
        "retrieved_at": "2026-01-01T00:00:00Z",
    }
    (legacy_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    installed = datasets.installed()
    assert installed["jmdict-eng"]["descriptor_id"] == "jmdict-eng"


def test_clear_download_cache(fresh_dirs):
    cache = datasets.download_dir()
    cache.mkdir(parents=True)
    (cache / "x.tgz").write_bytes(b"12345")
    files, size = datasets.clear_download_cache()
    assert files == 1
    assert size == 5
    assert not cache.exists()


def test_status_total_row(fresh_dirs, assets, pinned):
    datasets.install("jmdict-eng", fetcher=_fetcher(assets))
    rows = datasets.status()
    assert rows[-1]["name"] == "total"
    assert rows[-1]["size"] > 0


def test_dataset_attribution_block(fresh_dirs, assets, pinned):
    datasets.install("jmdict-eng", fetcher=_fetcher(assets))
    block = datasets.dataset_attribution_block()
    assert len(block["datasets"]) == 1
    assert block["datasets"][0]["name"] == "jmdict-eng"
    assert block["datasets"][0]["license"] == "CC BY-SA 4.0"


def test_kaikki_gzip_jsonl_stream(fresh_dirs, tmp_path: Path):
    fixture = tmp_path / "raw.jsonl.gz"
    valid = {"word": "gato", "lang_code": "es", "pos": "noun", "senses": [{"glosses": ["cat"]}]}
    other_lang = {"word": "chat", "lang_code": "fr", "pos": "noun", "senses": [{"glosses": ["cat"]}]}
    no_gloss = {"word": "perro", "lang_code": "es", "pos": "noun", "senses": []}
    with gzip.open(fixture, "wb") as gz:
        gz.write((json.dumps(valid, ensure_ascii=False) + "\n").encode("utf-8"))
        gz.write((json.dumps(other_lang, ensure_ascii=False) + "\n").encode("utf-8"))
        gz.write((json.dumps(no_gloss, ensure_ascii=False) + "\n").encode("utf-8"))

    from kotoba.langs import kaikki

    dataset_dir = tmp_path / "kaikki-es"
    class _Desc:
        language = "es"
    kaikki.ingest_kaikki(fixture, dataset_dir, _Desc())
    con = sqlite3.connect(str(dataset_dir / "index.sqlite3"))
    try:
        rows = con.execute("SELECT headword, glosses FROM entries").fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "gato"
        assert json.loads(rows[0][1]) == ["cat"]
    finally:
        con.close()


def test_kaikki_jsonl_gz_install_via_file_fetcher(fresh_dirs, tmp_path: Path, monkeypatch):
    """A jsonl.gz archive is streamed directly; no decompressed payload is left in the dataset dir."""
    fixture = tmp_path / "raw.jsonl.gz"
    valid = {"word": "gato", "lang_code": "es", "pos": "noun", "senses": [{"glosses": ["cat"]}]}
    other_lang = {"word": "chat", "lang_code": "fr", "pos": "noun", "senses": [{"glosses": ["cat"]}]}
    with gzip.open(fixture, "wb") as gz:
        gz.write((json.dumps(valid, ensure_ascii=False) + "\n").encode("utf-8"))
        gz.write((json.dumps(other_lang, ensure_ascii=False) + "\n").encode("utf-8"))

    test_id = "kaikki-es-test"
    test_descriptor = datasets.DatasetDescriptor(
        id=test_id,
        language="es",
        name="Kaikki Spanish test fixture",
        url=f"file://{fixture}",
        license="CC BY-SA 4.0",
        attribution="test",
        archive_format="jsonl.gz",
        extraction_shape="gzip-jsonl-lines",
        ingest="kotoba.langs.kaikki:ingest_kaikki",
        version="rolling",
        retain_archive=False,
        archive_bytes_hint=fixture.stat().st_size,
    )
    monkeypatch.setattr(datasets, "_REGISTRY", {test_id: test_descriptor})

    meta = datasets.install(test_id)
    dataset_dir = datasets.dataset_dir(test_id)
    assert dataset_dir.exists()
    assert (dataset_dir / "index.sqlite3").exists()
    assert meta["name"] == test_id

    con = sqlite3.connect(str(dataset_dir / "index.sqlite3"))
    try:
        rows = con.execute("SELECT headword, glosses FROM entries").fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "gato"
        assert json.loads(rows[0][1]) == ["cat"]
    finally:
        con.close()

    # The fix deliberately avoids materialising a decompressed .jsonl payload.
    assert not list(dataset_dir.glob("*.jsonl"))
    assert not list(dataset_dir.glob("*.jsonl.gz"))  # archive is not retained either
