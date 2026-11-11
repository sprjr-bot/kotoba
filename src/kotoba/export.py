from __future__ import annotations

import html
import json
import os
import stat
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from kotoba.model import Entry, Sense

if TYPE_CHECKING:
    import genanki


def _data_dir() -> Path:
    base = os.environ.get("XDG_DATA_HOME")
    if base:
        return Path(base) / "kotoba"
    return Path.home() / ".local" / "share" / "kotoba"


def _exports_dir() -> Path:
    return _data_dir() / "exports"


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def _stable_id(text: str) -> int:
    import zlib

    return zlib.crc32(text.encode("utf-8")) % (2 ** 31)


def _senses_html(entry: _ExportEntry) -> str:
    items = "\n".join(
        f"<li>{html.escape(', '.join(sense.pos))}: {html.escape('; '.join(sense.glosses))}</li>"
        for sense in entry.senses
    )
    return f"<ul>\n{items}\n</ul>" if items else ""


def _glosses_html(entry: _ExportEntry) -> str:
    items = "\n".join(
        f"<li>{html.escape('; '.join(sense.glosses))}</li>"
        for sense in entry.senses
    )
    return f"<ul>\n{items}\n</ul>" if items else ""


def _tsv_text(text: str | None) -> str:
    if not text:
        return ""
    return text.replace("\t", " ").replace("\n", " ").replace("\r", " ")


def _tags(entry: _ExportEntry, list_name: str) -> list[str]:
    base = [list_name.replace(" ", "_")]
    base.extend(tag.replace(" ", "_") for tag in entry.tags)
    return base


@dataclass(frozen=True)
class _ExportEntry(Entry):
    source: str = ""
    url: str = ""
    added: str = ""


def _wrap(entry: Entry, *, source: str = "", url: str = "", added: str = "") -> _ExportEntry:
    return _ExportEntry(
        headword=entry.headword,
        reading=entry.reading,
        senses=entry.senses,
        tags=entry.tags,
        source=source,
        url=url,
        added=added,
    )


def _model_jp() -> "genanki.Model":
    import genanki

    return genanki.Model(
        model_id=_stable_id("kotoba-model-kotoba JP"),
        name="kotoba JP",
        fields=[
            {"name": "Front"},
            {"name": "Reading"},
            {"name": "Back"},
            {"name": "Source"},
        ],
        templates=[
            {
                "name": "Recognition",
                "qfmt": "{{Front}}",
                "afmt": '{{Front}}<hr id="answer">{{Back}}<br><span style="color: #666;">{{Reading}}</span><br><small><a href="{{Source}}">{{Source}}</a></small>',
            },
        ],
        css=""".card { font-family: sans-serif; font-size: 20px; text-align: center; }
.answer { color: #333; }""",
    )


def _model_en() -> "genanki.Model":
    import genanki

    return genanki.Model(
        model_id=_stable_id("kotoba-model-kotoba EN"),
        name="kotoba EN",
        fields=[
            {"name": "Front"},
            {"name": "Back"},
            {"name": "Source"},
        ],
        templates=[
            {
                "name": "Recall",
                "qfmt": "{{Front}}",
                "afmt": '{{Front}}<hr id="answer">{{Back}}<br><small><a href="{{Source}}">{{Source}}</a></small>',
            },
        ],
        css=""".card { font-family: sans-serif; font-size: 20px; text-align: center; }
.answer { color: #333; }""",
    )


def _apkg(entries: list[_ExportEntry], list_name: str, path: Path) -> Path:
    import genanki

    deck_id = _stable_id(f"kotoba-deck-{list_name}")
    deck = genanki.Deck(deck_id=deck_id, name=f"kotoba::{list_name}")
    model_jp = _model_jp()
    model_en = _model_en()

    for entry in entries:
        tags = _tags(entry, list_name)
        reading = entry.reading or ""
        if entry.reading is None or entry.reading == entry.headword:
            model = model_en
            fields = [entry.headword, _glosses_html(entry), entry.url]
        else:
            model = model_jp
            fields = [entry.headword, reading, _senses_html(entry), entry.url]
        deck.add_note(genanki.Note(model=model, fields=fields, tags=tags))

    pkg = genanki.Package(deck)
    _ensure_dir(path.parent)
    pkg.write_to_file(str(path))
    return path


def _tsv(entries: list[_ExportEntry], list_name: str, path: Path) -> Path:
    lines = [
        "#separator:tab",
        "#html:true",
        "#tags column:4",
    ]
    for entry in entries:
        front = _tsv_text(entry.headword)
        reading = _tsv_text(entry.reading or "")
        back = _tsv_text(_senses_html(entry) if entry.reading else _glosses_html(entry))
        tags = " ".join(_tags(entry, list_name))
        lines.append("\t".join([front, back, reading, tags]))

    _ensure_dir(path.parent)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def export_list(
    entries: list[Entry],
    list_name: str,
    fmt: str,
    *,
    output_dir: Path | None = None,
    source: str = "",
    url: str = "",
    added: str = "",
) -> list[Path]:
    if fmt not in ("apkg", "tsv", "both"):
        raise ValueError(f"unsupported export format: {fmt}")

    wrapped = [_wrap(e, source=source, url=url, added=added) for e in entries]
    out = output_dir or _exports_dir()
    date = _today()
    written: list[Path] = []

    if fmt in ("apkg", "both"):
        apkg_path = out / f"kotoba-{list_name}-{date}.apkg"
        written.append(_apkg(wrapped, list_name, apkg_path))

    if fmt in ("tsv", "both"):
        tsv_path = out / f"kotoba-{list_name}-{date}.tsv"
        written.append(_tsv(wrapped, list_name, tsv_path))

    return written


def verify_apkg(path: Path) -> dict:
    with zipfile.ZipFile(path) as zf:
        if "collection.anki2" not in zf.namelist():
            raise ValueError("missing collection.anki2")
        db_bytes = zf.read("collection.anki2")

    tmp = Path(tempfile.mktemp(suffix=".anki2"))
    tmp.write_bytes(db_bytes)
    try:
        import sqlite3

        con = sqlite3.connect(str(tmp))
        models = json.loads(con.execute("select models from col").fetchone()[0])
        decks = json.loads(con.execute("select decks from col").fetchone()[0])
        notes = con.execute("select id, mid, flds, tags from notes").fetchall()
        cards = con.execute("select id, nid, did from cards").fetchall()
        con.close()
        return {
            "models": list(models.keys()),
            "decks": list(decks.keys()),
            "deck_names": [d.get("name") for d in decks.values()],
            "notes": len(notes),
            "cards": len(cards),
        }
    finally:
        tmp.unlink(missing_ok=True)


try:
    import genanki  # noqa: F401
except Exception as exc:

    def _apkg(*args, **kwargs):
        raise ImportError("genanki is not installed; install it to export .apkg") from exc

    export_list  # silence unused
