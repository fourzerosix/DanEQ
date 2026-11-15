"""File browser logic for the in-app 'open file' dialog (no curses here, so it is easy to test)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

from .player import PLAYLIST_EXTS, is_audio, natural_key


class Entry:
    def __init__(self, name: str, path: Path, is_dir: bool, size: int = 0):
        self.name, self.path, self.is_dir, self.size = name, path, is_dir, size


def human_size(n: int) -> str:
    for unit in ("B", "K", "M", "G"):
        if n < 1024 or unit == "G":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024.0
    return f"{n}B"


class Browser:
    def __init__(self, start: Optional[str] = None, show_hidden: bool = False):
        p = Path(os.path.expanduser(start)) if start else Path.home()
        if p.is_file():
            p = p.parent
        self.cwd = p if p.is_dir() else Path.home()
        self.show_hidden = show_hidden
        self.entries: List[Entry] = []
        self.idx = 0
        self.marked: List[Path] = []
        self.error = ""
        self.refresh()

    def refresh(self, keep: Optional[str] = None) -> None:
        self.error = ""
        entries: List[Entry] = []
        try:
            names = sorted(os.listdir(self.cwd), key=natural_key)
        except OSError as exc:
            names, self.error = [], str(exc)
        for n in names:
            if n.startswith(".") and not self.show_hidden:
                continue
            p = self.cwd / n
            try:
                if p.is_dir():
                    entries.append(Entry(n, p, True))
                elif is_audio(n) or p.suffix.lower() in PLAYLIST_EXTS:
                    entries.append(Entry(n, p, False, p.stat().st_size))
            except OSError:
                continue
        entries.sort(key=lambda e: (not e.is_dir,))      # directories first, natural order kept inside each group
        if self.cwd.parent != self.cwd:
            entries.insert(0, Entry("..", self.cwd.parent, True))
        self.entries = entries
        self.idx = 0
        if keep:
            for i, e in enumerate(entries):
                if e.name == keep:
                    self.idx = i
                    break

    def move(self, delta: int) -> None:
        if self.entries:
            self.idx = min(max(self.idx + delta, 0), len(self.entries) - 1)

    @property
    def current(self) -> Optional[Entry]:
        return self.entries[self.idx] if self.entries else None

    def go_up(self) -> None:
        child = self.cwd.name
        if self.cwd.parent != self.cwd:
            self.cwd = self.cwd.parent
            self.refresh(keep=child)

    def go_home(self) -> None:
        self.cwd = Path.home()
        self.refresh()

    def toggle_hidden(self) -> None:
        self.show_hidden = not self.show_hidden
        self.refresh(keep=self.current.name if self.current else None)

    def toggle_mark(self) -> None:
        e = self.current
        if e and not e.is_dir:
            if e.path in self.marked:
                self.marked.remove(e.path)
            else:
                self.marked.append(e.path)
            self.move(1)

    def activate(self):
        """Enter on the highlighted entry. Returns None (stayed in the browser) or (paths, start_index)."""
        e = self.current
        if e is None:
            return None
        if e.is_dir:
            if e.name == "..":
                self.go_up()
            else:
                self.cwd = e.path
                self.refresh()
            return None
        if self.marked:
            paths = [str(p) for p in self.marked]
            return paths, 0
        files = [x for x in self.entries if not x.is_dir]
        paths = [str(x.path) for x in files]
        return paths, paths.index(str(e.path))
