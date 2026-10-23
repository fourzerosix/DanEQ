"""btop-style curses interface: braille spectrum, faders, response curve, meters."""
from __future__ import annotations

import curses
import math
import os
import time

import numpy as np

from . import __version__
from collections import deque

from .braille import SHADE, Canvas, bar_rows
from .dsp import GAIN_MAX, GAIN_MIN, PRESET_ORDER, Spectrum, fmt_freq, preset_gains, to_apo

BW = 5            # columns per fader band
MIN_W, MIN_H = 80, 24
RANGE_DB = 50.0   # visible dynamic range of the spectrum
THEMES = {
    "classic": [46, 82, 118, 154, 190, 226, 220, 214, 208, 202, 196],
    "ice": [18, 19, 25, 31, 37, 43, 49, 86, 123, 159, 195],
    "fire": [52, 88, 124, 160, 196, 202, 208, 214, 220, 226, 230],
    "synthwave": [54, 55, 93, 129, 165, 201, 207, 213, 219, 225, 231],
    "mono": [238, 240, 242, 244, 246, 248, 250, 252, 254, 255, 231],
}
THEME_ORDER = list(THEMES)
VIEWS = ["Spectrum", "Waterfall", "Scope"]
HELP = [
    ("Left/Right  h/l", "select band"),
    ("Up/Down  k/j", "gain +/- 0.5 dB"),
    ("PgUp/PgDn  K/J", "gain +/- 3 dB"),
    ("0", "zero selected band"),
    ("r", "reset bands and preamp"),
    ("b", "bypass (A/B compare)"),
    ("p / P", "next / previous preset"),
    ("[ / ]", "preamp -/+ 0.5 dB"),
    ("a", "auto headroom (no clipping)"),
    ("v", "view: spectrum/waterfall/scope"),
    ("c", "color theme"),
    ("t", "spectrum tilt on/off"),
    (", / .", "spectrum sensitivity"),
    ("m", "mute"),
    ("e", "export Equalizer APO text"),
    ("s", "save settings"),
    ("?", "this help"),
    ("q", "quit"),
]
GRAD_8 = [2, 2, 3, 3, 1]


class Colors:
    def __init__(self, theme="classic"):
        curses.start_color()
        try:
            curses.use_default_colors()
            bg = -1
        except curses.error:
            bg = curses.COLOR_BLACK
        rich = curses.COLORS >= 256
        self.bg, self.rich = bg, rich
        self.set_theme(theme)

        def mk(n, fg_rich, fg_basic, extra=0):
            curses.init_pair(n, fg_rich if rich else fg_basic, bg)
            return curses.color_pair(n) | (0 if rich else extra)

        self.border = mk(30, 244, 7, curses.A_DIM)
        self.title = mk(31, 51, 6) | curses.A_BOLD
        self.accent = mk(32, 213, 5) | curses.A_BOLD
        self.dim = mk(33, 240, 7, curses.A_DIM)
        self.ok = mk(34, 46, 2)
        self.warn = mk(35, 196, 1) | curses.A_BOLD
        self.curve = mk(36, 45, 6) | curses.A_BOLD
        self.text = mk(37, 252, 7)

    def set_theme(self, name):
        self.theme = name if name in THEMES else "classic"
        self.grad = []
        for i, c in enumerate(THEMES[self.theme] if self.rich else GRAD_8):
            curses.init_pair(i + 1, c, self.bg)
            self.grad.append(curses.color_pair(i + 1))

    def at(self, frac: float) -> int:
        frac = min(max(frac, 0.0), 1.0)
        return self.grad[int(frac * (len(self.grad) - 1) + 0.5)]


