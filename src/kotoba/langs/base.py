from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable

from kotoba.model import Entry, LookupResult


class Language(ABC):
    """Abstract protocol for a supported lookup language."""

    code: str
    name: str
    aliases: tuple[str, ...] = ()
    api_module: str = ""

    @abstractmethod
    def datasets(self) -> list[str]:
        """Return dataset ids in preferred installation order."""
        ...

    @abstractmethod
    def search(self, query: str, *, limit: int | None = None, offline: bool = False) -> LookupResult:
        """Resolve *query* and return a LookupResult."""
        ...

    def api_search(self, query: str, *, limit: int | None = None) -> LookupResult:
        """Live API lookup; defaults to :meth:`search` with offline=False."""
        return self.search(query, limit=limit, offline=False)

    def render_extras(self, entry: Entry) -> dict:
        """Return language-specific rendering hints for an entry."""
        return {}

    def special(self, name: str, query: str) -> dict | None:
        """Handle a special sub-command such as ``kanji``."""
        return None

    def autodetect(self, text: str) -> bool:
        """Return True when *text* appears to be written in this language."""
        return False
