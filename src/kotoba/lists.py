from __future__ import annotations

import json
import os
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from kotoba.model import Entry, Sense

_FILE_VERSION = 1


class ListsError(Exception):
    pass


class _SerializableEntry(Entry):
    pass


def _data_dir() -> Path:
    base = os.environ.get("XDG_DATA_HOME")
    if base:
        return Path(base) / "kotoba"
    return Path.home() / ".local" / "share" / "kotoba"


def _lists_path() -> Path:
    return _data_dir() / "lists.json"


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _entry_to_dict(entry: Entry) -> dict:
    return {
        "headword": entry.headword,
        "reading": entry.reading or "",
        "source": getattr(entry, "source", None) or "",
        "senses": [
            {"pos": list(sense.pos), "glosses": list(sense.glosses)}
            for sense in entry.senses
        ],
        "tags": list(entry.tags),
        "url": getattr(entry, "url", None) or "",
        "added": getattr(entry, "added", None) or _now(),
    }


def _entry_from_dict(data: dict) -> Entry:
    return Entry(
        headword=data.get("headword", ""),
        reading=data.get("reading") or None,
        senses=tuple(
            Sense(
                pos=tuple(s.get("pos", [])),
                glosses=tuple(s.get("glosses", [])),
            )
            for s in data.get("senses", [])
        ),
        tags=tuple(data.get("tags", [])),
    )


def load() -> dict:
    path = _lists_path()
    if not path.exists():
        return _empty_state()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        raise ListsError(f"corrupt lists file: {exc}") from exc
    except OSError as exc:
        raise ListsError(f"cannot read lists file: {exc}") from exc

    if not isinstance(data, dict) or data.get("version") != _FILE_VERSION:
        raise ListsError("lists file has unsupported version")

    return data


def save(state: dict) -> None:
    path = _lists_path()
    _ensure_dir(path.parent)
    state.setdefault("version", _FILE_VERSION)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".lists.json.tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(state, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def _empty_state() -> dict:
    return {"version": _FILE_VERSION, "last_list": "default", "lists": {}}


def _default_list() -> dict:
    return {"created": _now(), "entries": []}


def _touch_list(state: dict, name: str) -> dict:
    if name not in state["lists"]:
        state["lists"][name] = _default_list()
    return state["lists"][name]


def _key(entry: Entry) -> tuple[str, str]:
    return (entry.headword, entry.reading or "")


def add_entry(list_name: str, entry: Entry, *, state: dict | None = None) -> tuple[dict, bool]:
    data = load() if state is None else state
    _touch_list(data, list_name)
    existing = {_key(_entry_from_dict(e)) for e in data["lists"][list_name]["entries"]}
    if _key(entry) in existing:
        return data, False
    data["lists"][list_name]["entries"].append(_entry_to_dict(entry))
    data["last_list"] = list_name
    return data, True


def remove_entry(list_name: str, headword: str, reading: str | None = None, *, state: dict | None = None) -> tuple[dict, bool]:
    data = load() if state is None else state
    if list_name not in data["lists"]:
        return data, False
    target = (headword, reading or "")
    before = len(data["lists"][list_name]["entries"])
    data["lists"][list_name]["entries"] = [
        e for e in data["lists"][list_name]["entries"]
        if (e.get("headword", ""), e.get("reading", "")) != target
    ]
    removed = len(data["lists"][list_name]["entries"]) < before
    return data, removed


def delete_list(name: str, *, state: dict | None = None) -> tuple[dict, bool]:
    data = load() if state is None else state
    if name not in data["lists"]:
        return data, False
    del data["lists"][name]
    if data.get("last_list") == name:
        data["last_list"] = next(iter(data["lists"].keys()), "default")
    return data, True


def get_list(name: str, *, state: dict | None = None) -> dict | None:
    data = load() if state is None else state
    return data["lists"].get(name)


def list_names(*, state: dict | None = None) -> list[str]:
    data = load() if state is None else state
    return list(data["lists"].keys())


def last_list(*, state: dict | None = None) -> str:
    data = load() if state is None else state
    return data.get("last_list", "default")
