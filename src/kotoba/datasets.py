"""Dataset descriptors and the generic install pipeline.

Every local dictionary dataset is described by a :class:`DatasetDescriptor`
loaded from ``kotoba/data/datasets.json``.  The pipeline is deliberately
language agnostic: it resolves a download URL, fills a shared download cache,
verifies the pinned hash, extracts the archive, and hands the extracted payload
to a language specific ingest callable named ``module:function``.

Language modules keep only ingestion and lookup code; the dataset tables,
release resolution and hash policy live here.
"""

from __future__ import annotations

import hashlib
import importlib
import inspect
import json
import os
import shutil
import stat
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, cast
from urllib.parse import urlparse
from urllib.request import Request, urlopen

DESCRIPTOR_PATH = Path(__file__).resolve().parent / "data" / "datasets.json"

ARCHIVE_FORMATS = ("json.tgz", "jsonl.gz", "zip", "single-json")
EXTRACTION_SHAPES = ("single-json-file", "first-json-file", "jsonl-lines", "raw-file", "gzip-jsonl-lines")

_ARCHIVE_SUFFIX = {
    "json.tgz": ".json.tgz",
    "jsonl.gz": ".jsonl.gz",
    "zip": ".zip",
    "single-json": ".json",
}

_REQUIRED_FIELDS = (
    "id",
    "language",
    "name",
    "url",
    "license",
    "attribution",
    "archive_format",
    "extraction_shape",
    "ingest",
)

_DEFAULT_FETCH_TIMEOUT = 120.0
_USER_AGENT = "kotoba-localdict/0.1.0"

#: ``progress(dataset_id, state, fraction_or_none)``
FetchProgress = Callable[[str, str, "float | None"], None]

#: ``ingest(source_path, dataset_dir, descriptor)``
Ingest = Callable[[Path, Path, "DatasetDescriptor"], None]


class DictError(Exception):
    """Raised for local dictionary dataset problems."""


@dataclass
class DatasetDescriptor:
    """One installable dictionary dataset."""

    id: str
    language: str
    name: str
    url: str
    sha256: str | None = None
    license: str = ""
    attribution: str = ""
    archive_format: str = ""
    extraction_shape: str = ""
    ingest: str = ""
    version: str = ""
    dump_date: str = ""
    conflicts_with: list[str] = field(default_factory=list)
    enabled_by_default: bool = True
    primary: bool = False
    retain_archive: bool = True
    homepage: str = ""
    asset_prefix: str | None = None
    release_api: str | None = None
    notice: str = ""
    archive_bytes_hint: int = 0

    @property
    def pinned(self) -> bool:
        """True when the descriptor pins an expected archive hash."""
        return self.sha256 is not None

    @classmethod
    def from_dict(cls, data: dict) -> "DatasetDescriptor":
        if not isinstance(data, dict):
            raise DictError(f"dataset descriptor must be an object, got {type(data).__name__}")
        known = {f.name for f in fields(cls)}
        unknown = sorted(set(data) - known)
        if unknown:
            raise DictError(f"descriptor {data.get('id', '<unknown>')}: unknown field(s): {', '.join(unknown)}")
        conflicts = data.get("conflicts_with") or []
        if not isinstance(conflicts, list) or any(not isinstance(item, str) for item in conflicts):
            raise DictError(f"descriptor {data.get('id', '<unknown>')}: conflicts_with must be a list of ids")
        try:
            descriptor = cls(**data)
        except TypeError as exc:  # pragma: no cover - guarded by the known-field check
            raise DictError(f"invalid dataset descriptor: {exc}") from exc
        descriptor.validate()
        return descriptor

    def validate(self) -> None:
        for name in _REQUIRED_FIELDS:
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise DictError(f"descriptor {self.id or '<unknown>'}: missing required field '{name}'")
        if self.archive_format not in ARCHIVE_FORMATS:
            raise DictError(
                f"descriptor {self.id}: unsupported archive_format {self.archive_format!r} "
                f"(expected one of {', '.join(ARCHIVE_FORMATS)})"
            )
        if self.extraction_shape not in EXTRACTION_SHAPES:
            raise DictError(
                f"descriptor {self.id}: unsupported extraction_shape {self.extraction_shape!r} "
                f"(expected one of {', '.join(EXTRACTION_SHAPES)})"
            )
        module, sep, attr = self.ingest.partition(":")
        if not sep or not module.strip() or not attr.strip():
            raise DictError(f"descriptor {self.id}: ingest must be 'module:callable', got {self.ingest!r}")
        if self.sha256 is not None:
            digest = self.sha256.lower()
            if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
                raise DictError(f"descriptor {self.id}: sha256 must be 64 hex characters")
            self.sha256 = digest


