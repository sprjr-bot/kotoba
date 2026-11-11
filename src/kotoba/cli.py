from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from kotoba.export import export_list
from kotoba.lists import (
    ListsError,
    add_entry,
    delete_list,
    entry_from_dict,
    get_list,
    last_list,
    list_names,
    load,
    remove_entry,
    save,
)
from kotoba.model import Entry, LookupResult
from kotoba.render import render_error, render_text

EXIT_OK = 0
EXIT_NO_RESULTS = 1
EXIT_UPSTREAM_ERROR = 2
EXIT_USAGE = 64

Source = str

ALIASES = {
    "jp": "jisho",
    "jisho": "jisho",
    "en": "wordnet",
    "wordnet": "wordnet",
}

_KANA = range(0x3040, 0x3100)
_KANJI = range(0x4E00, 0xA000)


def _looks_japanese(text: str) -> bool:
    return any(ord(ch) in _KANA or ord(ch) in _KANJI for ch in text)


def _with_source(argv: list[str]) -> list[str]:
    for index, token in enumerate(argv):
        if token in ("-h", "--help"):
            return argv
        if token == "list" or token.startswith("list-"):
            return argv
        if not token.startswith("-"):
            if token in ALIASES:
                return argv
            picked = "jp" if _looks_japanese(token) else "en"
            return argv[:index] + [picked] + argv[index:]
    return argv


EPILOG = """\
examples:
  kotoba 猫                  open the pager for a Japanese word
  kotoba love -p             WordNet, plain text to stdout
  kotoba 猫 --json --limit 3 structured output for scripts
  kotoba jp --selection -p   look up the primary selection
  kotoba list add 猫 -l jp   save first Jisho result to a list

A bare query picks jp for kana/kanji and en otherwise.

exit codes: 0 results, 1 no results, 2 upstream error, 64 usage error"""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        sys.stderr.write(f"{self.prog}: error: {message}\n")
        raise SystemExit(EXIT_USAGE)


def _version() -> str:
    try:
        from importlib.metadata import version

        return version("kotoba")
    except Exception:
        return "0.1.0"


def _lookup(source: Source, query: str, limit: int | None):
    if source == "jisho":
        from kotoba import jisho

        return jisho.fetch(query, limit=limit or 12)

    from kotoba import wordnet

    return wordnet.fetch(query, limit=limit)


def _as_json(result: LookupResult) -> str:
    return json.dumps(
        {
            "query": result.query,
            "source": result.source,
            "url": result.url,
            "entries": [
                {
                    "headword": entry.headword,
                    "reading": entry.reading,
                    "tags": list(entry.tags),
                    "senses": [{"pos": list(sense.pos), "glosses": list(sense.glosses)} for sense in entry.senses],
                }
                for entry in result.entries
            ],
        },
        ensure_ascii=False,
        indent=2,
    )


def _print_result(source: Source, query: str, limit: int | None, as_json: bool) -> int:
    if not query:
        print("kotoba: empty query", file=sys.stderr)
        return EXIT_USAGE

    try:
        result = _lookup(source, query, limit)
    except Exception as exc:
        sys.stderr.write(render_error(query, str(exc)))
        return EXIT_UPSTREAM_ERROR

    if not result.entries:
        sys.stderr.write(render_error(query, "no results"))
        return EXIT_NO_RESULTS

    if as_json:
        print(_as_json(result))
    else:
        print(render_text(result), end="")
    return EXIT_OK


def _entry_with_meta(entry: Entry, result: LookupResult) -> Entry:
    from dataclasses import replace

    return replace(entry, url=result.url or "", source=result.source)


def _cmd_list_add(args) -> int:
    source = ALIASES.get(args.source, "jisho")
    if not args.query:
        sys.stderr.write("kotoba list add: missing QUERY\n")
        return EXIT_USAGE
    try:
        result = _lookup(source, args.query, args.limit)
    except Exception as exc:
        sys.stderr.write(render_error(args.query, str(exc)))
        return EXIT_UPSTREAM_ERROR

    if not result.entries:
        sys.stderr.write(render_error(args.query, "no results"))
        return EXIT_NO_RESULTS

    entry = _entry_with_meta(result.entries[0], result)
    try:
        state = load()
        state, added = add_entry(args.list, entry, state=state)
        save(state)
    except ListsError as exc:
        sys.stderr.write(f"kotoba: {exc}\n")
        return EXIT_UPSTREAM_ERROR

    if added:
        print(f"added {entry.headword} to {args.list}")
        return EXIT_OK
    print(f"already in {args.list}")
    return EXIT_NO_RESULTS


def _cmd_list_rm(args) -> int:
    try:
        state = load()
        state, removed = remove_entry(args.list, args.headword, args.reading, state=state)
        save(state)
    except ListsError as exc:
        sys.stderr.write(f"kotoba: {exc}\n")
        return EXIT_UPSTREAM_ERROR

    if removed:
        print(f"removed {args.headword} from {args.list}")
        return EXIT_OK
    print(f"{args.headword} not found in {args.list}")
    return EXIT_NO_RESULTS


def _cmd_list_show(args) -> int:
    try:
        state = load()
    except ListsError as exc:
        sys.stderr.write(f"kotoba: {exc}\n")
        return EXIT_UPSTREAM_ERROR

    if args.list:
        data = get_list(args.list, state=state)
        if data is None:
            sys.stderr.write(f"kotoba: list '{args.list}' not found\n")
            return EXIT_NO_RESULTS
        print(f"{args.list} ({len(data['entries'])} entries)")
        for item in data["entries"]:
            reading = item.get("reading") or ""
            head = item["headword"]
            print(f"  {head}【{reading}】" if reading else f"  {head}")
        return EXIT_OK

    names = list_names(state=state)
    if not names:
        print("no lists")
        return EXIT_OK
    print("lists:")
    for name in names:
        data = get_list(name, state=state)
        assert data is not None
        count = len(data["entries"])
        marker = " *" if last_list(state=state) == name else ""
        print(f"  {name}: {count} entries{marker}")
    return EXIT_OK


