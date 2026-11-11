import sys
from unittest import mock

import pytest

from kotoba.cli import EXIT_NO_RESULTS, EXIT_OK, EXIT_UPSTREAM_ERROR, EXIT_USAGE, main


def test_cli_print_jisho_no_results(monkeypatch):
    def fetch(query, **kwargs):
        from kotoba.model import LookupResult
        return LookupResult(query=query, source="jisho", entries=())

    monkeypatch.setattr("kotoba.jisho.fetch", fetch)
    assert main(["jp", "--print", "xyz"]) == EXIT_NO_RESULTS


def test_cli_print_jisho_result(capsys, monkeypatch):
    from kotoba.model import Entry, LookupResult, Sense

    def fetch(query, **kwargs):
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
    def fetch(query, **kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr("kotoba.jisho.fetch", fetch)
    assert main(["jp", "--print", "猫"]) == EXIT_UPSTREAM_ERROR
    assert "network down" in capsys.readouterr().err


def test_cli_print_in_pipe(capsys, monkeypatch):
    from kotoba.model import Entry, LookupResult, Sense

    def fetch(query, **kwargs):
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

    def fetch(query, **kwargs):
        captured["query"] = query
        return LookupResult(query=query, source="jisho", entries=())

    monkeypatch.setattr("kotoba.jisho.fetch", fetch)
    monkeypatch.setattr("kotoba.selection.initial_query", lambda arg=None, *, use_selection=False: "猫")
    assert main(["jp", "--selection", "--print"]) == EXIT_NO_RESULTS
    assert captured["query"] == "猫"


def test_bare_query_autodetects_japanese(monkeypatch):
    from kotoba.model import LookupResult

    seen = {}

    def fetch(query, **kwargs):
        seen["query"] = query
        return LookupResult(query=query, source="jisho", entries=())

    monkeypatch.setattr("kotoba.jisho.fetch", fetch)
    assert main(["猫", "--print"]) == EXIT_NO_RESULTS
    assert seen["query"] == "猫"


def test_bare_query_autodetects_english(monkeypatch):
    from kotoba.model import LookupResult

    seen = {}

    def fetch(query, **kwargs):
        seen["query"] = query
        return LookupResult(query=query, source="wordnet", entries=())

    monkeypatch.setattr("kotoba.wordnet.fetch", fetch)
    assert main(["love", "--print"]) == EXIT_NO_RESULTS
    assert seen["query"] == "love"


def test_json_output(capsys, monkeypatch):
    from kotoba.model import Entry, LookupResult, Sense

    def fetch(query, **kwargs):
        return LookupResult(
            query=query,
            source="jisho",
            entries=(Entry(headword="猫", reading="ねこ", senses=(Sense(pos=("Noun",), glosses=("cat",)),)),),
            url="https://jisho.org/search/%E7%8C%AB",
        )

    monkeypatch.setattr("kotoba.jisho.fetch", fetch)
    assert main(["jp", "--json", "猫"]) == EXIT_OK
    import json

    payload = json.loads(capsys.readouterr().out)
    assert payload["entries"][0]["headword"] == "猫"
    assert payload["entries"][0]["senses"][0]["glosses"] == ["cat"]


def test_limit_reaches_upstream(monkeypatch):
    from kotoba.model import LookupResult

    seen = {}

    def fetch(query, **kwargs):
        seen.update(kwargs)
        return LookupResult(query=query, source="jisho", entries=())

    monkeypatch.setattr("kotoba.jisho.fetch", fetch)
    assert main(["jp", "--print", "--limit", "3", "猫"]) == EXIT_NO_RESULTS
    assert seen["limit"] == 3


def test_empty_query_returns_usage(capsys):
    assert main(["jp", "--print"]) == EXIT_USAGE
    assert "empty query" in capsys.readouterr().err


def test_help_exits_zero(capsys):
    import pytest

    with pytest.raises(SystemExit) as exc:
        main(["-h"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "kotoba 猫" in out
    assert "exit codes" in out


def test_subcommand_help(capsys):
    import pytest

    with pytest.raises(SystemExit) as exc:
        main(["jp", "-h"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "--selection" in out and "--limit" in out


def test_version_flag(capsys):
    import pytest

    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.startswith("kotoba ")


def test_no_args_is_usage_error(capsys):
    import pytest

    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == EXIT_USAGE
    assert "usage:" in capsys.readouterr().err


def test_unknown_flag_is_usage_error(capsys):
    import pytest

    with pytest.raises(SystemExit) as exc:
        main(["--nope"])
    assert exc.value.code == EXIT_USAGE
    assert "unrecognized" in capsys.readouterr().err


def test_list_add_saves_entry(monkeypatch, tmp_path):
    from kotoba.model import Entry, LookupResult, Sense

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    def fetch(query, **kwargs):
        return LookupResult(
            query=query,
            source="jisho",
            entries=(Entry(headword="猫", reading="ねこ", senses=(Sense(pos=("Noun",), glosses=("cat",)),)),),
            url="https://jisho.org/search/%E7%8C%AB",
        )

    monkeypatch.setattr("kotoba.jisho.fetch", fetch)
    assert main(["list", "add", "猫", "--source", "jp"]) == EXIT_OK
    data = (tmp_path / "kotoba" / "lists.json").read_text(encoding="utf-8")
    assert "猫" in data


def test_list_add_already_present(monkeypatch, tmp_path):
    from kotoba.model import Entry, LookupResult, Sense

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    def fetch(query, **kwargs):
        return LookupResult(
            query=query,
            source="jisho",
            entries=(Entry(headword="猫", reading="ねこ", senses=(Sense(pos=("Noun",), glosses=("cat",)),)),),
        )

    monkeypatch.setattr("kotoba.jisho.fetch", fetch)
    main(["list", "add", "猫", "--source", "jp"])
    assert main(["list", "add", "猫", "--source", "jp"]) == EXIT_NO_RESULTS


def test_list_add_not_found(monkeypatch, tmp_path):
    from kotoba.model import LookupResult

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr("kotoba.jisho.fetch", lambda q, **kw: LookupResult(query=q, source="jisho", entries=()))
    assert main(["list", "add", "xyz", "--source", "jp"]) == EXIT_NO_RESULTS


def test_list_add_upstream_error(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr("kotoba.jisho.fetch", lambda q, **kw: (_ for _ in ()).throw(RuntimeError("down")))
    assert main(["list", "add", "猫", "--source", "jp"]) == EXIT_UPSTREAM_ERROR


def test_list_rm_without_reading(monkeypatch, tmp_path):
    from kotoba.lists import add_entry, save
    from kotoba.model import Entry, Sense

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    state, _ = add_entry("default", Entry(headword="猫", reading="ねこ", senses=(Sense(pos=("Noun",), glosses=("cat",)),)))
    save(state)
    assert main(["list", "rm", "猫"]) == EXIT_OK
    assert main(["list", "rm", "猫"]) == EXIT_NO_RESULTS


def test_list_show(monkeypatch, tmp_path):
    from kotoba.lists import add_entry, save
    from kotoba.model import Entry, Sense

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    state, _ = add_entry("default", Entry(headword="猫", reading="ねこ", senses=(Sense(pos=("Noun",), glosses=("cat",)),)))
    save(state)
    assert main(["list", "show"]) == EXIT_OK


def test_list_export(monkeypatch, tmp_path):
    from kotoba.lists import add_entry, save
    from kotoba.model import Entry, Sense

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    state, _ = add_entry("default", Entry(headword="猫", reading="ねこ", senses=(Sense(pos=("Noun",), glosses=("cat",)),)))
    save(state)
    assert main(["list", "export", "default", "-f", "tsv"]) == EXIT_OK


def test_list_rm_list_requires_yes(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert main(["list", "rm-list", "default"]) == EXIT_USAGE


def test_list_help_shows_subcommands(capsys):
    import pytest

    with pytest.raises(SystemExit) as exc:
        main(["list", "-h"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "add" in out and "export" in out and "show" in out
