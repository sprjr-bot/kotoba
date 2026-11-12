from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from kotoba.config import ConfigError, ConfigMode
from kotoba.datasets import clear_download_cache, dataset_attribution_block, known_ids
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
from kotoba.localdict import installed as localdict_installed
from kotoba.lookup import (
    LookupError as LookupModeError,
    install_datasets,
    kanji as lookup_kanji,
    local_status,
    lookup as resolve_lookup,
    remove_dataset,
    reindex as reindex_datasets,
    update as update_datasets,
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
        if token in ("jp", "en", "list", "dict", "kanji") or token.startswith("list-"):
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
  kotoba dict install --all  download and index all dictionary datasets
  kotoba kanji 猫            show kanji details for 猫

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
    from kotoba import langs

    return langs.get(source).api_search(query, limit=limit)


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


def _print_result(source: Source, query: str, limit: int | None, as_json: bool, offline: bool = False) -> int:
    if not query:
        print("kotoba: empty query", file=sys.stderr)
        return EXIT_USAGE

    # --offline with no local data: hint, optionally offer download, then continue with API if declined
    if offline and not localdict_installed():
        sys.stderr.write("local dictionary not installed (kotoba dict install)\n")
        if sys.stdin.isatty():
            sys.stderr.write("download now? [y/N] ")
            sys.stderr.flush()
            try:
                answer = sys.stdin.readline().strip().lower()
            except (OSError, KeyboardInterrupt):
                answer = "n"
            if answer in ("y", "yes"):
                try:
                    install_datasets([], all_=True)
                except Exception as exc:
                    sys.stderr.write(f"kotoba: download failed: {exc}\n")
            else:
                sys.stderr.write("continuing with API lookup\n")
        # fall through to API if declined or download failed

    try:
        result = resolve_lookup(source, query, limit, offline=offline)
    except LookupModeError as exc:
        sys.stderr.write(render_error(query, str(exc)))
        return EXIT_NO_RESULTS
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
        result = resolve_lookup(source, args.query, args.limit, offline=getattr(args, "offline", False))
    except LookupModeError as exc:
        sys.stderr.write(render_error(args.query, str(exc)))
        return EXIT_NO_RESULTS
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


def _build_dict_parser(sub) -> argparse.ArgumentParser:
    valid = ", ".join(_VALID_DATASET_NAMES)
    p = sub.add_parser("dict", help="manage local dictionary datasets", description="Manage local dictionary datasets.")
    sub_dict = p.add_subparsers(dest="dict_command", required=True)

    status = sub_dict.add_parser("status", help="show installed datasets and licences")
    status.add_argument("--json", action="store_true", dest="as_json", help="JSON output")

    install = sub_dict.add_parser("install", help="download and index datasets")
    install.add_argument("name", nargs="*", help=f"dataset names: {valid}")
    install.add_argument("--all", action="store_true", dest="all_datasets", help="install all default datasets")
    install.add_argument("--lang", default=None, help="install default datasets for a language")
    install.add_argument("--latest", action="store_true", help="bypass pinned hash verification")
    install.add_argument(
        "--accept-new-dump",
        action="store_true",
        dest="accept_new_dump",
        help="accept an archive whose hash differs from the pinned one",
    )
    install.add_argument(
        "--purge-cache",
        action="store_true",
        dest="purge_cache",
        help="clear the download cache after a successful install",
    )

    remove = sub_dict.add_parser("remove", help="remove an installed dataset")
    remove.add_argument("name", choices=_VALID_DATASET_NAMES, help="dataset name")

    cache = sub_dict.add_parser("cache", help="manage the download cache")
    sub_cache = cache.add_subparsers(dest="cache_command", required=True)
    sub_cache.add_parser("clear", help="delete cached downloads")

    sub_dict.add_parser("update", help="re-resolve and reinstall installed datasets")
    sub_dict.add_parser("reindex", help="rebuild indices from stored archives")
    notice = sub_dict.add_parser("notice", help="print attribution notices for installed datasets")
    notice.add_argument("--json", action="store_true", dest="as_json", help="JSON output")

    return p


def _build_parser() -> _Parser:
    parser = _Parser(
        prog="kotoba",
        description="Dictionary pager for Jisho and WordNet",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"kotoba {_version()}")
    parser.add_argument("--offline", action="store_true", help="force local-only lookup")
    sub = parser.add_subparsers(dest="command", required=True, metavar="{jp,en,list,dict,kanji}")
    for name, label in (("jp", "Jisho"), ("en", "WordNet")):
        p = sub.add_parser(name, help=f"search {label}", description=f"Search {label}.")
        p.add_argument("query", nargs="?", default="", help="word to look up (omit to type in the TUI)")
        p.add_argument("--selection", action="store_true", help="use primary selection, then clipboard, as the query")
        p.add_argument("-p", "--print", action="store_true", dest="print_only", help="plain text output, no TUI")
        p.add_argument("--json", action="store_true", dest="as_json", help="JSON output")
        p.add_argument("--limit", type=int, default=None, metavar="N", help="maximum entries to show (Jisho default 12)")
        p.add_argument(
            "--offline",
            action="store_true",
            default=argparse.SUPPRESS,
            help="force local-only lookup",
        )

    _build_list_parser(sub)
    _build_dict_parser(sub)

    kanji = sub.add_parser("kanji", help="show kanji details")
    kanji.add_argument("literal", nargs=1, help="kanji character")

    return parser


def _parse_args(argv: list[str] | None = None):
    raw = list(sys.argv[1:] if argv is None else argv)
    if not raw:
        _build_parser().print_help(sys.stderr)
        raise SystemExit(EXIT_USAGE)

    if raw[0].startswith("-") and raw[0] not in ("-h", "--help", "--version", "--offline"):
        sys.stderr.write(f"kotoba: error: unrecognized argument: {raw[0]}\n")
        raise SystemExit(EXIT_USAGE)

    argv = _with_source(raw)
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args


def _cmd_dict_status(args) -> int:
    rows = local_status()
    data_rows = rows[:-1] if rows and rows[-1]["name"] == "total" else rows
    total = rows[-1] if rows and rows[-1]["name"] == "total" else None
    if args.as_json:
        total_fields = {k: v for k, v in (total or {}).items() if k in ("archive_bytes", "index_bytes", "size")}
        print(json.dumps(
            {
                "datasets": data_rows,
                "total": total_fields or {"archive_bytes": 0, "index_bytes": 0, "size": 0},
            },
            ensure_ascii=False,
            indent=2,
        ))
        return EXIT_OK
    if not data_rows:
        print("no datasets installed")
        return EXIT_OK
    print(f"{'dataset':<20} {'version':<20} {'size':>10} {'licence'}")
    data_rows = rows[:-1] if rows and rows[-1]["name"] == "total" else rows
    total = rows[-1] if rows and rows[-1]["name"] == "total" else None
    for row in data_rows:
        size = row.get("size", 0)
        size_mb = f"{size / (1024 * 1024):.2f} MB"
        print(f"{row['name']:<20} {row['version']:<20} {size_mb:>10} {row['license']}")
    if total:
        size_mb = f"{total['size'] / (1024 * 1024):.2f} MB"
        print(f"{'total':<20} {'':<20} {size_mb:>10}")
    print()
    print("Dictionary data from EDRDG (JMdict/KANJIDIC2/Kradfile/Radkfile), https://www.edrdg.org/")
    print("Licensed under CC BY-SA 4.0, https://creativecommons.org/licenses/by-sa/4.0/")
    print("WordNet 3.0 © Princeton University; WordNet licence applies.")
    print("Local SQLite indices are a derivative of CC BY-SA 4.0 data; sharing them carries the share-alike obligation.")
    return EXIT_OK


_VALID_DATASET_NAMES = known_ids()


def _dataset_suggestions(name: str, names: list[str], n: int = 3) -> list[str]:
    import difflib

    return difflib.get_close_matches(name, names, n=n, cutoff=0.4)


def _cmd_dict_install(args) -> int:
    if args.all_datasets:
        targets = []
    elif args.lang:
        targets = []
    elif args.name:
        targets = args.name
    else:
        sys.stderr.write("kotoba dict install: specify datasets or --all or --lang\n")
        return EXIT_USAGE

    invalid = [n for n in targets if n not in _VALID_DATASET_NAMES]
    if invalid:
        msg = f"kotoba dict install: unknown dataset: {invalid[0]}"
        suggestions = _dataset_suggestions(invalid[0], _VALID_DATASET_NAMES)
        if suggestions:
            msg += f"\n  did you mean: {', '.join(suggestions)}"
        sys.stderr.write(f"{msg}\n  valid datasets: {', '.join(_VALID_DATASET_NAMES)}\n")
        return EXIT_USAGE

    try:
        metas = install_datasets(
            targets,
            all_=args.all_datasets,
            lang=args.lang,
            latest=args.latest,
            accept_new_dump=args.accept_new_dump,
            purge_cache=args.purge_cache,
        )
    except Exception as exc:
        sys.stderr.write(f"kotoba: install failed: {exc}\n")
        return EXIT_UPSTREAM_ERROR
    for meta in metas:
        print(f"installed {meta['name']} {meta['version']} ({meta['size']} bytes)")
    return EXIT_OK


def _cmd_dict_notice(args) -> int:
    block = dataset_attribution_block()
    if args.as_json:
        print(json.dumps(block, ensure_ascii=False, indent=2))
        return EXIT_OK
    if not block["datasets"]:
        print("no datasets installed")
        return EXIT_OK
    for row in block["datasets"]:
        print(f"{row['name']} — {row['license']}")
        print(f"  {row['attribution']}")
        print(f"  {row['source_url']}")
        if row.get("notice"):
            print(f"  {row['notice']}")
    if block.get("shared_notice"):
        print()
        print(block["shared_notice"])
    return EXIT_OK


def _cmd_dict_cache_clear() -> int:
    files, size = clear_download_cache()
    if not files:
        print("download cache empty")
        return EXIT_OK
    print(f"cleared {files} cached archive{'s' if files != 1 else ''} ({size} bytes)")
    return EXIT_OK


def _cmd_dict_remove(args) -> int:
    if remove_dataset(args.name):
        print(f"removed {args.name}")
        return EXIT_OK
    sys.stderr.write(f"kotoba: dataset '{args.name}' not installed\n")
    return EXIT_NO_RESULTS


def _cmd_dict_update() -> int:
    try:
        metas = update_datasets()
    except Exception as exc:
        sys.stderr.write(f"kotoba: update failed: {exc}\n")
        return EXIT_UPSTREAM_ERROR
    for meta in metas:
        print(f"updated {meta['name']} {meta['version']}")
    if not metas:
        print("no datasets installed")
    return EXIT_OK


def _cmd_dict_reindex() -> int:
    try:
        metas = reindex_datasets()
    except Exception as exc:
        sys.stderr.write(f"kotoba: reindex failed: {exc}\n")
        return EXIT_UPSTREAM_ERROR
    for meta in metas:
        print(f"reindexed {meta['name']} {meta['version']}")
    if not metas:
        print("no datasets installed")
    return EXIT_OK


def _cmd_kanji(args) -> int:
    if not args.literal or not args.literal[0]:
        sys.stderr.write("kotoba kanji: missing character\n")
        return EXIT_USAGE
    char = args.literal[0]
    info = lookup_kanji(char)
    if info is None:
        sys.stderr.write(f"kotoba: no kanji data for '{char}' (kotoba dict install kanjidic2-en)\n")
        return EXIT_NO_RESULTS
    print(f"{info['literal']}  strokes: {info['stroke_count']}  grade: {info['grade'] or '-'}  JLPT: {info['jlpt'] or '-'}")
    if info['on_readings']:
        print(f"on:  {', '.join(info['on_readings'])}")
    if info['kun_readings']:
        print(f"kun: {', '.join(info['kun_readings'])}")
    if info['meanings']:
        print(f"meanings: {', '.join(info['meanings'])}")
    if info['radicals']:
        print(f"radicals: {', '.join(map(str, info['radicals']))}")
    if info['components']:
        print(f"components: {', '.join(info['components'])}")
    return EXIT_OK


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

    if args.command == "dict":
        if args.dict_command == "status":
            return _cmd_dict_status(args)
        if args.dict_command == "install":
            return _cmd_dict_install(args)
        if args.dict_command == "remove":
            return _cmd_dict_remove(args)
        if args.dict_command == "update":
            return _cmd_dict_update()
        if args.dict_command == "reindex":
            return _cmd_dict_reindex()
        if args.dict_command == "notice":
            return _cmd_dict_notice(args)
        if args.dict_command == "cache":
            if args.cache_command == "clear":
                return _cmd_dict_cache_clear()
            return EXIT_USAGE
        return EXIT_USAGE

    if args.command == "kanji":
        return _cmd_kanji(args)

    from kotoba import selection

    limit = args.limit if args.limit and args.limit > 0 else None
    query = selection.initial_query(args.query or None, use_selection=args.selection)
    source = ALIASES[args.command]
    if not (args.print_only or args.as_json) and sys.stdout.isatty():
        from kotoba.app import run_app

        run_app(source, query, offline=args.offline)
        return EXIT_OK
    return _print_result(source, query, limit, args.as_json, offline=args.offline)


if __name__ == "__main__":
    sys.exit(main())
