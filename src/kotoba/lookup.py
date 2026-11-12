from __future__ import annotations

from kotoba import config, langs, localdict
from kotoba.model import Entry, LookupResult, Sense


class LookupError(Exception):
    pass


Source = str


def _local_available() -> bool:
    return bool(localdict.installed())


def _mode_from_args(args) -> config.ConfigMode:
    if getattr(args, "offline", False):
        return "local-only"
    return config.mode()


def _local_lookup(query: str, limit: int) -> LookupResult:
    return localdict.lookup(query, limit=limit)


def _api_lookup(source: Source, query: str, limit: int | None) -> LookupResult:
    return langs.get(source).api_search(query, limit=limit)


def _merge_error(local_err: Exception | None, api_err: Exception | None) -> str:
    parts = []
    if local_err:
        parts.append(f"local: {local_err}")
    if api_err:
        parts.append(f"api: {api_err}")
    return "; ".join(parts) or "lookup failed"


def lookup(source: Source, query: str, limit: int | None, *, mode: config.ConfigMode | None = None, offline: bool = False) -> LookupResult:
    if mode is None:
        mode = "local-only" if offline else config.mode()

    if source != "jisho":
        # English queries never touch local JMdict index
        return _api_lookup(source, query, limit)

    has_data = _local_available()
    local_err: Exception | None = None

    if mode == "api-only" or (not has_data and mode in ("local-first", "local-only")):
        return _api_lookup(source, query, limit)

    if mode == "local-only":
        result = _local_lookup(query, limit or 12)
        if result.entries:
            return result
        raise LookupError("not in local dictionary")

    # local-first
    try:
        result = _local_lookup(query, limit or 12)
        if result.entries:
            return result
    except Exception as exc:
        local_err = exc

    try:
        return _api_lookup(source, query, limit)
    except Exception as exc:
        raise LookupError(_merge_error(local_err, exc)) from exc


def kanji(literal: str) -> dict | None:
    return localdict.kanji(literal)


def local_status() -> list[dict]:
    return localdict.status()


def install_datasets(
    names: list[str],
    *,
    all_: bool = False,
    latest: bool = False,
    progress=None,
    fetcher=None,
) -> list[dict]:
    japanese = langs.get("jisho")
    targets = list(japanese.datasets()) if all_ else names
    results: list[dict] = []
    for name in targets:
        meta = localdict.install(name, latest=latest, progress=progress, fetcher=fetcher)
        results.append(meta)
    return results


def remove_dataset(name: str) -> bool:
    return localdict.remove(name)


def reindex(name: str | None = None) -> list[dict]:
    if name:
        return [localdict.reindex(name)]
    return [localdict.reindex(n) for n in localdict.installed().keys()]


def update(fetcher=None, progress=None) -> list[dict]:
    return localdict.update(fetcher=fetcher, progress=progress)


def lookup_wordnet_mock_fallback(query: str) -> LookupResult:
    return LookupResult(query=query, source="wordnet", entries=())
