"""Braille drawing helpers (2x4 dots per terminal cell), numpy backed."""
from __future__ import annotations

import numpy as np

# Weight of the dot at [sub_y][sub_x] inside a braille cell.
WEIGHT = np.array([[0x01, 0x08], [0x02, 0x10], [0x04, 0x20], [0x40, 0x80]], dtype=np.uint32)

# Fill patterns, bottom-up, for the left and right dot column of a cell.
LEFT = np.array([0x00, 0x40, 0x44, 0x46, 0x47], dtype=np.uint32)
RIGHT = np.array([0x00, 0x80, 0xA0, 0xB0, 0xB8], dtype=np.uint32)
LCAP = np.array([0x40, 0x04, 0x02, 0x01], dtype=np.uint32)
RCAP = np.array([0x80, 0x20, 0x10, 0x08], dtype=np.uint32)

# Density ramp using braille dots only: SHADE[n] has n dots lit (0..8).
_ORDER = (0x40, 0x80, 0x04, 0x20, 0x02, 0x10, 0x01, 0x08)
SHADE = [chr(0x2800 | sum(_ORDER[:n])) for n in range(9)]


def to_str(bits: np.ndarray) -> str:
    return (np.asarray(bits, dtype=np.uint32) + 0x2800).astype("<u4").tobytes().decode("utf-32-le")


def bar_rows(levels: np.ndarray, caps: np.ndarray, h: int):
    """Filled bars as braille rows (top row first).

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
        rows.append(to_str(bits))
    return rows


class Canvas:
    """Boolean dot grid. (0, 0) is the top-left dot."""

    def __init__(self, w: int, h: int):
        self.w, self.h = w, h
        self.a = np.zeros((h * 4, w * 2), dtype=bool)

    def clear(self):
        self.a[:] = False

    def set(self, x, y):
        if 0 <= x < self.w * 2 and 0 <= y < self.h * 4:
            self.a[int(y), int(x)] = True

    def points(self, xs, ys):
        xs = np.rint(np.asarray(xs)).astype(int)
        ys = np.rint(np.asarray(ys)).astype(int)
        m = (xs >= 0) & (xs < self.w * 2) & (ys >= 0) & (ys < self.h * 4)
        self.a[ys[m], xs[m]] = True

    def line(self, x0, y0, x1, y1):
        n = int(max(abs(x1 - x0), abs(y1 - y0))) + 1
        self.points(np.linspace(x0, x1, n), np.linspace(y0, y1, n))

    def vspan(self, x, y0, y1):
        x = int(x)
        if not 0 <= x < self.w * 2:
            return
        y0, y1 = int(round(min(y0, y1))), int(round(max(y0, y1)))
        self.a[max(y0, 0):min(y1, self.h * 4 - 1) + 1, x] = True

    def hspan(self, y, x0, x1):
        y = int(round(y))
        if not 0 <= y < self.h * 4:
            return
        x0, x1 = int(round(min(x0, x1))), int(round(max(x0, x1)))
        self.a[y, max(x0, 0):min(x1, self.w * 2 - 1) + 1] = True

    def circle(self, cx, cy, r, a0=0.0, a1=2 * np.pi):
        n = max(int(r * abs(a1 - a0) * 1.6), 12)
        ang = np.linspace(a0, a1, n)
        self.points(cx + r * np.cos(ang), cy + r * np.sin(ang))

    def disc(self, cx, cy, r):
        for yy in range(int(cy - r), int(cy + r) + 1):
            dx = max(r * r - (yy - cy) ** 2, 0.0) ** 0.5
            self.hspan(yy, cx - dx, cx + dx)

    def bits(self) -> np.ndarray:
        a = self.a.reshape(self.h, 4, self.w, 2).astype(np.uint32)
        return (a * WEIGHT[None, :, None, :]).sum(axis=(1, 3))

    def bands(self, k: int):
        """Split into k horizontal band canvases (top to bottom) for gradients."""
        out, rows = [], self.h
        for i in range(k):
            c = Canvas(self.w, self.h)
            r0, r1 = rows * i // k * 4, rows * (i + 1) // k * 4
            c.a[r0:r1] = self.a[r0:r1]
            out.append(c)
        return out


def blit(put, iy, ix, layers):
    """Draw canvases bottom to top. layers: [(Canvas, attr)]. Top-most dot colors a cell."""
    if not layers:
        return
    h, w = layers[0][0].h, layers[0][0].w
    union = np.zeros((h, w), dtype=np.uint32)
    top = np.zeros((h, w), dtype=np.int32)
    for i, (cv, _) in enumerate(layers):
        b = cv.bits()
        union |= b
        top[b > 0] = i + 1
    attrs = [None] + [a for _, a in layers]
    for r in range(h):
        tl = top[r].tolist()
        if not any(tl):
            continue
        s = to_str(union[r])
        c = 0
        while c < w:
            k = tl[c]
            if k == 0:
                c += 1
                continue
            e = c + 1
            while e < w and tl[e] == k:
                e += 1
            put(iy + r, ix + c, s[c:e], attrs[k])
            c = e
