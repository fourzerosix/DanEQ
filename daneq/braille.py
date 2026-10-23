"""Braille drawing helpers (2x4 dots per terminal cell)."""
from __future__ import annotations

import numpy as np

# Dot bit for [sub_x][sub_y], sub_y 0 = top dot.
DOT = ((0x01, 0x02, 0x04, 0x40), (0x08, 0x10, 0x20, 0x80))

# Fill patterns, bottom-up, for the left and right dot column of a cell.
LEFT = np.array([0x00, 0x40, 0x44, 0x46, 0x47], dtype=np.uint32)
RIGHT = np.array([0x00, 0x80, 0xA0, 0xB0, 0xB8], dtype=np.uint32)
LCAP = np.array([0x40, 0x04, 0x02, 0x01], dtype=np.uint32)
RCAP = np.array([0x80, 0x20, 0x10, 0x08], dtype=np.uint32)


# Density ramp using braille dots only: SHADE[n] has n dots lit (0..8).
_ORDER = (0x40, 0x80, 0x04, 0x20, 0x02, 0x10, 0x01, 0x08)
SHADE = [chr(0x2800 | sum(_ORDER[:n])) for n in range(9)]


def _to_str(bits: np.ndarray) -> str:
    return (bits + 0x2800).astype("<u4").tobytes().decode("utf-32-le")


def bar_rows(levels: np.ndarray, caps: np.ndarray, h: int):
    """Render filled bars as braille rows (top row first).

    levels: int dot heights (0..4h), two entries per cell column.
    caps:   int dot index of a peak-hold dot per entry, or -1 for none.
    """
    left, right = levels[0::2], levels[1::2]
    cl, cr = caps[0::2], caps[1::2]
    rows = []
    for r in range(h - 1, -1, -1):
        base = 4 * r
        bits = LEFT[np.clip(left - base, 0, 4)] | RIGHT[np.clip(right - base, 0, 4)]
        for c, table in ((cl, LCAP), (cr, RCAP)):
            rel = c - base
            m = (rel >= 0) & (rel < 4)
            bits = bits | np.where(m, table[np.clip(rel, 0, 3)], 0).astype(np.uint32)
        rows.append(_to_str(bits))
    return rows


class Canvas:
    """A small braille dot canvas. y = 0 is the top dot row."""

    def __init__(self, w: int, h: int):
        self.w, self.h = w, h
        self.bits = [[0] * w for _ in range(h)]

    def set(self, x: int, y: int) -> None:
        if 0 <= x < self.w * 2 and 0 <= y < self.h * 4:
            self.bits[y >> 2][x >> 1] |= DOT[x & 1][y & 3]

    def line(self, x0: int, y0: int, x1: int, y1: int) -> None:
        dx, dy = abs(x1 - x0), -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        while True:
            self.set(x0, y0)
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy
