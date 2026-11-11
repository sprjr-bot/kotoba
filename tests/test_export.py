from __future__ import annotations

import html
import tempfile
import zipfile
from pathlib import Path
from unittest import mock

import pytest

from kotoba.export import export_list, verify_apkg
from kotoba.model import Entry, Sense


@pytest.fixture
def exports_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    return tmp_path / "kotoba" / "exports"


def _entry(headword="猫", reading="ねこ", source="jisho", tags=("common",), url="https://jisho.org/search/%E7%8C%AB"):
    return Entry(
        headword=headword,
        reading=reading,
        senses=(Sense(pos=("Noun",), glosses=("cat",)),),
        tags=tags,
    )


def _entry_en(headword="love", url="https://wordnet"):
    return Entry(
        headword=headword,
        reading=None,
        senses=(Sense(pos=("Noun",), glosses=("a strong positive emotion",)),),
        tags=(),
    )


def test_tsv_content_and_pragmas(exports_dir):
    paths = export_list([_entry()], "default", "tsv")
    assert len(paths) == 1
    text = paths[0].read_text(encoding="utf-8")
    lines = text.splitlines()
    assert lines[0] == "#separator:tab"
    assert lines[1] == "#html:true"
    assert lines[2] == "#tags column:4"
    parts = lines[3].split("\t")
    assert parts[0] == "猫"
    assert parts[2] == "ねこ"
    assert "<ul>" in parts[1]
    assert "default" in parts[3]


def test_tsv_sanitises_tabs_and_newlines(exports_dir):
    entry = Entry(
        headword="bad\ttab\nline",
        reading="x",
        senses=(Sense(pos=("Noun",), glosses=("cat",)),),
        tags=("common",),
    )
    paths = export_list([entry], "default", "tsv")
    line = paths[0].read_text(encoding="utf-8").splitlines()[3]
    fields = line.split("\t")
    assert len(fields) == 4
    assert all("\t" not in f and "\n" not in f for f in fields)
    assert "bad tab line" in fields[0]


def test_tsv_escapes_html(exports_dir):
    entry = Entry(
        headword="x",
        reading="y",
        senses=(Sense(pos=("Noun",), glosses=("a <b>cat</b>",)),),
        tags=(),
    )
    paths = export_list([entry], "default", "tsv")
    back = paths[0].read_text(encoding="utf-8").splitlines()[3].split("\t")[1]
    assert "<b>" not in back
    assert "&lt;b&gt;" in back


def test_apkg_built_and_verified(exports_dir):
    paths = export_list([_entry()], "default", "apkg", source="jisho", url="https://jisho.org/search/%E7%8C%AB")
    assert len(paths) == 1
    info = verify_apkg(paths[0])
    assert info["notes"] == 1
    assert info["cards"] == 1
    assert len(info["models"]) == 1
    assert any("default" in name for name in info["deck_names"])


def test_apkg_includes_en_model_for_wordnet(exports_dir):
    paths = export_list([_entry_en()], "en", "apkg", source="wordnet", url="https://wordnet")
    info = verify_apkg(paths[0])
    assert info["notes"] == 1


def test_apkg_deterministic_ids_across_runs(exports_dir):
    a = export_list([_entry()], "default", "apkg", source="jisho", url="https://jisho.org/search/%E7%8C%AB")[0]
    b = export_list([_entry()], "default", "apkg", source="jisho", url="https://jisho.org/search/%E7%8C%AB")[0]
    with zipfile.ZipFile(a) as z:
        da = z.read("collection.anki2")
    with zipfile.ZipFile(b) as z:
        db = z.read("collection.anki2")
    assert da == db


def test_both_writes_apkg_and_tsv(exports_dir):
    paths = export_list([_entry()], "default", "both")
    assert sorted(p.suffix for p in paths) == [".apkg", ".tsv"]


def test_apkg_mixed_list_emits_both_models(exports_dir):
    jp = Entry(
        headword="猫",
        reading="ねこ",
        senses=(Sense(pos=("Noun",), glosses=("cat",)),),
        tags=("common",),
        source="jisho",
        url="https://jisho",
    )
    en = Entry(
        headword="love",
        reading=None,
        senses=(Sense(pos=("Noun",), glosses=("a strong positive emotion",)),),
        tags=(),
        source="wordnet",
        url="https://wordnet",
    )
    paths = export_list([jp, en], "mixed", "apkg")
    info = verify_apkg(paths[0])
    assert info["notes"] == 2
    with zipfile.ZipFile(paths[0]) as zf:
        db_bytes = zf.read("collection.anki2")
    tmp = Path(tempfile.NamedTemporaryFile(delete=False, suffix=".anki2").name)
    tmp.write_bytes(db_bytes)
    try:
        import sqlite3

        con = sqlite3.connect(str(tmp))
        model_rows = con.execute("select mid, flds from notes").fetchall()
        con.close()
    finally:
        tmp.unlink(missing_ok=True)
    field_counts = sorted(len(fields.split("\x1f")) for _, fields in model_rows)
    assert field_counts == [3, 4]


def test_apkg_jisho_missing_reading_uses_jp_model(exports_dir):
    entry = Entry(
        headword="猫",
        reading=None,
        senses=(Sense(pos=("Noun",), glosses=("cat",)),),
        source="jisho",
        url="https://jisho",
    )
    paths = export_list([entry], "default", "apkg")
    info = verify_apkg(paths[0])
    assert info["notes"] == 1
    with zipfile.ZipFile(paths[0]) as zf:
        db_bytes = zf.read("collection.anki2")
    tmp = Path(tempfile.NamedTemporaryFile(delete=False, suffix=".anki2").name)
    tmp.write_bytes(db_bytes)
    try:
        import sqlite3

        con = sqlite3.connect(str(tmp))
        _, fields = con.execute("select mid, flds from notes").fetchone()
        con.close()
    finally:
        tmp.unlink(missing_ok=True)
    assert len(fields.split("\x1f")) == 4


def test_tsv_uses_source_to_pick_back_field(exports_dir):
    jp = Entry(
        headword="猫",
        reading="ねこ",
        senses=(Sense(pos=("Noun",), glosses=("cat",)),),
        source="jisho",
    )
    en = Entry(
        headword="love",
        reading=None,
        senses=(Sense(pos=("Noun",), glosses=("a strong positive emotion",)),),
        source="wordnet",
    )
    paths = export_list([jp, en], "mixed", "tsv")
    lines = paths[0].read_text(encoding="utf-8").splitlines()
    jp_line = lines[3].split("\t")
    en_line = lines[4].split("\t")
    assert "Noun" in jp_line[1]
    assert "cat" in jp_line[1]
    assert "a strong positive emotion" in en_line[1]


def test_filename_sanitises_list_name(exports_dir):
    paths = export_list(
        [Entry(headword="x", reading="y", senses=(Sense(pos=("Noun",), glosses=("z",)),))],
        "../../escape",
        "tsv",
    )
    assert len(paths) == 1
    assert paths[0].parent == exports_dir
    assert paths[0].name.startswith("kotoba-escape-")


def test_filename_falls_back_to_list(exports_dir):
    paths = export_list(
        [Entry(headword="x", reading="y", senses=(Sense(pos=("Noun",), glosses=("z",)),))],
        "../../",
        "tsv",
    )
    assert paths[0].name.startswith("kotoba-list-")
