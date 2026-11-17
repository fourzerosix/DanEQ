"""Color capability fallbacks used by the curses theme system."""

import curses

from daneq.themes import THEMES
from daneq.ui import Colors


def test_theme_background_uses_black_on_basic_color_terminals(monkeypatch):
    colors = Colors.__new__(Colors)
    colors.use_bg = True
    colors.rich = False
    colors.default_bg = -1
    monkeypatch.setattr(curses, "COLORS", 8, raising=False)

    assert colors._bg_index(THEMES["classic"]) == curses.COLOR_BLACK


def test_theme_background_remains_transparent_when_disabled(monkeypatch):
    colors = Colors.__new__(Colors)
    colors.use_bg = False
    colors.rich = False
    colors.default_bg = -1
    monkeypatch.setattr(curses, "COLORS", 8, raising=False)

    assert colors._bg_index(THEMES["classic"]) == -1