class App:
    def __init__(self, scr, engine, eq, cfg, info, mouse=True):
        self.scr, self.engine, self.eq, self.cfg, self.info = scr, engine, eq, cfg, info
        self.sel = 0
        self.spec = Spectrum(engine.rate, engine.nfft)
        self.tilt = float(cfg.get("tilt", 3.0))
        self.ceil = float(cfg.get("ceil", -10.0))
        self.lvl = np.zeros(0)
        self.cap = np.zeros(0)
        self.rms_db = np.full(2, -90.0)
        self.pk_db = np.full(2, -90.0)
        self.view = int(cfg.get("view", 0)) % len(VIEWS)
        self.hist = deque(maxlen=128)
        self.tick = 0
        self.scope_amp = 0.25
        self.show_help = False
        self.msg, self.msg_until = "", 0.0
        self.preset = "Custom"
        for name in PRESET_ORDER:
            if preset_gains(name, eq.freqs) == list(eq.gains):
                self.preset = name
        self.drag = False
        self.fader = (0, 0, 0)
        self.H = self.W = 0
        self.fmin = 30.0
        curses.curs_set(0) if hasattr(curses, "curs_set") else None
        self.scr.keypad(True)
        self.scr.timeout(33)
        if mouse:
            try:
                curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)
            except curses.error:
                pass
        self.c = Colors(cfg.get("theme", "classic"))

    # ---- drawing primitives -----------------------------------------------
    def put(self, y, x, s, attr=0):
        if y < 0 or y >= self.H or x >= self.W or not s:
            return
        if x < 0:
            s, x = s[-x:], 0
        s = s[: self.W - x]
        if y == self.H - 1 and x + len(s) >= self.W:
            s = s[: self.W - x - 1]
        try:
            self.scr.addstr(y, x, s, attr)
        except curses.error:
            pass

    def box(self, y, x, h, w, title="", right=""):
        if h < 3 or w < 6:
            return
        b = self.c.border
        self.put(y, x, "╭" + "─" * (w - 2) + "╮", b)
        for r in range(1, h - 1):
            self.put(y + r, x, "│", b)
            self.put(y + r, x + w - 1, "│", b)
        self.put(y + h - 1, x, "╰" + "─" * (w - 2) + "╯", b)
        if title:
            self.put(y, x + 2, "┤", b)
            self.put(y, x + 3, title, self.c.title)
            self.put(y, x + 3 + len(title), "├", b)
        if right:
            rx = x + w - 3 - len(right)
            self.put(y, rx - 1, "┤", b)
            self.put(y, rx, right, self.c.text)
            self.put(y, rx + len(right), "├", b)

    # ---- state updates ------------------------------------------------------
    def update_meters(self):
        peak, rms = self.engine.take_meter()
        to_db = lambda v: 20.0 * np.log10(np.maximum(v, 1e-5))  # noqa: E731
        self.rms_db = np.maximum(to_db(rms), self.rms_db - 1.2)
        self.pk_db = np.maximum(to_db(peak), self.pk_db - 0.5)

    def update_bars(self, nbars, hi):
        raw = self.spec.bars(self.engine.snapshot(), nbars, self.fmin, hi, self.tilt)
        floor = self.ceil - RANGE_DB
        new = np.clip((raw - floor) / (self.ceil - floor), 0.0, 1.0)
        if len(self.lvl) != nbars:
            self.lvl, self.cap = np.zeros(nbars), np.zeros(nbars)
        rising = new > self.lvl
        self.lvl = np.where(rising, self.lvl + (new - self.lvl) * 0.65, self.lvl + (new - self.lvl) * 0.18)
        self.cap = np.maximum(self.lvl, self.cap - 0.012)

    # ---- panels ----------------------------------------------------------------
    def draw_header(self):
        e, eq = self.engine, self.eq
        self.put(0, 1, f" DanEQ v{__version__} ", self.c.title)
        self.put(0, 20, self.info, self.c.dim)
        chips = []
        if time.time() - e.last_clip < 2.0:
            chips.append(("CLIP", self.c.warn))
        if e.muted:
            chips.append(("MUTE", self.c.warn))
        chips.append(("BYPASS" if eq.bypass else "EQ ON", self.c.warn if eq.bypass else self.c.ok))
        chips.append((f"dsp {e.load * 100:3.0f}%", self.c.text))
        if e.latency_ms:
            chips.append((f"lat ~{e.latency_ms:.0f}ms", self.c.text))
        x = self.W - 2
        for text, attr in reversed(chips):
            x -= len(text) + 2
            self.put(0, x, f"[{text}]", attr)

    def flash(self, text, secs=3.0):
        self.msg, self.msg_until = text, time.time() + secs

    def draw_footer(self):
        if time.time() < self.msg_until:
            self.put(self.H - 1, 1, self.msg, self.c.accent)
            return
        keys = ("? help  </> band  ^/v gain  b bypass  p preset  a headroom  v view  "
                "c theme  e export  m mute  s save  q quit")
        self.put(self.H - 1, 1, keys, self.c.dim)

    def draw_spectrum(self, y, x, h, w):
        eq = self.eq
        f = eq.freqs[self.sel]
        tag = "bypass" if eq.bypass else "post-EQ"
        self.box(y, x, h, w, f"{VIEWS[self.view]} {tag}",
                 f"band {self.sel + 1}/{eq.nbands}: {fmt_freq(f)}Hz {eq.gains[self.sel]:+.1f}dB")
        iy, ix, ih, iw = y + 1, x + 1, h - 2, w - 2
        sw = 5
        bw, bh = iw - sw, ih - 2
        if bw < 10 or bh < 3:
            return
        hi = min(18000.0, self.engine.rate / 2 * 0.95)
        self.update_bars(bw * 2, hi)
        if self.view == 0:
            levels = np.clip((self.lvl * bh * 4).astype(int), 0, bh * 4)
            caps = np.clip((self.cap * bh * 4).astype(int), 0, bh * 4 - 1)
            caps = np.where(self.cap < 0.02, -1, caps)
            rows = bar_rows(levels, caps, bh)
            for i, row in enumerate(rows):
                self.put(iy + i, ix + sw, row, self.c.at((bh - 1 - i) / max(bh - 1, 1)))
        elif self.view == 1:
            self.draw_waterfall(iy, ix + sw, bw, bh)
        else:
            self.draw_scope(iy, ix + sw, bw, bh)
        floor = self.ceil - RANGE_DB
        for k in range(5):
            i = round(k * (bh - 1) / 4)
            if self.view == 0:
                label = f"{self.ceil - (self.ceil - floor) * i / max(bh - 1, 1):4.0f}"
            elif self.view == 2:
                label = f"{self.scope_amp * (1 - 2 * i / max(bh - 1, 1)):+4.2f}"[:5]
            else:
                label = "now " if k == 0 else ("past" if k == 4 else "")
            self.put(iy + i, ix, label, self.c.dim)

        def xpos(freq):
            return ix + sw + int(round(math.log(freq / self.fmin) / math.log(hi / self.fmin) * (bw - 1)))

        last = -1
        for freq in (50, 100, 200, 500, 1000, 2000, 5000, 10000):
            if freq > hi:
                continue
            label = fmt_freq(freq)
            px = xpos(freq) - len(label) // 2
            if px > last:
                self.put(iy + bh, px, label, self.c.dim)
                last = px + len(label)
        for i, freq in enumerate(eq.freqs):
            px = min(max(xpos(min(max(freq, self.fmin), hi)), ix + sw), ix + sw + bw - 1)
            sel = i == self.sel
            self.put(iy + bh + 1, px, "▲", self.c.accent if sel else self.c.dim)

    def draw_waterfall(self, iy, ix, bw, bh):
        self.tick += 1
        if self.tick % 2 == 0 or not self.hist:
            self.hist.appendleft(self.lvl.reshape(-1, 2).max(axis=1).copy())
        n_grad = len(self.c.grad)
        for i in range(min(bh, len(self.hist))):
            v = self.hist[i]
            if len(v) != bw:
                continue
            dots = np.minimum((v * 9).astype(int), 8)
            ci = np.minimum((v * (n_grad - 1) + 0.5).astype(int), n_grad - 1)
            j = 0
            while j < bw:
                k = j
                while k < bw and ci[k] == ci[j]:
                    k += 1
                self.put(iy + i, ix + j, "".join(SHADE[d] for d in dots[j:k]), self.c.grad[ci[j]])
                j = k

    def draw_scope(self, iy, ix, bw, bh):
        x = self.engine.snapshot()
        n = bw * 2
        chunk = max(len(x) // n, 1)
        seg = x[: chunk * n].reshape(n, chunk)
        mn, mx = seg.min(axis=1), seg.max(axis=1)
        self.scope_amp = max(float(np.abs(x).max()), 0.05, self.scope_amp * 0.97)
        dh = bh * 4 - 1
        yof = lambda v: int(round((1.0 - min(max(v / self.scope_amp, -1.0), 1.0)) / 2.0 * dh))  # noqa: E731
        wave, mid = Canvas(bw, bh), Canvas(bw, bh)
        for xd in range(0, n, 4):
            mid.set(xd, dh // 2)
        for xd in range(n):
            wave.line(xd, yof(float(mx[xd])), xd, yof(float(mn[xd])))
        for r in range(bh):
            base = "".join(chr(0x2800 | mid.bits[r][c] | wave.bits[r][c]) for c in range(bw))
            self.put(iy + r, ix, base, self.c.dim)
            for c in range(bw):
                if wave.bits[r][c]:
                    self.put(iy + r, ix + c, chr(0x2800 | wave.bits[r][c] | mid.bits[r][c]), self.c.curve)

    def draw_help(self):
        w, h = 54, len(HELP) + 4
        y, x = max((self.H - h) // 2, 0), max((self.W - w) // 2, 0)
        for r in range(h):
            self.put(y + r, x, " " * w)
        self.box(y, x, h, w, "DanEQ keys", "any key closes")
        for i, (k, d) in enumerate(HELP):
            self.put(y + 2 + i, x + 3, k, self.c.accent)
            self.put(y + 2 + i, x + 21, d, self.c.text)

    def draw_faders(self, y, x, h, w):
        eq = self.eq
        self.box(y, x, h, w, f"Equalizer {eq.nbands}-band", f"preset: {self.preset}")
        iy, ix, ih = y + 1, x + 1, h - 2
        nt = ih - 2
        if nt % 2 == 0:
            nt -= 1
        if nt < 3:
            return
        tc = nt // 2
        self.fader = (iy + 1, ix, nt)
        off = eq.bypass
        for i in range(eq.nbands):
            cx = ix + i * BW + 2
            g, sel = eq.gains[i], i == self.sel
            t = int(round((GAIN_MAX - g) / (GAIN_MAX - GAIN_MIN) * (nt - 1)))
            gtxt = f"{g:+g}" if g else "0"
            self.put(iy, cx - len(gtxt) // 2, gtxt, self.c.accent if sel else self.c.text)
            fill = self.c.dim if off else (self.c.at(abs(g) / GAIN_MAX) if g > 0 else self.c.curve)
            for j in range(nt):
                ry = iy + 1 + j
                if j == tc:
                    self.put(ry, cx - 1, "┈┼┈", self.c.dim)
                else:
                    self.put(ry, cx, "│", self.c.dim)
                if (g > 0 and t <= j < tc) or (g < 0 and tc < j <= t):
                    self.put(ry, cx, "┃", fill)
            knob = self.c.accent if sel else fill
            if off and not sel:
                knob = self.c.dim
            self.put(iy + 1 + t, cx - 1, "▐█▌", knob)
            lab = fmt_freq(eq.freqs[i])
            self.put(iy + ih - 1, cx - len(lab) // 2, lab,
                     (self.c.accent | curses.A_REVERSE) if sel else self.c.dim)

    def draw_response(self, y, x, h, w):
        eq = self.eq
        self.box(y, x, h, w, "Response", "bypass" if eq.bypass else f"preamp {eq.preamp:+.1f}dB")
        iy, ix, ih, iw = y + 1, x + 1, h - 2, w - 2
        sw = 4
        cw, ch = iw - sw, ih - 1
        if cw < 8 or ch < 3:
            return
        fmin, fmax = 20.0, min(20000.0, eq.rate / 2 * 0.98)
        n = cw * 2
        freqs = fmin * (fmax / fmin) ** (np.arange(n) / (n - 1))
        db = eq.response_db(freqs)
        rng, dh = 15.0, ch * 4 - 1
        yof = lambda d: int(round((rng - min(max(d, -rng), rng)) / (2 * rng) * dh))  # noqa: E731
        grid, sel, curve = Canvas(cw, ch), Canvas(cw, ch), Canvas(cw, ch)
        for d, step in ((0, 2), (6, 4), (-6, 4), (12, 8), (-12, 8)):
            for xd in range(0, n, step):
                grid.set(xd, yof(d))
        for i, f in enumerate(eq.freqs):
            xd = int(round(math.log(f / fmin) / math.log(fmax / fmin) * (n - 1)))
            target = sel if i == self.sel else grid
            for yd in range(0, ch * 4, 2 if i == self.sel else 4):
                target.set(xd, yd)
        prev = None
        for xd in range(n):
            pt = (xd, yof(float(db[xd])))
            if prev:
                curve.line(prev[0], prev[1], pt[0], pt[1])
            prev = pt
        for r in range(ch):
            base = "".join(chr(0x2800 | grid.bits[r][c] | sel.bits[r][c] | curve.bits[r][c]) for c in range(cw))
            self.put(iy + r, ix + sw, base, self.c.dim)
            for c in range(cw):
                ch_bits = grid.bits[r][c] | sel.bits[r][c] | curve.bits[r][c]
                if curve.bits[r][c]:
                    self.put(iy + r, ix + sw + c, chr(0x2800 | ch_bits), self.c.curve)
                elif sel.bits[r][c]:
                    self.put(iy + r, ix + sw + c, chr(0x2800 | ch_bits), self.c.accent)
        for d in (12, 6, 0, -6, -12):
            self.put(iy + min(yof(d) // 4, ch - 1), ix, f"{d:+d}" if d else " 0", self.c.dim)
        last = -1
        for freq in (50, 100, 200, 500, 1000, 2000, 5000, 10000):
            if freq > fmax:
                continue
            label = fmt_freq(freq)
            px = ix + sw + int(round(math.log(freq / fmin) / math.log(fmax / fmin) * (cw - 1))) - len(label) // 2
            if px > last:
                self.put(iy + ch, px, label, self.c.dim)
                last = px + len(label)

    def draw_meters(self, y, x, h, w):
        self.box(y, x, h, w, "Levels", "dBFS")
        bx = x + 4
        bar_w = w - 4 - 10
        if bar_w < 6:
            return
        for k, name in enumerate("LR"):
            row = y + 1 + k
            self.put(row, x + 2, name, self.c.title)
            v = min(max((self.rms_db[k] + 60.0) / 60.0, 0.0), 1.0) * bar_w
            full = int(v)
            for i in range(min(full, bar_w)):
                self.put(row, bx + i, "█", self.c.at(i / (bar_w - 1)))
            rem = int((v - full) * 8)
            if rem and full < bar_w:
                self.put(row, bx + full, " ▏▎▍▌▋▊▉"[rem], self.c.at(full / (bar_w - 1)))
            pk = int(min(max((self.pk_db[k] + 60.0) / 60.0, 0.0), 1.0) * (bar_w - 1))
            if pk >= full:
                self.put(row, bx + pk, "│", self.c.text | curses.A_BOLD)
            hot = self.pk_db[k] >= -0.1
            self.put(row, bx + bar_w + 1, f"{self.pk_db[k]:6.1f}", self.c.warn if hot else self.c.text)

    def draw(self):
        self.scr.erase()
        self.H, self.W = self.scr.getmaxyx()
        need_w = max(MIN_W, self.eq.nbands * BW + 2 + 26)
        if self.H < MIN_H or self.W < need_w:
            self.put(0, 0, f"DanEQ needs at least {need_w}x{MIN_H}; this terminal is {self.W}x{self.H}", self.c.warn)
            self.scr.refresh()
            return
        self.update_meters()
        self.draw_header()
        body_h = self.H - 2
        bottom_h = max(11, int(body_h * 0.5))
        spec_h = body_h - bottom_h
        self.draw_spectrum(1, 0, spec_h, self.W)
        fw = self.eq.nbands * BW + 2
        by = 1 + spec_h
        self.draw_faders(by, 0, bottom_h, fw)
        rw = self.W - fw
        self.draw_response(by, fw, bottom_h - 4, rw)
        self.draw_meters(by + bottom_h - 4, fw, 4, rw)
        self.draw_footer()
        if self.show_help:
            self.draw_help()
        self.scr.refresh()

    # ---- input ----------------------------------------------------------------
    def nudge(self, d, i=None):
        i = self.sel if i is None else i
        self.set_band(i, round((self.eq.gains[i] + d) * 2) / 2)

    def set_band(self, i, g):
        self.eq.set_gain(i, g)
        self.preset = "Custom"

    def cycle_preset(self, step):
        cur = PRESET_ORDER.index(self.preset) if self.preset in PRESET_ORDER else -1
        name = PRESET_ORDER[(cur + step) % len(PRESET_ORDER)]
        self.eq.set_gains(preset_gains(name, self.eq.freqs))
        self.preset = name

    def on_mouse(self):
        try:
            _, mx, my, _, st = curses.getmouse()
        except curses.error:
            return
        ty, ix, nt = self.fader
        if nt < 3:
            return
        band = (mx - ix) // BW
        inside = 0 <= band < self.eq.nbands and ty - 1 <= my <= ty + nt
        wheel_up = st & getattr(curses, "BUTTON4_PRESSED", 0)
        wheel_dn = st & getattr(curses, "BUTTON5_PRESSED", 0)
        if wheel_up or wheel_dn:
            i = band if inside else self.sel
            self.sel = i
            self.nudge(0.5 if wheel_up else -0.5, i)
            return
        if st & curses.BUTTON1_RELEASED:
            self.drag = False
            return
        if st & getattr(curses, "BUTTON1_DOUBLE_CLICKED", 0) and inside:
            self.sel = band
            self.set_band(band, 0.0)
            return
        pressed = st & (curses.BUTTON1_PRESSED | curses.BUTTON1_CLICKED)
        if (pressed or (self.drag and st & curses.REPORT_MOUSE_POSITION)) and inside:
            self.sel = band
            row = min(max(my - ty, 0), nt - 1)
            self.set_band(band, round((GAIN_MAX - row / (nt - 1) * (GAIN_MAX - GAIN_MIN)) * 2) / 2)
            self.drag = bool(pressed) or self.drag

    def on_key(self, k) -> bool:
        n = self.eq.nbands
        if self.show_help:
            self.show_help = False
            return True
        if k in (ord("q"), ord("Q")):
            return False
        if k == ord("?"):
            self.show_help = True
            return True
        if k in (curses.KEY_LEFT, ord("h")):
            self.sel = (self.sel - 1) % n
        elif k in (curses.KEY_RIGHT, ord("l")):
            self.sel = (self.sel + 1) % n
        elif k == curses.KEY_HOME:
            self.sel = 0
        elif k == curses.KEY_END:
            self.sel = n - 1
        elif k in (curses.KEY_UP, ord("k")):
            self.nudge(0.5)
        elif k in (curses.KEY_DOWN, ord("j")):
            self.nudge(-0.5)
        elif k in (curses.KEY_PPAGE, ord("K")):
            self.nudge(3.0)
        elif k in (curses.KEY_NPAGE, ord("J")):
            self.nudge(-3.0)
        elif k == ord("0"):
            self.set_band(self.sel, 0.0)
        elif k == ord("r"):
            self.eq.set_gains([0.0] * n)
            self.eq.set_preamp(0.0)
            self.preset = "Flat"
        elif k == ord("b"):
            self.eq.set_bypass(not self.eq.bypass)
        elif k == ord("m"):
            self.engine.muted = not self.engine.muted
        elif k == ord("p"):
            self.cycle_preset(1)
        elif k == ord("P"):
            self.cycle_preset(-1)
        elif k == ord("["):
            self.eq.set_preamp(self.eq.preamp - 0.5)
        elif k == ord("]"):
            self.eq.set_preamp(self.eq.preamp + 0.5)
        elif k == ord("t"):
            self.tilt = 0.0 if self.tilt else 3.0
        elif k == ord("."):
            self.ceil = max(-40.0, self.ceil - 5.0)
        elif k == ord(","):
            self.ceil = min(0.0, self.ceil + 5.0)
        elif k == ord("s"):
            self.save()
            self.flash("settings saved")
        elif k == ord("v"):
            self.view = (self.view + 1) % len(VIEWS)
            self.hist.clear()
        elif k == ord("c"):
            nxt = THEME_ORDER[(THEME_ORDER.index(self.c.theme) + 1) % len(THEME_ORDER)]
            self.c.set_theme(nxt)
            self.flash(f"theme: {nxt}")
        elif k == ord("a"):
            self.flash(f"auto headroom: preamp {self.eq.auto_headroom():+.1f} dB")
        elif k == ord("e"):
            self.export()
        elif k == curses.KEY_MOUSE:
            self.on_mouse()
        return True

    def state(self) -> dict:
        gains = dict(self.cfg.get("gains", {}))
        gains[str(self.eq.nbands)] = list(self.eq.gains)
        return {**self.cfg, "bands": self.eq.nbands, "gains": gains, "preamp": self.eq.preamp,
                "tilt": self.tilt, "ceil": self.ceil, "theme": self.c.theme, "view": self.view}

    def save(self):
        from . import config
        config.save(self.state())

    def export(self):
        from . import config
        path = config.path().with_name(f"daneq-{self.eq.nbands}band.apo.txt")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(to_apo(self.eq))
            self.flash(f"exported {path}", 5.0)
        except OSError as exc:
            self.flash(f"export failed: {exc}", 5.0)

    def run(self):
        while True:
            if self.engine.error or self.engine.finished:
                return
            self.draw()
            k = self.scr.getch()
            if k != -1 and not self.on_key(k):
                return


def run(engine, eq, cfg, info, mouse=True):
    """Runs the TUI, returns the final state dict to persist."""
    os.environ.setdefault("ESCDELAY", "25")
    out = {}

    def main(scr):
        app = App(scr, engine, eq, cfg, info, mouse)
        try:
            app.run()
        finally:
            out.update(app.state())

    curses.wrapper(main)
    return out