# --------------------------------------------------------------------------- #
# registry


_REGISTRY: dict[str, DatasetDescriptor] | None = None
_INGEST_CACHE: dict[str, Ingest] = {}


def load_registry(path: Path | str = DESCRIPTOR_PATH) -> dict[str, DatasetDescriptor]:
    """Load and validate the descriptor registry from *path*."""
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise DictError(f"cannot read dataset registry {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise DictError(f"invalid dataset registry {path}: {exc}") from exc

    if isinstance(raw, dict):
        items = raw.get("datasets")
    else:
        items = raw
    if not isinstance(items, list):
        raise DictError(f"invalid dataset registry {path}: expected a 'datasets' list")

    registry: dict[str, DatasetDescriptor] = {}
    for item in items:
        descriptor = DatasetDescriptor.from_dict(item)
        if descriptor.id in registry:
            raise DictError(f"duplicate dataset id in registry: {descriptor.id}")
        registry[descriptor.id] = descriptor

    for descriptor in registry.values():
        for other in descriptor.conflicts_with:
            if other not in registry:
                raise DictError(f"descriptor {descriptor.id}: conflicts_with unknown dataset {other}")
            if other == descriptor.id:
                raise DictError(f"descriptor {descriptor.id}: cannot conflict with itself")
    return registry


def registry() -> dict[str, DatasetDescriptor]:
    """Return the loaded descriptor registry (cached)."""
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = load_registry(DESCRIPTOR_PATH)
    return _REGISTRY.copy()


def reset_registry() -> None:
    """Drop the cached registry and ingest callables (used by tooling/tests)."""
    global _REGISTRY
    _REGISTRY = None
    _INGEST_CACHE.clear()


def descriptor(dataset_id: str) -> DatasetDescriptor:
    """Return the descriptor for *dataset_id*."""
    try:
        return registry()[dataset_id]
    except KeyError:
        raise DictError(f"unknown dataset: {dataset_id}") from None


def known_ids() -> list[str]:
    """Return every registered dataset id in registry order."""
    return list(registry())


def enabled_ids(language: str | None = None) -> list[str]:
    """Return ids installed by ``dict install --all`` (or by language)."""
    return [
        item.id
        for item in registry().values()
        if item.enabled_by_default and (language is None or item.language == language)
    ]


def primary_ids(language: str | None = None) -> list[str]:
    """Return primary ids for a language, or every primary id."""
    return [
        item.id
        for item in registry().values()
        if item.primary and (language is None or item.language == language)
    ]


def ids_for_language(language: str) -> list[str]:
    """Return every dataset id for *language* in registry order."""
    return [item.id for item in registry().values() if item.language == language]


# --------------------------------------------------------------------------- #
# paths


def data_dir() -> Path:
    base = os.environ.get("XDG_DATA_HOME")
    if base:
        return Path(base) / "kotoba" / "dict"
    return Path.home() / ".local" / "share" / "kotoba" / "dict"


def cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME")
    if base:
        return Path(base) / "kotoba"
    return Path.home() / ".cache" / "kotoba"


def download_dir() -> Path:
    """Shared download cache, reused when two languages need the same archive."""
    return cache_dir() / "downloads"


def dataset_dir(dataset_id: str) -> Path:
    _safe_id(dataset_id)
    return data_dir() / dataset_id


def _safe_id(dataset_id: str) -> str:
    if not dataset_id or dataset_id in (".", "..") or "/" in dataset_id or "\\" in dataset_id:
        raise DictError(f"unknown dataset: {dataset_id}")
    return dataset_id


def db_path(dataset_path: Path) -> Path:
    return dataset_path / "index.sqlite3"


def index_size(dataset_path: Path) -> int:
    total = 0
    for suffix in ("", "-wal", "-shm"):
        path = dataset_path / ("index.sqlite3" + suffix)
        if path.exists():
            total += path.stat().st_size
    return total


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- #
# metadata


def read_meta(dataset_path: Path) -> dict | None:
    """Read ``meta.json`` from a dataset directory, or None."""
    path = dataset_path / "meta.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def write_meta(dataset_path: Path, meta: dict) -> None:
    path = dataset_path / "meta.json"
    _ensure_dir(dataset_path)
    fd, tmp = tempfile.mkstemp(dir=dataset_path, prefix=".meta-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(meta, indent=2, ensure_ascii=False) + "\n")
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def migrate_meta(meta: dict, dataset_path_name: str = "") -> dict:
    """Return *meta* with ``descriptor_id`` filled in for legacy installs.

    Legacy installs wrote ``name`` (the dataset id) but no ``descriptor_id``.
    Matching happens at load time only: nothing is rewritten on disk and no
    download is triggered.
    """
    if meta.get("descriptor_id"):
        return meta
    registry_ids = registry()
    candidate = meta.get("name") or dataset_path_name
    desc = registry_ids.get(candidate) if candidate else None
    if desc is None and dataset_path_name:
        desc = registry_ids.get(dataset_path_name)
    if desc is None:
        return meta
    migrated = dict(meta)
    migrated["descriptor_id"] = desc.id
    migrated.setdefault("dump_date", desc.dump_date)
    return migrated


def installed() -> dict[str, dict]:
    """Return ``{dataset_id: meta}`` for every installed dataset.

    Unknown (legacy) dataset directories are returned too so ``status`` can
    report them; they are excluded from ``update``.
    """
    root = data_dir()
    found: dict[str, dict] = {}
    if not root.exists():
        return found
    try:
        entries = sorted(entry for entry in root.iterdir() if entry.is_dir())
    except OSError:
        return found
    for entry in entries:
        meta = read_meta(entry)
        if meta is None:
            continue
        found[entry.name] = migrate_meta(meta, entry.name)

    ordered: dict[str, dict] = {}
    for dataset_id in registry():
        if dataset_id in found:
            ordered[dataset_id] = found[dataset_id]
    for dataset_id in sorted(found):
        if dataset_id not in ordered:
            ordered[dataset_id] = found[dataset_id]
    return ordered


def installed_meta(dataset_id: str) -> dict | None:
    """Return the (migrated) meta for one installed dataset, or None."""
    meta = read_meta(dataset_dir(dataset_id))
    if meta is None:
        return None
    return migrate_meta(meta, dataset_id)


# --------------------------------------------------------------------------- #
# release resolution + downloads


@dataclass(frozen=True)
class ResolvedAsset:
    """A download URL plus the metadata needed to record it."""

    url: str
    asset_name: str
    version: str


def github_latest(url: str, fetcher: Callable[[str], dict] | None = None) -> dict:
    """Return the latest release document for *url*."""
    if fetcher is not None:
        return fetcher(url)
    req = Request(url, headers={"User-Agent": _USER_AGENT})
    with urlopen(req, timeout=30.0) as resp:
        return json.loads(resp.read().decode("utf-8"))


def asset_for(release: dict, descriptor: DatasetDescriptor) -> dict | None:
    """Pick the release asset that belongs to *descriptor*."""
    prefix = descriptor.asset_prefix or descriptor.id
    suffix = _ARCHIVE_SUFFIX[descriptor.archive_format]
    for asset in release.get("assets", []):
        name = asset.get("name", "")
        if name.startswith(prefix) and name.endswith(suffix):
            return asset
    return None


def resolve_source(descriptor: DatasetDescriptor, *, fetcher: Callable[[str], dict] | None = None) -> ResolvedAsset:
    """Resolve the descriptor to a concrete download URL."""
    if descriptor.release_api:
        release = github_latest(descriptor.release_api, fetcher=fetcher)
        asset = asset_for(release, descriptor)
        if asset is None:
            raise DictError(f"release contains no recognized assets for {descriptor.id}")
        version = release.get("tag_name") or descriptor.version or "unknown"
        return ResolvedAsset(asset["browser_download_url"], asset["name"], version)
    name = Path(urlparse(descriptor.url).path).name
    return ResolvedAsset(descriptor.url, name or f"{descriptor.id}{_ARCHIVE_SUFFIX[descriptor.archive_format]}", descriptor.version)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(1024 * 256)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _download(url: str, dest: Path, progress: FetchProgress | None = None, label: str = "") -> None:
    label = label or url
    _ensure_dir(dest.parent)
    if url.startswith("file://"):
        shutil.copyfile(url[7:], dest)
        return
    req = Request(url, headers={"User-Agent": _USER_AGENT})
    with urlopen(req, timeout=_DEFAULT_FETCH_TIMEOUT) as resp:
        total = resp.headers.get("Content-Length")
        total = int(total) if total else None
        fd, tmp = tempfile.mkstemp(dir=dest.parent, prefix=".download-", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as fh:
                received = 0
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    fh.write(chunk)
                    received += len(chunk)
                    if total and progress:
                        progress(label, "downloading", received / total)
            os.replace(tmp, dest)
        except Exception:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass
            raise


def _fetch_verified(
    descriptor: DatasetDescriptor,
    asset: ResolvedAsset,
    *,
    accept: bool,
    refresh: bool,
    progress: FetchProgress | None,
) -> tuple[Path, str]:
    # Keep cached archive on mismatch once, so a truncated cache cannot wedge the install.
    descriptor_id = descriptor.id
    expected = descriptor.sha256
    cached = download_dir() / asset.asset_name
    if refresh:
        cached.unlink(missing_ok=True)

    reused = cached.exists()
    while True:
        if not cached.exists():
            _download(asset.url, cached, progress=progress, label=descriptor_id)
            reused = False
        observed = sha256_file(cached)
        if expected is None or observed == expected or accept:
            return cached, observed
        cached.unlink(missing_ok=True)
        if reused:
            reused = False
            continue
        raise DictError(
            f"hash mismatch for {descriptor_id}: expected {expected}, got {observed}; upstream may have moved "
            f"(re-run with --accept-new-dump to accept the new dump)"
        )


def clear_download_cache() -> tuple[int, int]:
    """Delete the shared download cache; return ``(files, bytes)`` removed."""
    root = download_dir()
    if not root.exists():
        return (0, 0)
    files = 0
    size = 0
    for entry in root.rglob("*"):
        try:
            if entry.is_file():
                files += 1
                size += entry.stat().st_size
        except OSError:
            continue
    shutil.rmtree(root, ignore_errors=True)
    return (files, size)


def _link_or_copy(source: Path, dest: Path) -> None:
    if dest.exists():
        dest.unlink()
    _ensure_dir(dest.parent)
    try:
        os.link(source, dest)
    except OSError:
        shutil.copyfile(source, dest)


# --------------------------------------------------------------------------- #
# extraction


def extract_archive(archive: Path, dest_dir: Path, descriptor: DatasetDescriptor) -> tuple[Path, bool]:
    """Extract *archive* into *dest_dir*.

    Returns ``(payload_path, temporary)``; the caller removes *payload_path*
    when *temporary* is true.
    """
    fmt = descriptor.archive_format
    shape = descriptor.extraction_shape
    if fmt == "json.tgz":
        return _extract_tar(archive, dest_dir, descriptor), True
    if fmt == "zip":
        return _extract_zip(archive, dest_dir), True
    if fmt == "jsonl.gz":
        return archive, False
    if fmt == "single-json" or shape == "gzip-jsonl-lines":
        return archive, False
    raise DictError(f"unsupported archive format: {fmt}")


def _json_members(members: Iterable) -> list:
    return [member for member in members if member.name.endswith(".json")]


def _extract_tar(archive: Path, dest_dir: Path, descriptor: DatasetDescriptor) -> Path:
    with tarfile.open(archive, "r:gz") as tf:
        members = _json_members(tf.getmembers())
        if not members:
            raise DictError("archive contains no .json file")
        if descriptor.extraction_shape == "single-json-file" and len(members) > 1:
            raise DictError(f"archive contains multiple .json files, expected one for {descriptor.id}")
        chosen = members[0]
        try:
            tf.extractall(path=dest_dir, members=[chosen], filter="data")
        except TypeError:  # pragma: no cover - Python < 3.11.4
            tf.extractall(path=dest_dir, members=[chosen])
        return dest_dir / chosen.name


def _extract_zip(archive: Path, dest_dir: Path) -> Path:
    with zipfile.ZipFile(archive) as zf:
        names = [name for name in zf.namelist() if name.endswith(".json")]
        if not names:
            raise DictError("archive contains no .json file")
        chosen = names[0]
        zf.extract(chosen, path=dest_dir)
        return dest_dir / chosen


# --------------------------------------------------------------------------- #
# ingest callables


def ingest_callable(spec: str) -> Ingest:
    """Resolve an ``module:callable`` ingest spec to a callable."""
    cached = _INGEST_CACHE.get(spec)
    if cached is not None:
        return cached
    module_name, _, attr = spec.partition(":")
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise DictError(f"cannot load ingest module {module_name}: {exc}") from exc
    try:
        fn = getattr(module, attr)
    except AttributeError as exc:
        raise DictError(f"ingest callable {spec} not found") from exc
    if not callable(fn):
        raise DictError(f"ingest callable {spec} is not callable")
    ingest = cast(Ingest, fn)
    _INGEST_CACHE[spec] = ingest
    return ingest


def dataset_attribution_block() -> dict:
    """Return installed dataset attribution for the ``dict notice`` command."""
    rows = status()[:-1] if status() else []  # drop total row when present
    datasets = []
    for row in rows:
        if row.get("legacy"):
            continue
        desc = registry().get(row["name"])
        datasets.append(
            {
                "name": row["name"],
                "license": row.get("license", ""),
                "attribution": row.get("attribution", ""),
                "source_url": row.get("source_url", ""),
                "notice": desc.notice if desc else "",
            }
        )
    return {"datasets": datasets, "shared_notice": ""}


def _format_size(size: int | None) -> str:
    if size is None:
        return ""
    for unit, denom in (("GB", 1024**3), ("MB", 1024**2), ("KB", 1024)):
        if size >= denom:
            return f"{size / denom:.2f} {unit}"
    return f"{size} bytes"


format_size = _format_size

#: Size above which a first-launch/download warning is shown.
CACHE_SIZE_THRESHOLD = 20 * 1024 * 1024


def install_exceeds_threshold(descriptor: DatasetDescriptor) -> bool:
    """Return True when the descriptor's archive is large enough to warn about."""
    return descriptor.archive_bytes_hint > CACHE_SIZE_THRESHOLD


def download_size_notice(descriptor: DatasetDescriptor) -> str:
    """Return license + source + download-size notice for a not-yet-installed dataset."""
    size = descriptor.archive_bytes_hint
    size_note = f" (~{format_size(size)})" if size else ""
    lines = [
        f"{descriptor.name} ({descriptor.id}) will be downloaded{size_note}.",
        f"License: {descriptor.license}",
        f"Source: {descriptor.homepage or descriptor.url}",
    ]
    if descriptor.notice:
        lines.append(descriptor.notice)
    return "\n".join(lines)


def pending_download_notice(dataset_ids: list[str] | None = None) -> str:
    """Return a combined first-launch notice for the selected (or default) datasets."""
    ids = dataset_ids or enabled_ids()
    notices = [download_size_notice(descriptor(did)) for did in ids]
    if not notices:
        return ""
    return "The following datasets will be downloaded:\n\n" + "\n\n".join(notices)


# --------------------------------------------------------------------------- #
# pipeline


def _meta(descriptor: DatasetDescriptor, asset: ResolvedAsset, dataset_path: Path, observed: str, version: str) -> dict:
    archive_path = dataset_path / asset.asset_name
    archive_bytes = archive_path.stat().st_size if archive_path.exists() else 0
    index_bytes = index_size(dataset_path)
    return {
        "name": descriptor.id,
        "descriptor_id": descriptor.id,
        "version": version,
        "asset": asset.asset_name,
        "sha256": observed,
        "sha256_observed": observed,
        "dump_date": descriptor.dump_date,
        "archive_bytes": archive_bytes,
        "index_bytes": index_bytes,
        "size": archive_bytes + index_bytes,
        "source_url": descriptor.homepage or descriptor.url,
        "license": descriptor.license,
        "attribution": descriptor.attribution,
        "retrieved_at": _now(),
    }


def install(
    dataset_id: str,
    *,
    latest: bool = False,
    accept_new_dump: bool = False,
    purge_cache: bool = False,
    refresh: bool = False,
    fetcher: Callable[[str], dict] | None = None,
    progress: FetchProgress | None = None,
    full_index: bool = False,
) -> dict:
    """Install one dataset: resolve, download, verify, extract, ingest."""
    descriptor_ = descriptor(dataset_id)
    asset = resolve_source(descriptor_, fetcher=fetcher)
    expected = descriptor_.sha256
    accept = latest or accept_new_dump

    cached, observed = _fetch_verified(
        descriptor_, asset, accept=accept, refresh=refresh, progress=progress
    )

    # Conflict removal happens only after the archive is proven good.
    for other in descriptor_.conflicts_with:
        if dataset_dir(other).exists():
            remove(other)

    dataset_path = dataset_dir(dataset_id)
    _ensure_dir(dataset_path)
    archive_path = dataset_path / asset.asset_name
    if descriptor_.retain_archive:
        _link_or_copy(cached, archive_path)
    elif archive_path.exists():
        archive_path.unlink()

    payload, temporary = extract_archive(cached if not descriptor_.retain_archive else archive_path, dataset_path, descriptor_)
    try:
        ingest_fn = ingest_callable(descriptor_.ingest)
        if _ingest_accepts(ingest_fn, "full_index"):
            ingest_fn(payload, dataset_path, descriptor_, full_index=full_index)
        else:
            ingest_fn(payload, dataset_path, descriptor_)
    finally:
        if temporary:
            payload.unlink(missing_ok=True)

    version = asset.version or descriptor_.version
    meta = _meta(descriptor_, asset, dataset_path, observed, version)
    write_meta(dataset_path, meta)

    if expected is None:
        print(
            f"installed {dataset_id} {version} with sha256 {observed}"
            f" (dump {descriptor_.dump_date or 'undated'}) — verify and update the descriptor pin if acceptable"
        )
    elif observed != expected:
        print(f"installed {dataset_id} {version} with sha256 {observed} — verify and update pinned hash if acceptable")

    if purge_cache:
        clear_download_cache()

    return meta


def _ingest_accepts(fn: Callable, name: str) -> bool:
    try:
        sig = inspect.signature(fn)
    except (ValueError, TypeError):
        return False
    return name in sig.parameters


def remove(dataset_id: str) -> bool:
    """Delete an installed dataset directory; return False when absent."""
    dataset_path = dataset_dir(dataset_id)
    if not dataset_path.exists():
        return False
    shutil.rmtree(dataset_path)
    return True


def reindex(dataset_id: str) -> dict:
    """Rebuild one dataset index from the archive stored with the install."""
    descriptor_ = descriptor(dataset_id)
    if not descriptor_.retain_archive:
        raise DictError(f"archive not retained for {dataset_id}; reinstall to rebuild the index")
    dataset_path = dataset_dir(dataset_id)
    meta = installed_meta(dataset_id)
    if meta is None:
        raise DictError(f"no installed metadata for {dataset_id}")
    asset_name = meta.get("asset")
    archive = dataset_path / asset_name if asset_name else None
    if archive is None or not archive.exists():
        raise DictError(f"stored archive missing for {dataset_id}")
    payload, temporary = extract_archive(archive, dataset_path, descriptor_)
    try:
        ingest_callable(descriptor_.ingest)(payload, dataset_path, descriptor_)
    finally:
        if temporary:
            payload.unlink(missing_ok=True)
    return meta


def update(
    fetcher: Callable[[str], dict] | None = None,
    progress: FetchProgress | None = None,
) -> list[dict]:
    """Reinstall every installed dataset that still has a descriptor."""
    results: list[dict] = []
    for dataset_id, meta in installed().items():
        if meta.get("descriptor_id") not in registry():
            continue  # legacy / unknown installs are never updated
        if dataset_dir(dataset_id).exists():
            results.append(install(dataset_id, refresh=True, fetcher=fetcher, progress=progress))
    return results


def reindex_all() -> list[dict]:
    """Rebuild every installed dataset index from its stored archive."""
    results: list[dict] = []
    for dataset_id, meta in installed().items():
        if meta.get("descriptor_id") in registry():
            results.append(reindex(dataset_id))
    return results


def status() -> list[dict]:
    """Return one row per installed dataset plus a trailing ``total`` row."""
    rows: list[dict] = []
    total = 0
    for dataset_id, meta in installed().items():
        dataset_path = dataset_dir(dataset_id)
        archive_bytes = meta.get("archive_bytes")
        index_bytes = meta.get("index_bytes")
        if index_bytes is None:
            index_bytes = index_size(dataset_path)
        if archive_bytes is None:
            asset_name = meta.get("asset") or ""
            archive = dataset_path / asset_name if asset_name else None
            archive_bytes = archive.stat().st_size if archive is not None and archive.exists() else 0
        size = archive_bytes + index_bytes
        total += size

        known = registry().get(meta.get("descriptor_id") or dataset_id)
        rows.append(
            {
                "name": dataset_id,
                "version": meta.get("version", ""),
                "archive_bytes": archive_bytes,
                "index_bytes": index_bytes,
                "size": size,
                "source_url": meta.get("source_url") or (known.homepage if known else ""),
                "license": meta.get("license") or (known.license if known else ""),
                "attribution": meta.get("attribution") or (known.attribution if known else ""),
                "dump_date": meta.get("dump_date") or (known.dump_date if known else ""),
                "descriptor_id": meta.get("descriptor_id"),
                "legacy": known is None,
            }
        )
    if rows:
        rows.append(
            {
                "name": "total",
                "version": "",
                "archive_bytes": sum(row["archive_bytes"] for row in rows),
                "index_bytes": sum(row["index_bytes"] for row in rows),
                "size": total,
            }
        )
    return rows
