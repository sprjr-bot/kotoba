from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path

import pytest

from kotoba.lists import (
    ListsError,
    add_entry,
    delete_list,
    get_list,
    last_list,
    list_names,
    load,
    remove_entry,
    save,
)
from kotoba.model import Entry, Sense


@pytest.fixture
def lists_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    return tmp_path / "kotoba"


def _entry(headword: str, reading: str | None = None) -> Entry:
    return Entry(
        headword=headword,
        reading=reading,
        senses=(Sense(pos=("Noun",), glosses=("cat",)),),
        tags=("common",),
    )


def test_round_trip(lists_dir):
    state, added = add_entry("default", _entry("猫", "ねこ"))
    save(state)
    loaded = load()
    assert last_list(state=loaded) == "default"
    entries = get_list("default", state=loaded)["entries"]
    assert len(entries) == 1
    assert entries[0]["headword"] == "猫"


def test_atomic_write_leaves_no_temp_files(lists_dir):
    state, _ = add_entry("default", _entry("猫"))
    save(state)
    assert not any(lists_dir.glob(".lists.json.tmp-*"))


def test_dedupe_per_list(lists_dir):
    state, added = add_entry("default", _entry("猫", "ねこ"))
    assert added
    state, added = add_entry("default", _entry("猫", "ねこ"), state=state)
    assert not added
    assert len(get_list("default", state=state)["entries"]) == 1


def test_remove_entry(lists_dir):
    state, _ = add_entry("default", _entry("猫", "ねこ"))
    state, removed = remove_entry("default", "猫", "ねこ", state=state)
    assert removed
    assert len(get_list("default", state=state)["entries"]) == 0


def test_delete_list(lists_dir):
    state, _ = add_entry("jp", _entry("猫"))
    state, deleted = delete_list("jp", state=state)
    assert deleted
    assert "jp" not in list_names(state=state)


def test_corrupt_file_raises(lists_dir):
    path = lists_dir / "lists.json"
    path.parent.mkdir(parents=True)
    path.write_text("not json", encoding="utf-8")
    with pytest.raises(ListsError, match="corrupt"):
        load()


def test_file_mode_and_parent_permissions(lists_dir):
    state, _ = add_entry("default", _entry("猫"))
    save(state)
    assert stat.S_IMODE(lists_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE((lists_dir / "lists.json").stat().st_mode) == 0o600
