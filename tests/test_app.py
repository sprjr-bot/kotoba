import os
import pytest
from textual.widgets import Input, Static

from kotoba.app import KotobaApp, QueryScreen, ResultsScreen


def _fake_fetch(monkeypatch, source, entries):
    from kotoba.model import LookupResult

    def fetch(query, limit=12):
        return LookupResult(query=query, source=source, entries=entries)

    if source == "jisho":
        monkeypatch.setattr("kotoba.jisho.fetch", fetch)
    else:
        monkeypatch.setattr("kotoba.wordnet.fetch", fetch)


@pytest.mark.asyncio
async def test_app_opens_query_screen_with_empty_query(monkeypatch):
    _fake_fetch(monkeypatch, "jisho", ())
    monkeypatch.setenv("XDG_CONFIG_HOME", "/tmp/kotoba-test-empty")
    import tempfile, shutil
    cfg = "/tmp/kotoba-test-empty/kotoba"
    shutil.rmtree(cfg, ignore_errors=True)
    os.makedirs(cfg, exist_ok=True)
    from kotoba.config import save, load
    c = load()
    c["onboarding_done"] = True
    save(c)
    app = KotobaApp("jisho", "")
    async with app.run_test() as pilot:
        assert isinstance(app.screen, QueryScreen)
        assert app.screen.query_one("#query", Input).value == ""


@pytest.mark.asyncio
async def test_app_submits_query_and_shows_results(monkeypatch):
    from kotoba.model import Entry, Sense

    _fake_fetch(monkeypatch, "jisho", (Entry(headword="猫", reading="ねこ", senses=(Sense(pos=("Noun",), glosses=("cat",)),)),))
    monkeypatch.setenv("XDG_CONFIG_HOME", "/tmp/kotoba-test-results")
    import shutil
    shutil.rmtree("/tmp/kotoba-test-results", ignore_errors=True)
    from kotoba.config import save, load
    c = load()
    c["onboarding_done"] = True
    save(c)
    app = KotobaApp("jisho", "")
    async with app.run_test() as pilot:
        input_widget = app.screen.query_one("#query", Input)
        input_widget.value = "猫"
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, ResultsScreen)
        results = app.screen.query_one("#results", Static)
        assert "猫" in str(results.render())


@pytest.mark.asyncio
async def test_esc_returns_to_query_preserving_text(monkeypatch):
    from kotoba.model import Entry, Sense

    _fake_fetch(monkeypatch, "jisho", (Entry(headword="猫", reading="ねこ", senses=(Sense(pos=("Noun",), glosses=("cat",)),)),))
    monkeypatch.setenv("XDG_CONFIG_HOME", "/tmp/kotoba-test-esc")
    import shutil
    shutil.rmtree("/tmp/kotoba-test-esc", ignore_errors=True)
    from kotoba.config import save, load
    c = load()
    c["onboarding_done"] = True
    save(c)
    app = KotobaApp("jisho", "猫")
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, ResultsScreen)
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, QueryScreen)
        assert app.screen.query_one("#query", Input).value == "猫"


@pytest.mark.asyncio
async def test_press_a_on_results_adds_to_default_list(monkeypatch, tmp_path):
    from kotoba.model import Entry, Sense

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    import shutil
    shutil.rmtree(str(tmp_path / "config" / "kotoba"), ignore_errors=True)
    from kotoba.config import save, load
    c = load()
    c["onboarding_done"] = True
    save(c)
    _fake_fetch(monkeypatch, "jisho", (Entry(headword="猫", reading="ねこ", senses=(Sense(pos=("Noun",), glosses=("cat",)),)),))
    app = KotobaApp("jisho", "猫")
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, ResultsScreen)
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()
        data = (tmp_path / "kotoba" / "lists.json").read_text(encoding="utf-8")
        assert "猫" in data

def _onboarded(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    from kotoba.config import load, save

    c = load()
    c["onboarding_done"] = True
    save(c)


@pytest.mark.asyncio
async def test_first_run_opens_onboarding(monkeypatch, tmp_path):
    from kotoba.app import OnboardingScreen

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    _fake_fetch(monkeypatch, "jisho", ())
    app = KotobaApp("jisho", "")
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, OnboardingScreen)


@pytest.mark.asyncio
async def test_settings_screen_opens_from_results(monkeypatch, tmp_path):
    from kotoba.app import SettingsScreen
    from kotoba.model import Entry, Sense

    _fake_fetch(monkeypatch, "jisho", (Entry(headword="猫", reading="ねこ", senses=(Sense(pos=("Noun",), glosses=("cat",)),)),))
    _onboarded(tmp_path, monkeypatch)
    app = KotobaApp("jisho", "猫")
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("s")
        await pilot.pause()
        assert isinstance(app.screen, SettingsScreen)


@pytest.mark.asyncio
async def test_kanji_panel_opens_from_results(monkeypatch, tmp_path):
    from kotoba.app import KanjiScreen
    from kotoba.model import Entry, Sense

    _fake_fetch(monkeypatch, "jisho", (Entry(headword="猫", reading="ねこ", senses=(Sense(pos=("Noun",), glosses=("cat",)),)),))
    _onboarded(tmp_path, monkeypatch)
    app = KotobaApp("jisho", "猫")
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("K")
        await pilot.pause()
        assert isinstance(app.screen, KanjiScreen)

