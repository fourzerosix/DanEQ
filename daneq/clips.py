"""Optional clip library: public domain recordings fetched on demand.

Nothing is bundled in the repo. Clips are downloaded to ~/.cache/daneq/clips the first time
you ask for them. Add your own entries to ~/.config/daneq/clips.json:
  {"name": {"url": "https://...", "about": "what it is and why it is free to use"}}
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
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
    # Public domain movie dialogue (Wikimedia Commons). Clips marked "slice" are cut out of the full film on your
    # machine with ffmpeg (only that part is downloaded) and cached as a small WAV.
    "jazzsinger": {"url": _C + "Jolson-WaitAMinute.ogg",
                   "about": "The Jazz Singer (1927), Al Jolson: 'Wait a minute, you ain't heard nothin' yet' (about 1 min). Public domain (US, 1927 film)"},
    "barbra": {"url": _C + "Night_of_the_Living_Dead_(1968).webm", "start": 358, "length": 34,
               "about": "Night of the Living Dead (1968): 'They're coming to get you, Barbra!' (34 s). Public domain, no copyright notice"},
    "farmhouse": {"url": _C + "Night_of_the_Living_Dead_(1968).webm", "start": 1130, "length": 100,
                  "about": "Night of the Living Dead (1968): 'They know we're in here now' and boarding up the farmhouse (100 s). Public domain"},
    "fire": {"url": _C + "Night_of_the_Living_Dead_(1968).webm", "start": 1485, "length": 30,
             "about": "Night of the Living Dead (1968): 'They're afraid of fire. I found that out.' (30 s). Public domain"},
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


def slice_audio(url: str, dest: Path, start: float, length: float) -> Path:
    """Cut [start, start+length) out of a remote or local media file into a small WAV using ffmpeg."""
    if not shutil.which("ffmpeg"):
        raise ClipError("this clip is cut out of a full film and needs ffmpeg (install it, or use another clip)")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part.wav")
    cmd = ["ffmpeg", "-v", "error", "-y", "-ss", str(start), "-t", str(length), "-i", url, "-vn",
           "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le", str(tmp)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ClipError(f"could not cut the clip: {exc}")
    if r.returncode != 0 or not tmp.exists() or tmp.stat().st_size < 1000:
        raise ClipError("ffmpeg could not read the clip (no network, or the file moved): " + (r.stderr.strip()[-200:] or "unknown error"))
    tmp.replace(dest)
    return dest


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
    entry = lib.get(spec, {})
    if "start" in entry:
        dest = cache_dir() / f"{spec}.wav"
        return str(dest if dest.exists() else slice_audio(url, dest, float(entry["start"]), float(entry.get("length", 30))))
    name = os.path.basename(urllib.parse.urlparse(url).path) or "clip"
    dest = cache_dir() / (f"{spec}-{name}" if spec in lib else name)
    return str(dest if dest.exists() else download(url, dest))
