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

from kotoba.model import LookupResult
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
    ]

    def __init__(self, source: Source, query: str) -> None:
        super().__init__()
        self.source = source
        self.query_text = query
        self._result: LookupResult | None = None
        self._error: str | None = None
        self._started = time.monotonic()

    def compose(self) -> ComposeResult:
        yield Static("", id="status")
        yield VerticalScroll(Static(id="results"), id="scroll")
        yield Static("q quit · esc edit · y copy · o open · ? help", id="footer")

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
