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
    return _fetch_core(query, limit, shutil.which)
