from __future__ import annotations

import argparse
import json
import sys

from kotoba.render import render_error, render_text
from kotoba.selection import initial_query


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
        if not token.startswith("-"):
            if token in ALIASES:
                return argv
            picked = "jp" if _looks_japanese(token) else "en"
            return argv[:index] + [picked] + argv[index:]
    return argv


def _parse_args(argv: list[str] | None = None) -> tuple[str, bool, bool, str, int | None, bool]:
    argv = _with_source(list(sys.argv[1:] if argv is None else argv))
    parser = argparse.ArgumentParser(
        prog="kotoba",
        description="Dictionary pager for Jisho and WordNet",
        epilog="A bare query picks jp for kana/kanji and en otherwise.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name, label in (("jp", "Jisho"), ("en", "WordNet")):
        p = sub.add_parser(name, help=f"search {label}")
        p.add_argument("query", nargs="?", default="", help="word to look up")
        p.add_argument("--selection", action="store_true", help="use primary selection, then clipboard, as the query")
        p.add_argument("-p", "--print", action="store_true", dest="print_only", help="plain text output, no TUI")
        p.add_argument("--json", action="store_true", dest="as_json", help="JSON output")
        p.add_argument("--limit", type=int, default=None, help="maximum entries to show")

    args = parser.parse_args(argv)
    limit = args.limit if args.limit and args.limit > 0 else None
    query = initial_query(args.query or None, use_selection=args.selection)
    return ALIASES[args.command], args.selection, args.print_only, query, limit, args.as_json


def _lookup(source: Source, query: str, limit: int | None):
    if source == "jisho":
        from kotoba import jisho

        return jisho.fetch(query, limit=limit or 12)

    from kotoba import wordnet

    return wordnet.fetch(query, limit=limit)


def _as_json(result) -> str:
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


def main(argv: list[str] | None = None) -> int:
    source, from_selection, print_only, query, limit, as_json = _parse_args(argv)
    if not (print_only or as_json) and sys.stdout.isatty():
        from kotoba.app import run_app

        run_app(source, query)
        return EXIT_OK
    return _print_result(source, query, limit, as_json)


if __name__ == "__main__":
    sys.exit(main())
