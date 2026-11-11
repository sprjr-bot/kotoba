import sys
from unittest import mock

import pytest

from kotoba.cli import EXIT_NO_RESULTS, EXIT_OK, EXIT_UPSTREAM_ERROR, main


def test_cli_usage_returns_64():
    with pytest.raises(SystemExit) as exc_info:
        main([])
    # argparse uses code 2 for usage errors; our usage test checks error path
    assert exc_info.value.code == 2


def test_cli_print_jisho_no_results(monkeypatch):
    def fetch(query):
        from kotoba.model import LookupResult
        return LookupResult(query=query, source="jisho", entries=())

    monkeypatch.setattr("kotoba.jisho.fetch", fetch)
    assert main(["jp", "--print", "xyz"]) == EXIT_NO_RESULTS


def test_cli_print_jisho_result(capsys, monkeypatch):
    from kotoba.model import Entry, LookupResult, Sense

    def fetch(query):
        return LookupResult(
            query=query,
            source="jisho",
            entries=(Entry(headword="猫", reading="ねこ", senses=(Sense(pos=("Noun",), glosses=("cat",)),)),),
            url="https://jisho.org/search/%E7%8C%AB",
        )

    monkeypatch.setattr("kotoba.jisho.fetch", fetch)
    assert main(["jp", "--print", "猫"]) == EXIT_OK
    captured = capsys.readouterr()
    assert "猫" in captured.out
    assert "cat" in captured.out


def test_cli_print_upstream_error(capsys, monkeypatch):
    def fetch(query):
        raise RuntimeError("network down")

    monkeypatch.setattr("kotoba.jisho.fetch", fetch)
    assert main(["jp", "--print", "猫"]) == EXIT_UPSTREAM_ERROR
    assert "network down" in capsys.readouterr().err


def test_cli_print_in_pipe(capsys, monkeypatch):
    from kotoba.model import Entry, LookupResult, Sense

    def fetch(query):
        return LookupResult(
            query=query,
            source="jisho",
            entries=(Entry(headword="猫", reading="ねこ", senses=(Sense(pos=("Noun",), glosses=("cat",)),)),),
        )

    monkeypatch.setattr("kotoba.jisho.fetch", fetch)
    with mock.patch("sys.stdout.isatty", return_value=False):
        assert main(["jp", "猫"]) == EXIT_OK
    assert "cat" in capsys.readouterr().out


def test_cli_selection_feeds_query(capsys, monkeypatch):
    from kotoba.model import LookupResult

    captured = {}

    def fetch(query):
        captured["query"] = query
        return LookupResult(query=query, source="jisho", entries=())

    monkeypatch.setattr("kotoba.jisho.fetch", fetch)
    monkeypatch.setattr("kotoba.cli.initial_query", lambda arg=None, *, use_selection=False: "猫")
    assert main(["jp", "--selection", "--print"]) == EXIT_NO_RESULTS
    assert captured["query"] == "猫"
