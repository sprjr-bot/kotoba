from __future__ import annotations

import shutil
import subprocess
import time
from typing import Literal

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Input, Static
import threading

from kotoba.config import ask_at_startup, load as load_config, mode as config_mode, onboarding_done, save as save_config, set_mode
from kotoba.export import export_list
from kotoba.lists import add_entry, delete_list, entry_from_dict, get_list, last_list, list_names, load, remove_entry, save
from kotoba.localdict import installed as localdict_installed
from kotoba.lookup import install_datasets, kanji as lookup_kanji, local_status, lookup as resolve_lookup, remove_dataset
from kotoba.model import Entry, LookupResult
from kotoba.render import render_error, render_text

Source = Literal["jisho", "wordnet"]


def _fetch(source: Source, query: str, *, offline: bool = False) -> LookupResult:
    return resolve_lookup(source, query, None, offline=offline)


class QueryScreen(Screen):
    BINDINGS = [
        Binding("ctrl+c", "quit", "quit", show=False),
        Binding("escape", "quit", "quit", show=False),
        Binding("l", "lists", "lists", show=False),
        Binding("s", "settings", "settings", show=False),
        Binding("d", "data", "data & licences", show=False),
    ]

    CSS = ""

    DEFAULT_CLASSES = "dialog"

    def __init__(self, source: Source, query: str = "", offline: bool = False) -> None:
        super().__init__()
        self.source = source
        self.query_text = query
        self._placeholder = "日本語" if source == "jisho" else "define"
        self.offline = offline

    def compose(self) -> ComposeResult:
        yield Input(value=self.query_text, placeholder=self._placeholder, id="query")
        yield Static("", id="status")

    def on_mount(self) -> None:
        self.focus_input()
        cfg = load_config()
        mode_label = cfg.get("lookup", "local-first")
        self.query_one("#status", Static).update(f"mode: {mode_label}")

    def focus_input(self) -> None:
        self.query_one("#query", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        self.app.push_screen(ResultsScreen(self.source, text, offline=self.offline))

    def action_lists(self) -> None:
        self.app.push_screen(ListsScreen())

    def action_settings(self) -> None:
        self.app.push_screen(SettingsScreen())

    def action_data(self) -> None:
        self.app.push_screen(LicencesScreen())


class ResultsScreen(Screen):
    CSS_PATH = "app.tcss"
    BINDINGS = [
        Binding("q", "quit", "quit", show=False),
        Binding("escape", "back", "back", show=False),
        Binding("slash", "focus_query", "focus query", show=False),
        Binding("j,down", "scroll_down", "scroll down", show=False),
        Binding("k,up", "scroll_up", "scroll up", show=False),
        Binding("pageup", "scroll_page_up", "page up", show=False),
        Binding("pagedown", "scroll_page_down", "page down", show=False),
        Binding("home", "scroll_home", "home", show=False),
        Binding("end", "scroll_end", "end", show=False),
        Binding("y", "copy_headword", "copy", show=False),
        Binding("o", "open_url", "open", show=False),
        Binding("question_mark", "toggle_help", "help", show=False),
        Binding("a", "add_to_list", "add", show=False),
        Binding("A", "add_to_choose", "add pick", show=False),
        Binding("l", "lists", "lists", show=False),
        Binding("s", "settings", "settings", show=False),
        Binding("K", "kanji", "kanji", show=False),
    ]

    def __init__(self, source: Source, query: str, offline: bool = False) -> None:
        super().__init__()
        self.source = source
        self.query_text = query
        self._result: LookupResult | None = None
        self._error: str | None = None
        self._started = time.monotonic()
        self._selection_index = 0
        self.offline = offline

    def compose(self) -> ComposeResult:
        yield Static("", id="status")
        yield VerticalScroll(Static(id="results"), id="scroll")
        yield Static("q quit · esc edit · y copy · o open · a add · A add-pick · l lists · s settings · K kanji · ? toggle help", id="footer")

    CSS = ""

    DEFAULT_CLASSES = "dialog"

    def on_mount(self) -> None:
        self.app.title = f"kotoba — {self.query_text}"
        self.run_worker(self._lookup, thread=True)

    def on_lookup_complete(self, result: LookupResult, duration_ms: int) -> None:
        self._result = result
        text = render_text(result, width=max(40, self.size.width - 2))
        self.query_one("#results", Static).update(text)
        count = len(result.entries)
        mode_label = config_mode()
        version = ""
        if result.source == "jmdict":
            for name, meta in localdict_installed().items():
                if name in ("jmdict-eng", "jmdict-eng-common"):
                    version = meta.get("version", "")
                    break
        version_note = f" · {version}" if version else ""
        status = f"{mode_label}{version_note} · {count} result{'s' if count != 1 else ''} · {duration_ms} ms"
        self.query_one("#status", Static).update(status)
        self._selection_index = 0

    def on_lookup_error(self, msg: str) -> None:
        self._error = msg
        self.query_one("#results", Static).update(render_error(self.query_text, msg))
        self.query_one("#status", Static).update(msg)

    async def _lookup(self) -> None:
        try:
            result = _fetch(self.source, self.query_text, offline=self.offline)
            duration = int((time.monotonic() - self._started) * 1000)
            self.app.call_from_thread(self.on_lookup_complete, result, duration)
        except Exception as exc:
            self.app.call_from_thread(self.on_lookup_error, str(exc))

    def _selected_entry(self) -> Entry | None:
        if not self._result or not self._result.entries:
            return None
        index = max(0, min(self._selection_index, len(self._result.entries) - 1))
        return self._result.entries[index]

    def _add_to(self, list_name: str) -> None:
        entry = self._selected_entry()
        if entry is None:
            self.notify("no result selected", severity="warning")
            return
        try:
            state = load()
            state, added = add_entry(list_name, entry, state=state)
            save(state)
            if added:
                self.notify(f"added {entry.headword} to {list_name}", severity="information")
            else:
                self.notify(f"already in {list_name}", severity="warning")
        except Exception as exc:
            self.notify(f"failed: {exc}", severity="error")

    def action_add_to_list(self) -> None:
        if not self._result or not self._result.entries:
            return
        entry = self._selected_entry()
        if entry is None:
            return
        try:
            name = last_list()
        except Exception:
            name = "default"
        self._add_to(name)

    def action_add_to_choose(self) -> None:
        entry = self._selected_entry()
        if entry is None:
            return
        self.app.push_screen(ListPickerScreen(entry))

    def action_lists(self) -> None:
        self.app.push_screen(ListsScreen())

    def action_settings(self) -> None:
        self.app.push_screen(SettingsScreen())

    def action_kanji(self) -> None:
        entry = self._selected_entry()
        if entry is None or not entry.headword:
            return
        if not any("\u4e00" <= ch <= "\u9faf" for ch in entry.headword):
            return
        self.app.push_screen(KanjiScreen(entry.headword))

    def action_back(self) -> None:
        self.app.switch_screen(QueryScreen(self.source, self.query_text, offline=self.offline))

    def action_focus_query(self) -> None:
        qs = QueryScreen(self.source, self.query_text, offline=self.offline)
        self.app.switch_screen(qs)
        self.app.call_after_refresh(qs.focus_input)

    def action_scroll_down(self) -> None:
        self.query_one("#scroll", VerticalScroll).scroll_down()

    def action_scroll_up(self) -> None:
        self.query_one("#scroll", VerticalScroll).scroll_up()

    def action_scroll_page_down(self) -> None:
        self.query_one("#scroll", VerticalScroll).scroll_page_down()

    def action_scroll_page_up(self) -> None:
        self.query_one("#scroll", VerticalScroll).scroll_page_up()

    def action_scroll_home(self) -> None:
        self.query_one("#scroll", VerticalScroll).scroll_home()

    def action_scroll_end(self) -> None:
        self.query_one("#scroll", VerticalScroll).scroll_end()

    def action_copy_headword(self) -> None:
        if not self._result or not self._result.entries or not shutil.which("wl-copy"):
            return
        head = self._result.entries[0].headword
        subprocess.run(["wl-copy", head], capture_output=True, check=False)

    def action_open_url(self) -> None:
        if self._result and self._result.url:
            subprocess.run(["xdg-open", self._result.url], capture_output=True, check=False)

    def action_toggle_help(self) -> None:
        footer = self.query_one("#footer", Static)
        if "help-hidden" in footer.classes:
            footer.remove_class("help-hidden")
        else:
            footer.add_class("help-hidden")


class ListPickerScreen(ModalScreen):
    BINDINGS = [
        Binding("escape", "dismiss", "cancel", show=False),
        Binding("enter", "confirm", "confirm", show=False),
        Binding("up", "up", "up", show=False),
        Binding("down", "down", "down", show=False),
    ]

    CSS = "list-dialog"

    DEFAULT_CLASSES = "dialog"

    def __init__(self, entry: Entry) -> None:
        super().__init__()
        self.entry = entry
        self._lists = ["default"]
        self._index = 0

    def compose(self) -> ComposeResult:
        yield Static(f"Add {self.entry.headword} to:", id="title")
        yield Static("", id="lists")
        self._refresh()
        yield Static("enter add · esc cancel", id="hint")

    def _refresh(self) -> None:
        try:
            state = load()
            self._lists = sorted(list_names(state=state)) + ["<new list>"]
            current = last_list(state=state)
            if current in self._lists:
                self._index = self._lists.index(current)
        except Exception:
            self._lists = ["default", "<new list>"]
        self._render_rows()

    def _render_rows(self) -> None:
        lines = []
        for i, name in enumerate(self._lists):
            prefix = "> " if i == self._index else "  "
            lines.append(f"{prefix}{name}")
        self.query_one("#lists", Static).update("\n".join(lines))

    def action_up(self) -> None:
        self._index = max(0, self._index - 1)
        self._render_rows()

    def action_down(self) -> None:
        self._index = min(len(self._lists) - 1, self._index + 1)
        self._render_rows()

    def action_confirm(self) -> None:
        name = self._lists[self._index]
        if name == "<new list>":
            self.app.push_screen(NewListScreen(self.entry))
        else:
            try:
                state = load()
                state, _ = add_entry(name, self.entry, state=state)
                save(state)
                self.app.notify(f"added {self.entry.headword} to {name}")
            except Exception as exc:
                self.app.notify(f"failed: {exc}", severity="error")
            self.app.pop_screen()

    def action_dismiss(self) -> None:
        self.app.pop_screen()


class NewListScreen(ModalScreen):
    BINDINGS = [
        Binding("escape", "dismiss", "cancel", show=False),
        Binding("enter", "confirm", "confirm", show=False),
    ]

    CSS = ""

    DEFAULT_CLASSES = "dialog"

    def __init__(self, entry: Entry) -> None:
        super().__init__()
        self.entry = entry

    def compose(self) -> ComposeResult:
        yield Static("New list name:", id="title")
        yield Input(value="", id="name")
        yield Static("enter create · esc cancel", id="hint")

    def on_mount(self) -> None:
        self.query_one("#name", Input).focus()

    def action_confirm(self) -> None:
        name = self.query_one("#name", Input).value.strip()
        if not name:
            return
        try:
            state = load()
            state, _ = add_entry(name, self.entry, state=state)
            save(state)
            self.app.notify(f"added {self.entry.headword} to {name}")
        except Exception as exc:
            self.app.notify(f"failed: {exc}", severity="error")
        self.app.pop_screen()

    def action_dismiss(self) -> None:
        self.app.pop_screen()


class ListsScreen(ModalScreen):
    BINDINGS = [
        Binding("escape", "dismiss", "back", show=False),
        Binding("enter", "view", "view", show=False),
        Binding("d", "delete_entry", "delete entry", show=False),
        Binding("x", "delete_list", "delete list", show=False),
        Binding("e", "export", "export", show=False),
        Binding("up", "up", "up", show=False),
        Binding("down", "down", "down", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._lists: list[str] = []
        self._index = 0

    def compose(self) -> ComposeResult:
        yield Static("Lists", id="title")
        yield Static("", id="lists")
        yield Static("enter view · e export · d entry · x delete · esc close", id="hint")

    def on_mount(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        try:
            state = load()
            self._lists = sorted(list_names(state=state))
            current = last_list(state=state)
            if current in self._lists:
                self._index = self._lists.index(current)
        except Exception:
            self._lists = []
        self._render_rows()

    def _render_rows(self) -> None:
        if not self._lists:
            self.query_one("#lists", Static).update("no lists")
            return
        lines = []
        for i, name in enumerate(self._lists):
            prefix = "> " if i == self._index else "  "
            try:
                data = get_list(name)
                count = len(data["entries"]) if data else 0
            except Exception:
                count = 0
            marker = " *" if last_list() == name else ""
            lines.append(f"{prefix}{name} ({count}){marker}")
        self.query_one("#lists", Static).update("\n".join(lines))

    def action_up(self) -> None:
        self._index = max(0, self._index - 1)
        self._render_rows()

    def action_down(self) -> None:
        self._index = min(len(self._lists) - 1, self._index + 1)
        self._render_rows()

    def action_view(self) -> None:
        if not self._lists:
            return
        self.app.push_screen(EntriesScreen(self._lists[self._index]))

    def action_export(self) -> None:
        if not self._lists:
            return
        self.app.push_screen(ExportScreen(self._lists[self._index]))

    def action_delete_list(self) -> None:
        if not self._lists:
            return
        self.app.push_screen(ConfirmScreen(self._lists[self._index], self._delete_list))

    def _delete_list(self, name: str) -> None:
        try:
            state = load()
            state, _ = delete_list(name, state=state)
            save(state)
            self.notify(f"deleted list {name}")
        except Exception as exc:
            self.notify(f"failed: {exc}", severity="error")
        self._refresh()

    def action_dismiss(self) -> None:
        self.app.pop_screen()


class EntriesScreen(ModalScreen):
    BINDINGS = [
        Binding("escape", "dismiss", "back", show=False),
        Binding("d", "delete", "delete", show=False),
        Binding("up", "up", "up", show=False),
        Binding("down", "down", "down", show=False),
    ]

    def __init__(self, list_name: str) -> None:
        super().__init__()
        self.list_name = list_name
        self._entries: list[dict] = []
        self._index = 0

    def compose(self) -> ComposeResult:
        yield Static(f"{self.list_name}", id="title")
        yield Static("", id="entries")
        yield Static("d delete entry · esc back", id="hint")

    def on_mount(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        try:
            data = get_list(self.list_name)
            self._entries = list(data.get("entries", [])) if data else []
        except Exception:
            self._entries = []
        self._render_rows()

    def _render_rows(self) -> None:
        if not self._entries:
            self.query_one("#entries", Static).update("no entries")
            return
        lines = []
        for i, item in enumerate(self._entries):
            prefix = "> " if i == self._index else "  "
            head = item["headword"]
            reading = item.get("reading", "")
            lines.append(f"{prefix}{head}【{reading}】" if reading else f"{prefix}{head}")
        self.query_one("#entries", Static).update("\n".join(lines))

    def action_up(self) -> None:
        self._index = max(0, self._index - 1)
        self._render_rows()

    def action_down(self) -> None:
        self._index = min(len(self._entries) - 1, self._index + 1)
        self._render_rows()

    def action_delete(self) -> None:
        if not self._entries:
            return
        item = self._entries[self._index]
        try:
            state = load()
            state, _ = remove_entry(self.list_name, item["headword"], item.get("reading"), state=state)
            save(state)
            self._refresh()
        except Exception as exc:
            self.notify(f"failed: {exc}", severity="error")

    def action_dismiss(self) -> None:
        self.app.pop_screen()


class ExportScreen(ModalScreen):
    BINDINGS = [
        Binding("escape", "dismiss", "cancel", show=False),
        Binding("enter", "confirm", "confirm", show=False),
        Binding("up", "up", "up", show=False),
        Binding("down", "down", "down", show=False),
    ]

    CSS = ""

    DEFAULT_CLASSES = "dialog"

    def __init__(self, list_name: str) -> None:
        super().__init__()
        self.list_name = list_name
        self._options = ["apkg", "tsv", "both"]
        self._index = 0

    def compose(self) -> ComposeResult:
        yield Static(f"Export {self.list_name}:", id="title")
        yield Static("", id="options")

    def on_mount(self) -> None:
        self._render_rows()

    def _render_rows(self) -> None:
        lines = []
        for i, opt in enumerate(self._options):
            prefix = "> " if i == self._index else "  "
            lines.append(f"{prefix}{opt}")
        self.query_one("#options", Static).update("\n".join(lines))

    def action_up(self) -> None:
        self._index = max(0, self._index - 1)
        self._render_rows()

    def action_down(self) -> None:
        self._index = min(len(self._options) - 1, self._index + 1)
        self._render_rows()

    def action_confirm(self) -> None:
        fmt = self._options[self._index]
        try:
            data = get_list(self.list_name)
            if data is None:
                raise ValueError(f"list {self.list_name} not found")
            entries = [entry_from_dict(item) for item in data.get("entries", [])]
            output_dir = None
            paths = export_list(entries, self.list_name, fmt, output_dir=output_dir)
            self.app.notify("\n".join(str(p) for p in paths))
        except Exception as exc:
            self.app.notify(f"export failed: {exc}", severity="error")
        self.app.pop_screen()

    def action_dismiss(self) -> None:
        self.app.pop_screen()


class ConfirmScreen(ModalScreen):
    BINDINGS = [
        Binding("y", "yes", "yes", show=False),
        Binding("n,escape", "no", "no", show=False),
    ]

    CSS = "confirm-dialog"

    def __init__(self, list_name: str, on_confirm) -> None:
        super().__init__()
        self.list_name = list_name
        self.on_confirm = on_confirm

    def compose(self) -> ComposeResult:
        yield Static(f"Delete list '{self.list_name}'? (y/n)", id="title")

    def action_yes(self) -> None:
        self.on_confirm(self.list_name)
        self.app.pop_screen()

    def action_no(self) -> None:
        self.app.pop_screen()


class OnboardingScreen(ModalScreen):
    BINDINGS = [
        Binding("escape", "not_now", "not now", show=False),
        Binding("d", "download", "download", show=False),
    ]

    CSS = ""

    DEFAULT_CLASSES = "dialog"

    _DATASETS = [
        ("jmdict-eng", True, "~11.5 MB", "full JMdict English (219k entries)"),
        ("jmdict-eng-common", False, "~1.5 MB", "common-only JMdict (replaces full)"),
        ("kanjidic2-en", True, "~1.3 MB", "KANJIDIC2 kanji data"),
        ("kradfile", True, "~0.1 MB", "kanji component breakdown"),
        ("radkfile", True, "~0.1 MB", "radical-to-kanji index"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._selected = [checked for _, checked, _, _ in self._DATASETS]
        self._index = 0

    def compose(self) -> ComposeResult:
        yield Static("Local dictionary setup", id="title")
        yield Static("", id="rows")
        yield Static("d download · n not now", id="hint")
        yield Static("Dictionary data from EDRDG (CC BY-SA 4.0); kanji data from KANJIDIC2. See Data & licences.", id="attribution")

    def on_mount(self) -> None:
        self._render_rows()
        rows = self.query_one("#rows", Static)
        if rows is not None:
            rows.focus()

    def on_key(self, event) -> None:
        if event.key in ("up", "k"):
            self._index = max(0, self._index - 1)
            self._render_rows()
            event.stop()
        elif event.key in ("down", "j"):
            self._index = min(len(self._DATASETS) - 1, self._index + 1)
            self._render_rows()
            event.stop()
        elif event.key == "space":
            self._selected[self._index] = not self._selected[self._index]
            self._render_rows()
            event.stop()

    def _render_rows(self) -> None:
        lines = []
        for i, (name, checked, size, desc) in enumerate(self._DATASETS):
            marker = "[x]" if self._selected[i] else "[ ]"
            note = " (replaces full dictionary)" if name == "jmdict-eng-common" else ""
            cursor = " >" if i == self._index else "  "
            lines.append(f"{cursor}{marker} {name} {size} — {desc}{note}")
        self.query_one("#rows", Static).update("\n".join(lines))

    def action_download(self) -> None:
        chosen = [name for i, (name, _, _, _) in enumerate(self._DATASETS) if self._selected[i]]
        if not chosen:
            self.notify("no datasets selected", severity="warning")
            return
        self.app.push_screen(DownloadProgressScreen(chosen))

    def action_not_now(self) -> None:
        onboarding_done(True)
        self.app.pop_screen()


class DownloadProgressScreen(ModalScreen):
    BINDINGS = [
        Binding("escape", "dismiss", "back", show=False),
    ]

    CSS = ""

    DEFAULT_CLASSES = "dialog"

    def __init__(self, datasets: list[str]) -> None:
        super().__init__()
        self.datasets = datasets

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("Downloading dictionaries…", id="title")
            yield Static("", id="rows")

    def on_mount(self) -> None:
        self.run_worker(self._download_all, thread=True)

    async def _download_all(self) -> None:
        statuses = {name: "pending" for name in self.datasets}
        lock = threading.Lock()

        def progress(name, state, fraction):
            with lock:
                statuses[name] = f"{state} {int((fraction or 0) * 100)}%" if fraction else state
                self.app.call_from_thread(self._update, dict(statuses))

        def _update(st):
            lines = [f"{name}: {st[name]}" for name in self.datasets]
            self.query_one("#rows", Static).update("\n".join(lines))

        for name in self.datasets:
            with lock:
                statuses[name] = "downloading"
                self._update(statuses)
            try:
                install_datasets([name], progress=progress)
                with lock:
                    statuses[name] = "done"
                    self._update(statuses)
            except Exception as exc:
                with lock:
                    statuses[name] = f"failed: {exc}"
                    self._update(statuses)
        onboarding_done(True)
        self.app.call_from_thread(self.app.pop_screen)

    def action_dismiss(self) -> None:
        self.app.pop_screen()


class SettingsScreen(ModalScreen):
    BINDINGS = [
        Binding("escape", "dismiss", "back", show=False),
        Binding("up", "up", "up", show=False),
        Binding("down", "down", "down", show=False),
        Binding("enter", "toggle", "toggle", show=False),
    ]

    CSS = ""
    DEFAULT_CLASSES = "dialog"

    _MODES = ["local-first", "local-only", "api-only"]

    def __init__(self) -> None:
        super().__init__()
        self._index = 0
        self._items: list[dict] = []

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("Settings", id="title")
            yield Static("", id="rows")
            yield Static("enter toggle · esc close", id="hint")

    def on_mount(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        cfg = load_config()
        mode = cfg.get("lookup", "local-first")
        ask = cfg.get("ask_at_startup", True)
        self._items = [
            {"kind": "mode", "label": f"Lookup mode: {mode}"},
            {"kind": "ask", "label": f"Ask at startup: {'on' if ask else 'off'}"},
        ]
        for row in local_status():
            self._items.append({"kind": "dataset", "label": f"{row['name']} {row['version']} ({row['size'] // 1024 // 1024} MB) — remove"})
        self._items.append({"kind": "licences", "label": "Data & licences"})
        self._index = 0
        self._render_rows()

    def _render_rows(self) -> None:
        lines = []
        for i, item in enumerate(self._items):
            prefix = "> " if i == self._index else "  "
            lines.append(f"{prefix}{item['label']}")
        self.query_one("#rows", Static).update("\n".join(lines))

    def action_up(self) -> None:
        self._index = max(0, self._index - 1)
        self._render_rows()

    def action_down(self) -> None:
        self._index = min(len(self._items) - 1, self._index + 1)
        self._render_rows()

    def action_toggle(self) -> None:
        item = self._items[self._index]
        kind = item["kind"]
        if kind == "mode":
            current = load_config().get("lookup", "local-first")
            next_mode = self._MODES[(self._MODES.index(current) + 1) % len(self._MODES)]
            set_mode(next_mode)
        elif kind == "ask":
            ask_at_startup(not ask_at_startup())
        elif kind == "dataset":
            name = item["label"].split()[0]
            remove_dataset(name)
        elif kind == "licences":
            self.app.push_screen(LicencesScreen())
        self._refresh()

    def action_dismiss(self) -> None:
        self.app.pop_screen()


class LicencesScreen(ModalScreen):
    BINDINGS = [
        Binding("escape", "dismiss", "back", show=False),
    ]

    CSS = ""

    DEFAULT_CLASSES = "dialog"

    def compose(self) -> ComposeResult:
        yield Static("Data & licences", id="title")
        text = (
            "Dictionary data from EDRDG (JMdict, KANJIDIC2, Kradfile, Radkfile), https://www.edrdg.org/.\n"
            "Licensed under CC BY-SA 4.0, https://creativecommons.org/licenses/by-sa/4.0/\n"
            "WordNet 3.0 © Princeton University; WordNet licence applies.\n"
            "Local SQLite indices are derivatives of CC BY-SA 4.0 data; sharing them carries the share-alike obligation."
        )
        yield Static(text, id="rows")
        yield Static("esc close", id="hint")

    def action_dismiss(self) -> None:
        self.app.pop_screen()


class KanjiScreen(ModalScreen):
    BINDINGS = [
        Binding("escape", "dismiss", "back", show=False),
    ]

    CSS = ""

    DEFAULT_CLASSES = "dialog"

    def __init__(self, headword: str) -> None:
        super().__init__()
        self.headword = headword

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(f"Kanji in {self.headword}", id="title")
            yield Static("", id="rows")
            yield Static("esc close", id="hint")

    def on_mount(self) -> None:
        self.run_worker(self._load, thread=True)

    async def _load(self) -> None:
        lines = []
        for ch in self.headword:
            if ord(ch) < 0x4E00 or ord(ch) >= 0xA000:
                continue
            info = lookup_kanji(ch)
            if info is None:
                lines.append(f"{ch} — no kanjidic2 data installed")
                continue
            parts = [
                f"{info['literal']}",
                f"strokes {info['stroke_count']}",
            ]
            if info.get("grade"):
                parts.append(f"grade {info['grade']}")
            if info.get("jlpt"):
                parts.append(f"JLPT {info['jlpt']}")
            if info.get("on_readings"):
                parts.append(f"on {', '.join(info['on_readings'])}")
            if info.get("kun_readings"):
                parts.append(f"kun {', '.join(info['kun_readings'])}")
            if info.get("meanings"):
                parts.append(f"meanings: {', '.join(info['meanings'])}")
            if info.get("radicals"):
                parts.append(f"radicals: {', '.join(map(str, info['radicals']))}")
            if info.get("components"):
                parts.append(f"components: {', '.join(info['components'])}")
            lines.append("  ".join(parts))
        if not lines:
            lines.append("no kanji in this headword")
        self.app.call_from_thread(self.query_one("#rows", Static).update, "\n".join(lines))

    def action_dismiss(self) -> None:
        self.app.pop_screen()


class KotobaApp(App):
    CSS_PATH = "app.tcss"

    BINDINGS = [
        Binding("s", "settings", "settings", show=True),
        Binding("d", "data", "data & licences", show=True),
        Binding("q", "quit", "quit", show=True),
    ]

    def __init__(self, source: Source, query: str = "", print_only: bool = False, offline: bool = False) -> None:
        super().__init__()
        self.source = source
        self.query_text = query
        self.print_only = print_only
        self.offline = offline

    def on_mount(self) -> None:
        if self.print_only or self.query_text:
            self.push_screen(ResultsScreen(self.source, self.query_text, offline=self.offline))
        else:
            cfg = load_config()
            if not self.offline and cfg.get("ask_at_startup", True) and not cfg.get("onboarding_done", False):
                self.push_screen(OnboardingScreen())
            else:
                self.push_screen(QueryScreen(self.source, self.query_text, offline=self.offline))

    def action_settings(self) -> None:
        self.push_screen(SettingsScreen())

    def action_data(self) -> None:
        self.push_screen(LicencesScreen())

    def action_kanji(self) -> None:
        if isinstance(self.screen, ResultsScreen):
            self.screen.action_kanji()

    def action_lists(self) -> None:
        if isinstance(self.screen, ResultsScreen):
            self.screen.action_lists()
        else:
            self.push_screen(ListsScreen())


def run_app(source: Source, query: str, *, print_only: bool = False, offline: bool = False) -> None:
    KotobaApp(source, query, print_only=print_only, offline=offline).run()
