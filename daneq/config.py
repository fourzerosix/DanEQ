"""Tiny JSON config store (~/.config/daneq/config.json)."""
from __future__ import annotations

import json
import os
from pathlib import Path


def path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return Path(base) / "daneq" / "config.json"


def load() -> dict:
    try:
        return json.loads(path().read_text())
    except (OSError, ValueError):
        return {}


def save(cfg: dict) -> None:
    p = path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(cfg, indent=2))
        tmp.replace(p)
    except OSError:
        pass