def _cmd_list_rm_list(args) -> int:
    if not args.yes:
        sys.stderr.write("kotoba list rm-list: use --yes to confirm\n")
        return EXIT_USAGE
    try:
        state = load()
        state, deleted = delete_list(args.list, state=state)
        save(state)
    except ListsError as exc:
        sys.stderr.write(f"kotoba: {exc}\n")
        return EXIT_UPSTREAM_ERROR

    if deleted:
        print(f"deleted list {args.list}")
        return EXIT_OK
    sys.stderr.write(f"kotoba: list '{args.list}' not found\n")
    return EXIT_NO_RESULTS


def _cmd_list_export(args) -> int:
    try:
        state = load()
    except ListsError as exc:
        sys.stderr.write(f"kotoba: {exc}\n")
        return EXIT_UPSTREAM_ERROR

    data = get_list(args.list, state=state)
    if data is None:
        sys.stderr.write(f"kotoba: list '{args.list}' not found\n")
        return EXIT_NO_RESULTS

    from kotoba.lists import entry_from_dict

    entries = [entry_from_dict(item) for item in data["entries"]]
    output_dir = Path(args.output) if args.output else None
    try:
        paths = export_list(entries, args.list, args.format, output_dir=output_dir)
    except ImportError as exc:
        sys.stderr.write(f"kotoba: {exc}\n")
        return EXIT_UPSTREAM_ERROR
    except Exception as exc:
        sys.stderr.write(f"kotoba: export failed: {exc}\n")
        return EXIT_UPSTREAM_ERROR

    for path in paths:
        print(path)
    return EXIT_OK


def _build_list_parser(sub) -> argparse.ArgumentParser:
    p = sub.add_parser("list", help="manage saved word lists", description="Manage saved word lists.")
    sub_list = p.add_subparsers(dest="list_command", required=True)

    add = sub_list.add_parser("add", help="add the first lookup result to a list")
    add.add_argument("query", help="word to look up")
    add.add_argument("-l", "--list", default="default", help="target list (default: default)")
    add.add_argument("--source", choices=["jp", "en"], default="jp", help="lookup source")
    add.add_argument("--limit", type=int, default=None, metavar="N", help="maximum results to consider")

    rm = sub_list.add_parser("rm", help="remove an entry from a list")
    rm.add_argument("headword", help="headword to remove")
    rm.add_argument("-l", "--list", default="default", help="list name")
    rm.add_argument("--reading", default=None, help="reading to match")

    show = sub_list.add_parser("show", help="show lists or entries")
    show.add_argument("list", nargs="?", default=None, help="list name; omit for all lists")

    rm_list = sub_list.add_parser("rm-list", help="delete a list")
    rm_list.add_argument("list", help="list name")
    rm_list.add_argument("--yes", action="store_true", help="confirm deletion")

    export = sub_list.add_parser("export", help="export a list to Anki")
    export.add_argument("list", help="list name")
    export.add_argument("-f", "--format", choices=["apkg", "tsv", "both"], default="apkg", help="export format")
    export.add_argument("-o", "--output", default=None, help="output directory")

    return p


def _build_parser() -> _Parser:
    parser = _Parser(
        prog="kotoba",
        description="Dictionary pager for Jisho and WordNet",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"kotoba {_version()}")
    sub = parser.add_subparsers(dest="command", required=True, metavar="{jp,en,list}")
    for name, label in (("jp", "Jisho"), ("en", "WordNet")):
        p = sub.add_parser(name, help=f"search {label}", description=f"Search {label}.")
        p.add_argument("query", nargs="?", default="", help="word to look up (omit to type in the TUI)")
        p.add_argument("--selection", action="store_true", help="use primary selection, then clipboard, as the query")
        p.add_argument("-p", "--print", action="store_true", dest="print_only", help="plain text output, no TUI")
        p.add_argument("--json", action="store_true", dest="as_json", help="JSON output")
        p.add_argument("--limit", type=int, default=None, metavar="N", help="maximum entries to show (Jisho default 12)")

    _build_list_parser(sub)
    return parser


def _parse_args(argv: list[str] | None = None):
    raw = list(sys.argv[1:] if argv is None else argv)
    if not raw:
        _build_parser().print_help(sys.stderr)
        raise SystemExit(EXIT_USAGE)

    if raw[0].startswith("-") and raw[0] not in ("-h", "--help", "--version"):
        sys.stderr.write(f"kotoba: error: unrecognized argument: {raw[0]}\n")
        raise SystemExit(EXIT_USAGE)

    argv = _with_source(raw)
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if args.command == "list":
        if args.list_command == "add":
            return _cmd_list_add(args)
        if args.list_command == "rm":
            return _cmd_list_rm(args)
        if args.list_command == "show":
            return _cmd_list_show(args)
        if args.list_command == "rm-list":
            return _cmd_list_rm_list(args)
        if args.list_command == "export":
            return _cmd_list_export(args)
        return EXIT_USAGE

    from kotoba import selection

    limit = args.limit if args.limit and args.limit > 0 else None
    query = selection.initial_query(args.query or None, use_selection=args.selection)
    source = ALIASES[args.command]
    if not (args.print_only or args.as_json) and sys.stdout.isatty():
        from kotoba.app import run_app

        run_app(source, query)  # type: ignore[arg-type]
        return EXIT_OK
    return _print_result(source, query, limit, args.as_json)


if __name__ == "__main__":
    sys.exit(main())
