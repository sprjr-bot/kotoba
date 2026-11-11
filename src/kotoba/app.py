from __future__ import annotations

import shutil
import subprocess
import time
from typing import Literal

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Input, Static

from kotoba.export import export_list
from kotoba.lists import add_entry, delete_list, entry_from_dict, get_list, last_list, list_names, load, remove_entry, save
from kotoba.model import Entry, LookupResult
from kotoba.render import render_error, render_text

Source = Literal["jisho", "wordnet"]


def _fetch(source: Source, query: str) -> LookupResult:
    if source == "jisho":
        from kotoba import jisho
        return jisho.fetch(query)
    from kotoba import wordnet
    return wordnet.fetch(query)


class QueryScreen(Screen):
    BINDINGS = [
        Binding("ctrl+c", "quit", "quit", show=False),
        Binding("escape", "quit", "quit", show=False),
        Binding("l", "lists", "lists", show=False),
    ]

    def __init__(self, source: Source, query: str = "") -> None:
        super().__init__()
        self.source = source
        self.query_text = query
        self._placeholder = "日本語" if source == "jisho" else "define"

    def compose(self) -> ComposeResult:
        yield Input(value=self.query_text, placeholder=self._placeholder, id="query")
        yield Static("", id="status")

    def on_mount(self) -> None:
        self.focus_input()

    def focus_input(self) -> None:
        self.query_one("#query", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        self.app.push_screen(ResultsScreen(self.source, text))

    def action_lists(self) -> None:
        self.app.push_screen(ListsScreen())


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
    ]

    def __init__(self, source: Source, query: str) -> None:
        super().__init__()
        self.source = source
        self.query_text = query
        self._result: LookupResult | None = None
        self._error: str | None = None
        self._started = time.monotonic()
        self._selection_index = 0

    def compose(self) -> ComposeResult:
        yield Static("", id="status")
        yield VerticalScroll(Static(id="results"), id="scroll")
        yield Static("q quit · esc edit · y copy · o open · a add · A add-pick · l lists · ? toggle help", id="footer")

    def on_mount(self) -> None:
        self.app.title = f"kotoba — {self.query_text}"
        self.run_worker(self._lookup, thread=True)

    def on_lookup_complete(self, result: LookupResult, duration_ms: int) -> None:
        self._result = result
        text = render_text(result, width=max(40, self.size.width - 2))
        self.query_one("#results", Static).update(text)
        count = len(result.entries)
        status = f"{self.source} · {count} result{'s' if count != 1 else ''} · {duration_ms} ms"
        self.query_one("#status", Static).update(status)

    def on_lookup_error(self, msg: str) -> None:
        self._error = msg
        self.query_one("#results", Static).update(render_error(self.query_text, msg))
        self.query_one("#status", Static).update(msg)

    async def _lookup(self) -> None:
        try:
            result = _fetch(self.source, self.query_text)
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

    def action_back(self) -> None:
        self.app.switch_screen(QueryScreen(self.source, self.query_text))

    def action_focus_query(self) -> None:
        qs = QueryScreen(self.source, self.query_text)
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


class ListPickerScreen(Screen):
    BINDINGS = [
        Binding("escape", "dismiss", "cancel", show=False),
        Binding("enter", "confirm", "confirm", show=False),
        Binding("up", "up", "up", show=False),
        Binding("down", "down", "down", show=False),
    ]

    def __init__(self, entry: Entry) -> None:
        super().__init__()
        self.entry = entry
        self._lists = ["default"]
        self._index = 0

    def compose(self) -> ComposeResult:
        yield Static(f"Add {self.entry.headword} to:", id="title")
        yield Static("", id="lists")
        yield Static("enter pick · n new list · esc cancel", id="hint")

    def compose_add_class(self) -> None:
        self.add_class("list-dialog")

    def on_mount(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        try:
            state = load()
            self._lists = sorted(list_names(state=state)) + ["<new list>"]
            current = last_list(state=state)
            if current in self._lists:
                self._index = self._lists.index(current)
        except Exception:
            self._lists = ["default", "<new list>"]
        self._render()

    def _render(self) -> None:
        lines = []
        for i, name in enumerate(self._lists):
            prefix = "> " if i == self._index else "  "
            lines.append(f"{prefix}{name}")
        self.query_one("#lists", Static).update("\n".join(lines))

    def action_up(self) -> None:
        self._index = max(0, self._index - 1)
        self._render()

    def action_down(self) -> None:
        self._index = min(len(self._lists) - 1, self._index + 1)
        self._render()

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


class NewListScreen(Screen):
    BINDINGS = [
        Binding("escape", "dismiss", "cancel", show=False),
        Binding("enter", "confirm", "confirm", show=False),
    ]

    CSS = "list-dialog"

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


class ListsScreen(Screen):
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
        self._render()

    def _render(self) -> None:
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
        self._render()

    def action_down(self) -> None:
        self._index = min(len(self._lists) - 1, self._index + 1)
        self._render()

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


class EntriesScreen(Screen):
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
        self._render()

    def _render(self) -> None:
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
        self._render()

    def action_down(self) -> None:
        self._index = min(len(self._entries) - 1, self._index + 1)
        self._render()

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


class ExportScreen(Screen):
    BINDINGS = [
        Binding("escape", "dismiss", "cancel", show=False),
        Binding("enter", "confirm", "confirm", show=False),
        Binding("up", "up", "up", show=False),
        Binding("down", "down", "down", show=False),
    ]

    CSS = "list-dialog"

    def __init__(self, list_name: str) -> None:
        super().__init__()
        self.list_name = list_name
        self._options = ["apkg", "tsv", "both"]
        self._index = 0

    def compose(self) -> ComposeResult:
        yield Static(f"Export {self.list_name}:", id="title")
        yield Static("", id="options")

    def on_mount(self) -> None:
        self._render()

    def _render(self) -> None:
        lines = []
        for i, opt in enumerate(self._options):
            prefix = "> " if i == self._index else "  "
            lines.append(f"{prefix}{opt}")
        self.query_one("#options", Static).update("\n".join(lines))

    def action_up(self) -> None:
        self._index = max(0, self._index - 1)
        self._render()

    def action_down(self) -> None:
        self._index = min(len(self._options) - 1, self._index + 1)
        self._render()

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


class ConfirmScreen(Screen):
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


class KotobaApp(App):
    CSS_PATH = "app.tcss"

    def __init__(self, source: Source, query: str = "", print_only: bool = False) -> None:
        super().__init__()
        self.source = source
        self.query_text = query
        self.print_only = print_only

    def on_mount(self) -> None:
        if self.print_only or self.query_text:
            self.push_screen(ResultsScreen(self.source, self.query_text))
        else:
            self.push_screen(QueryScreen(self.source, self.query_text))


def run_app(source: Source, query: str) -> None:
    KotobaApp(source, query).run()
