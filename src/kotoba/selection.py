from __future__ import annotations

import shutil
import subprocess


def initial_query(arg: str | None, *, use_selection: bool = False) -> str:
    if arg is not None:
        return _clean(arg)
    if not use_selection:
        return ""
    text = _paste("--primary") or _paste() or ""
    return _clean(text)


def _paste(flag: str = "") -> str | None:
    if not shutil.which("wl-paste"):
        return None
    cmd = ["wl-paste"]
    if flag:
        cmd.append(flag)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except Exception:
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def _clean(text: str) -> str:
    text = " ".join(text.split())
    text = text.splitlines()[0] if text else ""
    return text[:64]
