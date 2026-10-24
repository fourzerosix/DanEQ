"""Optional clip library: public domain recordings fetched on demand.

Nothing is bundled in the repo. Clips are downloaded to ~/.cache/daneq/clips the first time
you ask for them. Add your own entries to ~/.config/daneq/clips.json:
  {"name": {"url": "https://...", "about": "what it is and why it is free to use"}}
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

from . import config

# Built-in library. Entries here are fetched at runtime; see the README for sources and licensing notes.
_C = "https://commons.wikimedia.org/wiki/Special:FilePath/"
BUILTIN = {
    "moon": {"url": _C + "Neil_Armstrong_small_step.wav",
             "about": "Apollo 11, one small step (24 s). NASA, public domain (Wikimedia Commons)"},
    "infamy": {"url": _C + "Roosevelt_Infamy.ogg",
               "about": "FDR, 'a date which will live in infamy' (27 s). US government, public domain"},
    "fdr": {"url": _C + "Roosevelt_Pearl_Harbor.ogg",
            "about": "FDR, full 8 Dec 1941 address to Congress (8.7 min). US government, public domain"},
    "jfk": {"url": _C + "JFK_inaugural_address.ogg",
            "about": "JFK inaugural address, 20 Jan 1961 (14 min). US government, public domain"},
    "cuba": {"url": _C + "John_F_Kennedy_Address_on_the_Buildup_of_Arms_in_Cuba.ogg",
             "about": "JFK, Cuban Missile Crisis address, 22 Oct 1962 (17.6 min). US government, public domain"},
}


class ClipError(RuntimeError):
    pass


def cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return Path(base) / "daneq" / "clips"


def library() -> dict:
    lib = dict(BUILTIN)
    try:
        lib.update(json.loads(config.path().with_name("clips.json").read_text()))
    except (OSError, ValueError):
        pass
    return lib


def describe() -> str:
    lib = library()
    if not lib:
        return ("No clips configured. Use --clip PATH_OR_URL for any file you have the right to use,\n"
                "or add named entries to ~/.config/daneq/clips.json (see the README).")
    return "\n".join(f"{n:14s} {v.get('about', '')}" for n, v in sorted(lib.items()))


def download(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "DanEQ (+https://github.com/fourzerosix/DanEQ)"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r, open(dest.with_suffix(dest.suffix + ".part"), "wb") as f:
            while True:
                chunk = r.read(65536)
                if not chunk:
                    break
                f.write(chunk)
        dest.with_suffix(dest.suffix + ".part").replace(dest)
    except (OSError, ValueError) as exc:
        raise ClipError(f"download failed for {url}: {exc}")
    return dest


def resolve(spec: str) -> str:
    """Returns a local path for a library name, URL or file path."""
    if os.path.exists(spec):
        return spec
    lib = library()
    url = lib[spec]["url"] if spec in lib else (spec if spec.startswith(("http://", "https://")) else None)
    if url is None:
        raise ClipError(f"unknown clip '{spec}'. Try --list-clips, a file path or a URL.")
    name = os.path.basename(urllib.parse.urlparse(url).path) or "clip"
    dest = cache_dir() / (f"{spec}-{name}" if spec in lib else name)
    return str(dest if dest.exists() else download(url, dest))
