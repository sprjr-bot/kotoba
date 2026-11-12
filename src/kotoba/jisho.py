from __future__ import annotations

from kotoba.langs.japanese import LookupError
from kotoba.langs.japanese import fetch as _fetch_core


def fetch(query: str, *, timeout: float = 8.0, limit: int = 12):
    return _fetch_core(query, timeout=timeout, limit=limit)


__all__ = ["LookupError", "fetch"]
