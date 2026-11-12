from __future__ import annotations

import shutil

from kotoba.langs.english import (
    LookupError,
    _entry,
    _fetch_core,
    _parse,
)

__all__ = ["LookupError", "_parse", "_entry", "fetch"]


def fetch(query: str, *, limit: int | None = None):
    """Live WordNet lookup.  Kept as a module-level helper for backwards compatibility.

    The implementation delegates to ``kotoba.langs.english`` but uses the local
    ``shutil.which`` so that tests can continue to monkeypatch
    ``kotoba.wordnet.shutil.which``.
    """
    return _fetch_core(query, limit, shutil.which)
