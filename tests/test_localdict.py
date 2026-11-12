import hashlib
import json
import tarfile
from pathlib import Path
from typing import Callable

import pytest

from kotoba import config, localdict, lookup

JMDICT_WORDS = {
    "words": [
        {
            "id": "1000001",
            "kanji": [{"text": "猫", "common": True}],
            "kana": [{"text": "ねこ", "common": True, "appliesToKanji": ["*"]}],
            "sense": [{"partOfSpeech": ["n"], "gloss": [{"text": "cat"}]}],
        },
        {
            "id": "1000002",
            "kanji": [{"text": "猫又", "common": False}],
            "kana": [{"text": "ねこまた", "common": False, "appliesToKanji": ["*"]}],
            "sense": [{"partOfSpeech": ["n"], "gloss": [{"text": "bakeneko"}]}],
        },
        {
            "id": "1000003",
            "kanji": [{"text": "日本語", "common": True}],
            "kana": [{"text": "にほんご", "common": True, "appliesToKanji": ["*"]}],
            "sense": [{"partOfSpeech": ["n"], "gloss": [{"text": "Japanese language"}]}],
        },
        {
            "id": "1000004",
            "kanji": [],
            "kana": [{"text": "ありがとう", "common": True}],
            "sense": [{"partOfSpeech": ["int"], "gloss": [{"text": "thank you"}]}],
        },
    ]
}

KANJIDIC = {
    "characters": [
        {
            "literal": "猫",
            "misc": {"strokeCounts": [11], "grade": 8, "frequency": 1700, "jlptLevel": 2},
            "readingMeaning": {
                "rmgroup": [
                    {
                        "reading": [
                            {"type": "ja_on", "value": "ビョウ"},
                            {"type": "ja_kun", "value": "ねこ"},
                        ],
                        "meaning": [{"lang": "en", "value": "cat"}],
                    }
                ]
            },
            "radicals": [{"value": "犭"}, {"value": "苗"}],
        },
        {
            "literal": "日",
            "misc": {"strokeCounts": [4], "grade": 1, "frequency": 1},
            "readingMeaning": {"rmgroup": [{"reading": [{"type": "ja_on", "value": "ニチ"}]}]},
            "radicals": [{"value": "日"}],
        },
    ]
}

KRADFILE = {"kanji": {"猫": ["犭", "苗"], "日": ["日"]}}
RADKFILE = {"radicals": {"犭": {"strokeCount": 3, "kanji": ["猫"]}, "日": {"strokeCount": 4, "kanji": ["日"]}}}

_ASSET_NAMES = {
    "jmdict-eng": "jmdict-eng-3.6.2.json.tgz",
    "jmdict-eng-common": "jmdict-eng-common-3.6.2.json.tgz",
    "kanjidic2-en": "kanjidic2-en-3.6.2.json.tgz",
    "kradfile": "kradfile-3.6.2.json.tgz",
    "radkfile": "radkfile-3.6.2.json.tgz",
}

_PAYLOADS = {
    "jmdict-eng": ("jmdict-eng-3.6.2.json", JMDICT_WORDS),
    "jmdict-eng-common": ("jmdict-eng-common-3.6.2.json", JMDICT_WORDS),
    "kanjidic2-en": ("kanjidic2-en-3.6.2.json", KANJIDIC),
    "kradfile": ("kradfile-3.6.2.json", KRADFILE),
    "radkfile": ("radkfile-3.6.2.json", RADKFILE),
}


def _make_tarball(json_name: str, payload: dict, root: Path) -> Path:
    json_path = root / json_name
    json_path.write_text(json.dumps(payload), encoding="utf-8")
    tar_path = root / (json_name + ".tgz")
    with tarfile.open(tar_path, "w:gz") as tf:
        tf.add(str(json_path), arcname=json_name)
    return tar_path


def _release_metadata(asset_url_map: dict[str, str]) -> dict:
    return {
        "tag_name": "3.6.2+test",
        "assets": [
            {"name": name, "browser_download_url": url} for name, url in asset_url_map.items()
        ],
    }


def _fetcher_for(asset_url_map: dict[str, str]) -> Callable[[str], dict]:
    meta = _release_metadata(asset_url_map)

    def fetcher(url: str) -> dict:
        if "api.github.com" in url:
            return meta
        raise RuntimeError(f"unexpected fetch: {url}")

    return fetcher


@pytest.fixture
def assets(tmp_path: Path) -> dict[str, Path]:
    root = tmp_path / "assets"
    root.mkdir()
    built = {}
    for dataset, (json_name, payload) in _PAYLOADS.items():
        built[dataset] = _make_tarball(json_name, payload, root)
    return built


@pytest.fixture
def pinned(assets, monkeypatch) -> dict[str, str]:
    hashes = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in assets.items()}
    monkeypatch.setattr(localdict, "_PINNED", hashes)
    return hashes


