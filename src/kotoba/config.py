from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Literal

ConfigMode = Literal["local-first", "local-only", "api-only"]

_CONFIG_VERSION = 1

_DEFAULT = {
    "version": _CONFIG_VERSION,
    "lookup": "local-first",
    "ask_at_startup": True,
    "onboarding_done": False,
}


class ConfigError(Exception):
    pass


def _config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME")
    if base:
        return Path(base) / "kotoba"
    return Path.home() / ".config" / "kotoba"


def _config_path() -> Path:
    return _config_dir() / "config.json"


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)


def load() -> dict:
    path = _config_path()
    if not path.exists():
        return dict(_DEFAULT)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"corrupt config: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"cannot read config: {exc}") from exc

    if not isinstance(data, dict) or data.get("version") != _CONFIG_VERSION:
        raise ConfigError("config has unsupported version")

    # merge missing keys from defaults
    merged = dict(_DEFAULT)
    merged.update(data)
    # validate lookup value
    if merged.get("lookup") not in ("local-first", "local-only", "api-only"):
        merged["lookup"] = "local-first"
    return merged


def save(data: dict) -> None:
    path = _config_path()
    _ensure_dir(path.parent)
    data.setdefault("version", _CONFIG_VERSION)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".config.json.tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def mode() -> ConfigMode:
    cfg = load()
    value = cfg.get("lookup", "local-first")
    if value in ("local-first", "local-only", "api-only"):
        return value
    return "local-first"


def set_mode(value: ConfigMode) -> None:
    cfg = load()
    cfg["lookup"] = value
    save(cfg)


def onboarding_done(value: bool | None = None) -> bool:
    cfg = load()
    if value is not None:
        cfg["onboarding_done"] = value
        save(cfg)
    return cfg.get("onboarding_done", False)


def ask_at_startup(value: bool | None = None) -> bool:
    cfg = load()
    if value is not None:
        cfg["ask_at_startup"] = value
        save(cfg)
    return cfg.get("ask_at_startup", True)
