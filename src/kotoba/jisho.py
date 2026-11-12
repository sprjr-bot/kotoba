from __future__ import annotations

# ponytail: re-export shim so existing importers and monkey-patches keep working.
from kotoba.langs.japanese import LookupError
from kotoba.langs.japanese import fetch as _fetch_core


def fetch(query: str, *, timeout: float = 8.0, limit: int = 12):
    """Backwards-compatible Jisho fetch that delegates to the language module."""
    return _fetch_core(query, timeout=timeout, limit=limit)


__all__ = ["LookupError", "fetch"]