@pytest.fixture
def fresh_data(tmp_path: Path, monkeypatch) -> Path:
    data_root = tmp_path / "data"
    monkeypatch.setenv("XDG_DATA_HOME", str(data_root))
    config_root = tmp_path / "config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_root))
    return data_root


def _fetcher(assets) -> Callable[[str], dict]:
    return _fetcher_for({_ASSET_NAMES[name]: "file://" + str(path) for name, path in assets.items()})


def _dataset_dir(dataset: str) -> Path:
    return localdict._data_dir() / dataset


def test_installed_empty(fresh_data):
    assert localdict.installed() == {}


def test_manifest_resolution_and_install(fresh_data, assets, pinned):
    meta = localdict.install("jmdict-eng", fetcher=_fetcher(assets))
    assert meta["name"] == "jmdict-eng"
    assert meta["version"].startswith("3.6.2")
    assert meta["license"] == "CC BY-SA 4.0"
    assert localdict.installed()["jmdict-eng"]["sha256"] == meta["sha256"]
    assert not (_dataset_dir("jmdict-eng") / "jmdict-eng-3.6.2.json").exists()


def test_hash_mismatch_aborts(fresh_data, assets, pinned):
    bad = assets["jmdict-eng"].parent / "bad.json.tgz"
    bad.write_bytes(assets["jmdict-eng"].read_bytes() + b"x")
    fetcher = _fetcher_for(
        {
            _ASSET_NAMES[name]: (
                "file://" + str(bad) if name == "jmdict-eng" else "file://" + str(path)
            )
            for name, path in assets.items()
        }
    )
    with pytest.raises(localdict.DictError, match="hash mismatch"):
        localdict.install("jmdict-eng", fetcher=fetcher)
    assert not (_dataset_dir("jmdict-eng") / "meta.json").exists()
    assert localdict.installed() == {}


def test_latest_bypasses_pin(fresh_data, assets, pinned, monkeypatch):
    monkeypatch.setitem(localdict._PINNED, "jmdict-eng", "0" * 64)
    meta = localdict.install("jmdict-eng", fetcher=_fetcher(assets), latest=True)
    assert meta["sha256"] != "0" * 64


def test_install_index_lookup_ranking(fresh_data, assets, pinned):
    localdict.install("jmdict-eng", fetcher=_fetcher(assets))
    result = localdict.lookup("猫", limit=5)
    assert [e.headword for e in result.entries] == ["猫", "猫又"]
    assert result.entries[0].reading == "ねこ"
    assert result.entries[0].senses[0].glosses == ("cat",)
    assert "common" in result.entries[0].tags
    assert result.entries[0].source == "jmdict"
    assert result.source == "jmdict"


def test_lookup_limit_and_kana_only(fresh_data, assets, pinned):
    localdict.install("jmdict-eng", fetcher=_fetcher(assets))
    assert len(localdict.lookup("猫", limit=1).entries) == 1
    kana = localdict.lookup("ありがとう", limit=5)
    assert kana.entries[0].headword == "ありがとう"


def test_lookup_prefix_and_substring_fallthrough(fresh_data, assets, pinned):
    localdict.install("jmdict-eng", fetcher=_fetcher(assets))
    assert [e.headword for e in localdict.lookup("日本", limit=5).entries] == ["日本語"]
    assert [e.headword for e in localdict.lookup("本語", limit=5).entries] == ["日本語"]


def test_mutual_exclusion_jmdict(fresh_data, assets, pinned):
    fetcher = _fetcher(assets)
    localdict.install("jmdict-eng", fetcher=fetcher)
    localdict.install("jmdict-eng-common", fetcher=fetcher)
    installed = localdict.installed()
    assert "jmdict-eng-common" in installed
    assert "jmdict-eng" not in installed


def test_kanji_lookup(fresh_data, assets, pinned):
    fetcher = _fetcher(assets)
    localdict.install("kanjidic2-en", fetcher=fetcher)
    localdict.install("kradfile", fetcher=fetcher)
    info = localdict.kanji("猫")
    assert info is not None
    assert info["literal"] == "猫"
    assert info["stroke_count"] == 11
    assert info["on_readings"] == ["ビョウ"]
    assert info["kun_readings"] == ["ねこ"]
    assert info["meanings"] == ["cat"]
    assert info["components"] == ["犭", "苗"]


def test_kanji_missing_dataset(fresh_data):
    assert localdict.kanji("猫") is None


def test_kanji_without_kradfile_has_no_components(fresh_data, assets, pinned):
    localdict.install("kanjidic2-en", fetcher=_fetcher(assets))
    info = localdict.kanji("日")
    assert info is not None
    assert info["components"] == []


def test_config_round_trip(fresh_data):
    assert config.mode() == "local-first"
    config.set_mode("api-only")
    assert config.mode() == "api-only"
    assert config.ask_at_startup() is True
    config.ask_at_startup(False)
    assert config.ask_at_startup() is False
    config.onboarding_done(True)
    assert config.onboarding_done() is True


