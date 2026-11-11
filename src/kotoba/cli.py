from __future__ import annotations

import argparse
import sys

from kotoba.model import LookupResult
from kotoba.render import render_error, render_text
from kotoba.selection import initial_query


EXIT_OK = 0
EXIT_NO_RESULTS = 1
EXIT_UPSTREAM_ERROR = 2
EXIT_USAGE = 64


Source = str


def _source(parser: argparse.ArgumentParser, value: str) -> str:
    if value in ("jp", "jisho"):
        return "jisho"
    if value in ("en", "wordnet"):
        return "wordnet"
    parser.error(f"unknown command: {value}")
    return ""


def _parse_args(argv: list[str] | None = None) -> tuple[str, bool, bool, str]:
    parser = argparse.ArgumentParser(prog="kotoba", description="Dictionary pager for Jisho and WordNet")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("jp", "en"):
        p = sub.add_parser(name, help=f"search {'Jisho' if name == 'jp' else 'WordNet'}")
        p.add_argument("query", nargs="?", default="", help="word to look up")
        p.add_argument("--selection", action="store_true", help="use clipboard/primary selection as query")
        p.add_argument("--print", action="store_true", dest="print_only", help="plain text output, no TUI")
    args = parser.parse_args(argv)
    source = _source(parser, args.command)
    from_selection = args.selection
    query = initial_query(args.query or None, use_selection=from_selection)
    return source, from_selection, args.print_only, query


def _print_result(source: Source, query: str) -> int:
    if source == "jisho":
        from kotoba import jisho

        try:
            result = jisho.fetch(query)
        except Exception as exc:
            print(render_error(query, str(exc)), file=sys.stderr)
            return EXIT_UPSTREAM_ERROR
    else:
        from kotoba import wordnet

        try:
            result = wordnet.fetch(query)
        except Exception as exc:
            print(render_error(query, str(exc)), file=sys.stderr)
            return EXIT_UPSTREAM_ERROR

    if not result.entries:
        print(render_error(query, "no results"), file=sys.stderr)
        return EXIT_NO_RESULTS
    print(render_text(result), end="")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    source, from_selection, print_only, query = _parse_args(argv)
    if not print_only and sys.stdout.isatty():
        from kotoba.app import run_app
        run_app(source, query)
        return EXIT_OK
    return _print_result(source, query)


if __name__ == "__main__":
    sys.exit(main())
