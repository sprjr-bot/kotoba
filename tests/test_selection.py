from kotoba.selection import initial_query


def test_explicit_arg_wins():
    assert initial_query("  猫  ") == "猫"


def test_no_selection_returns_empty():
    assert initial_query(None, use_selection=False) == ""


def test_selection_primary_then_clipboard(monkeypatch):
    calls = []

    def fake_which(cmd):
        return "/usr/bin/wl-paste"

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if "--primary" in cmd:
            return type("R", (), {"returncode": 1, "stdout": ""})()
        return type("R", (), {"returncode": 0, "stdout": "clipboard text\n"})()

    monkeypatch.setattr("kotoba.selection.shutil.which", fake_which)
    monkeypatch.setattr("kotoba.selection.subprocess.run", fake_run)
    assert initial_query(None, use_selection=True) == "clipboard text"
    assert ["wl-paste", "--primary"] in calls


def test_missing_wl_paste_returns_empty(monkeypatch):
    monkeypatch.setattr("kotoba.selection.shutil.which", lambda cmd: None)
    assert initial_query(None, use_selection=True) == ""


def test_cleans_whitespace_and_truncates():
    assert initial_query("a\n\tb   c") == "a b c"
    assert initial_query("x" * 100) == "x" * 64