def test_lookup_mode_api_only_no_local(monkeypatch, fresh_data):
    from kotoba.model import Entry, LookupResult, Sense

    fake = LookupResult(
        query="猫",
        source="jisho",
        entries=(Entry(headword="猫", reading="ねこ", senses=(Sense(pos=("Noun",), glosses=("cat",)),)),),
    )
    monkeypatch.setattr("kotoba.langs.japanese.fetch", lambda q, limit=None: fake)
    assert lookup.lookup("jisho", "猫", 5, mode="api-only").entries


def test_lookup_local_only_miss(fresh_data, assets, pinned):
    localdict.install("jmdict-eng", fetcher=_fetcher(assets))
    with pytest.raises(lookup.LookupError, match="not in local dictionary"):
        lookup.lookup("jisho", "xyznotaword", 5, mode="local-only")


def test_lookup_local_first_uses_local(fresh_data, assets, pinned, monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("api should not be called")

    monkeypatch.setattr("kotoba.lookup._api_lookup", boom)
    localdict.install("jmdict-eng", fetcher=_fetcher(assets))
    assert lookup.lookup("jisho", "猫", 5, mode="local-first").entries


def test_lookup_no_data_fallback(monkeypatch, fresh_data):
    from kotoba.model import Entry, LookupResult, Sense

    called = []

    def fake_api(source, query, limit):
        called.append((source, query))
        return LookupResult(
            query=query,
            source="jisho",
            entries=(Entry(headword=query, reading=None, senses=(Sense(pos=("Noun",), glosses=("fake",)),)),),
        )

    monkeypatch.setattr("kotoba.lookup._api_lookup", fake_api)
    assert lookup.lookup("jisho", "猫", 5, mode="local-first").entries
    assert called == [("jisho", "猫")]


def test_install_records_archive_and_index_bytes(fresh_data, assets, pinned):
    localdict.install("jmdict-eng", fetcher=_fetcher(assets))
    dataset_dir = _dataset_dir("jmdict-eng")
    meta = json.loads((dataset_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["archive_bytes"] == (dataset_dir / meta["asset"]).stat().st_size
    assert meta["index_bytes"] == localdict._index_size(dataset_dir)
    assert meta["size"] == meta["archive_bytes"] + meta["index_bytes"]


def test_status_total_equals_sum(fresh_data, assets, pinned):
    localdict.install("jmdict-eng", fetcher=_fetcher(assets))
    rows = localdict.status()
    data = {r["name"]: r for r in rows}
    row = data["jmdict-eng"]
    assert row["size"] == row["archive_bytes"] + row["index_bytes"]
    assert data["total"]["size"] == data["total"]["archive_bytes"] + data["total"]["index_bytes"]


def test_legacy_meta_without_index_bytes_reports_sane_size(fresh_data, assets, pinned):
    localdict.install("jmdict-eng", fetcher=_fetcher(assets))
    dataset_dir = _dataset_dir("jmdict-eng")
    meta = json.loads((dataset_dir / "meta.json").read_text(encoding="utf-8"))
    del meta["archive_bytes"]
    del meta["index_bytes"]
    (dataset_dir / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    rows = localdict.status()
    row = next(r for r in rows if r["name"] == "jmdict-eng")
    expected_index = localdict._index_size(dataset_dir)
    expected_archive = (dataset_dir / meta["asset"]).stat().st_size
    assert row["index_bytes"] == expected_index
    assert row["archive_bytes"] == expected_archive
    assert row["size"] == expected_archive + expected_index
    # legacy metadata is not rewritten
    assert "index_bytes" not in json.loads((dataset_dir / "meta.json").read_text(encoding="utf-8"))


def test_local_status_and_remove(fresh_data, assets, pinned):
    localdict.install("jmdict-eng", fetcher=_fetcher(assets))
    rows = localdict.status()
    assert any(r["name"] == "jmdict-eng" for r in rows)
    assert localdict.remove("jmdict-eng") is True
    assert localdict.remove("jmdict-eng") is False
    assert localdict.status() == []


def test_update_reinstalls_installed(fresh_data, assets, pinned):
    fetcher = _fetcher(assets)
    localdict.install("kanjidic2-en", fetcher=fetcher)
    updated = lookup.update(fetcher=fetcher)
    assert [row["name"] for row in updated] == ["kanjidic2-en"]


def test_reindex_keeps_archive_and_index(fresh_data, assets, pinned):
    localdict.install("kradfile", fetcher=_fetcher(assets))
    dataset_dir = _dataset_dir("kradfile")
    assert (dataset_dir / "index.sqlite3").exists()
    lookup.reindex("kradfile")
    assert (dataset_dir / "index.sqlite3").exists()
    assert (dataset_dir / _ASSET_NAMES["kradfile"]).exists()
