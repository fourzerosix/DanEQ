"""btop-style curses interface for DanEQ."""
from __future__ import annotations

import curses
import math
import os
import time
from collections import deque

import numpy as np

from . import __version__, visuals
from .braille import Canvas, blit
from .dsp import GAIN_MAX, GAIN_MIN, PRESET_ORDER, Spectrum, fmt_freq, preset_gains, to_apo
from .nerd import Collector, NerdView
from .themes import STEPS, THEME_ORDER, THEMES, gradient, rgb_to_256

MIN_H = 24
RANGE_DB = 44.0
GRAD_8 = [2, 2, 3, 3, 1, 1]
RIP = "R.I.P. D.J.E. [08/13/1976 - 11/01/2011]"
VIEWS = ["Spectrum"]          # filled in by App (visual names follow)
HELP = [
    ("Esc", "menu (like btop)"),
    ("Left/Right h/l", "select band / knob"), ("Up/Down k/j", "gain / knob +- fine"),
    ("PgUp/PgDn K/J", "gain / knob +- coarse"), ("0", "zero band / reset knob"),
    ("r", "reset all (FX: reset effect)"), ("b", "bypass EQ (FX mode: rack)"),
    ("p / P", "next / previous EQ preset"), ("[ / ]", "preamp -/+ 0.5 dB"),
    ("a", "auto headroom"), ("f", "toggle FX rack"),
    ("Tab / 1-9", "FX: next effect / pick"), ("o / Space", "FX: effect on/off"),
    ("v / V", "next / previous view"), ("g", "spectrum bar style"),
    ("c / C", "next / previous theme"), ("t", "spectrum tilt"), (", / .", "spectrum sensitivity"),
    ("( / )", "bottom panel shorter / taller"), ("{ / }", "faders narrower / wider"),
    ("n", "nerd mode (audio processes)"), ("m", "mute"), ("e", "export Equalizer APO text"),
    ("s", "save settings"), ("?", "this help"), ("q", "quit"),
    ("mouse", "click/drag faders, wheel, drag panel borders"),
]


class Colors:
    def __init__(self, theme="classic"):
        curses.start_color()
        try:
            curses.use_default_colors()
            self.bg = -1
        except curses.error:
            self.bg = curses.COLOR_BLACK
        self.rich = curses.COLORS >= 256
        self.theme = "classic"

        def mk(n, fg_rich, fg_basic, extra=0):
            curses.init_pair(n, fg_rich if self.rich else fg_basic, self.bg)
            return curses.color_pair(n) | (0 if self.rich else extra)

        self.border = mk(60, 244, 7, curses.A_DIM)
        self.title = mk(61, 51, 6) | curses.A_BOLD
        self.dim = mk(63, 240, 7, curses.A_DIM)
        self.ok = mk(64, 46, 2)
        self.warn = mk(65, 196, 1) | curses.A_BOLD
        self.text = mk(67, 252, 7)
        self.set_theme(theme)

    def set_theme(self, name):
        self.theme = name if name in THEMES else "classic"
        th = THEMES[self.theme]
        idx = gradient(th["a"], STEPS) if self.rich else GRAD_8
        self.grad = []
        for i, c in enumerate(idx):
            curses.init_pair(i + 1, c, self.bg)
            self.grad.append(curses.color_pair(i + 1))
        curses.init_pair(62, rgb_to_256(*th["accent"]) if self.rich else 5, self.bg)
        curses.init_pair(66, rgb_to_256(*th["curve"]) if self.rich else 6, self.bg)
        self.accent = curses.color_pair(62) | curses.A_BOLD
        self.curve = curses.color_pair(66) | curses.A_BOLD
        self.fill_up, self.fill_dn = self.at(0.78), self.at(0.12)

    def at(self, frac):
        frac = min(max(frac, 0.0), 1.0)
        return self.grad[int(frac * (len(self.grad) - 1) + 0.5)]


class App:
    def __init__(self, scr, engine, eq, fx, cfg, info, mouse=True, collector=None):
        self.scr, self.engine, self.eq, self.fx, self.cfg, self.info = scr, engine, eq, fx, cfg, info
        self.vis = visuals.make_all()
        self.view_names = ["Spectrum"] + [v.name for v in self.vis]
        self.view = self._pick(cfg.get("view"), self.view_names)
        self.style = max(visuals.STYLES.index(cfg.get("style", "braille")) if cfg.get("style") in visuals.STYLES else 0, 0)
        self.sel, self.fsel, self.kidx = 0, 0, 0
        self.mode = "eq"
        self.spec = Spectrum(engine.rate, engine.nfft)
        self.tilt = float(cfg.get("tilt", 3.0))
        self.ceil = float(cfg.get("ceil", -10.0))
        self.lvl = np.zeros(0)
        self.disp = np.zeros(0)
        self.cap = np.zeros(0)
        self.capv = np.zeros(0)
        self.bass_avg = 0.0
        self.rms_db = np.full(2, -90.0)
        self.pk_db = np.full(2, -90.0)
        self.bottom_h = cfg.get("bottom_h")
        self.bw = int(cfg.get("bw", 5))
        self.fps = float(cfg.get("fps", 60))
        self.fps_now = 0.0
        self.t = 0.0
        self.dt = 1 / 60.0
        self.show_help = False
        self.menu = None                      # stack of [title, builder, index]
        self.menu_rect = (0, 0, 0, 0, 0)
        self.msg, self.msg_until = "", 0.0
        self.drag = None
        self.lay = {}
        self.fader = (0, 0, 0)
        self.tabs, self.knobs = [], []
        self.fmin = 30.0
        self.preset = "Custom"
        for name in PRESET_ORDER:
            if preset_gains(name, eq.freqs) == list(eq.gains):
                self.preset = name
        self.collector = collector
        self.nerd = NerdView(collector) if collector else None
        self.nerd_on = bool(cfg.get("nerd_start"))
        if self.nerd_on and collector:
            collector.active.set()
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        self.scr.keypad(True)
        if mouse:
            try:
                curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)
            except curses.error:
                pass
        self.c = Colors(cfg.get("theme", "classic"))

    @staticmethod
    def _pick(name, names):
        if name is None:
            return 0
        if isinstance(name, int):
            return name % len(names)
        low = [n.lower() for n in names]
        return low.index(str(name).lower()) if str(name).lower() in low else 0

    # ---- primitives --------------------------------------------------------------
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

    def flash(self, text, secs=3.0):
        self.msg, self.msg_until = text, time.time() + secs

    # ---- analysis ------------------------------------------------------------------
    def update_meters(self):
        peak, rms = self.engine.take_meter()
        to_db = lambda v: 20.0 * np.log10(np.maximum(v, 1e-5))  # noqa: E731
        fall = self.dt * 70.0
        self.rms_db = np.maximum(to_db(rms), self.rms_db - fall * 0.8)
        self.pk_db = np.maximum(to_db(peak), self.pk_db - self.dt * 30.0)

    def update_bars(self, nbars, hi):
        raw = self.spec.bars(self.engine.snapshot(), nbars, self.fmin, hi, self.tilt)
        floor = self.ceil - RANGE_DB
        new = np.clip((raw - floor) / (self.ceil - floor), 0.0, 1.0)
        if len(self.lvl) != nbars:
            self.lvl, self.cap, self.capv = np.zeros(nbars), np.zeros(nbars), np.zeros(nbars)
        a, r = 1 - math.exp(-self.dt * 50.0), 1 - math.exp(-self.dt * 11.0)
        self.lvl += (new - self.lvl) * np.where(new > self.lvl, a, r)
        pad = np.pad(self.lvl, 1, mode="edge")
        self.disp = np.clip(self.lvl * 0.64 + (pad[:-2] + pad[2:]) * 0.18, 0.0, 1.0)
        rising = self.disp >= self.cap
        self.capv = np.where(rising, 0.0, self.capv + 2.6 * self.dt)
        self.cap = np.where(rising, self.disp, np.maximum(self.cap - self.capv * self.dt, self.disp))

    # ---- layout ----------------------------------------------------------------------
    def compute_layout(self):
        H, W = self.H, self.W
        body = H - 2
        bottom = self.bottom_h or max(11, int(body * 0.5))
        bottom = max(11, min(int(bottom), body - 8))
        nb = self.eq.nbands
        fw = nb * self.bw + 2
        left = min(W, max(fw, 60)) if self.mode == "fx" else fw
        right = W - left
        if right < 20:
            left, right = W, 0
        self.lay = dict(spec_h=body - bottom, by=1 + body - bottom, bottom=bottom, left=left, right=right, fw=fw)

    # ---- header / footer ---------------------------------------------------------------
    def draw_header(self):
        e, eq = self.engine, self.eq
        self.put(0, 1, f" DanEQ v{__version__} ", self.c.title)
        self.put(0, 16, self.info[: max(self.W - 70, 10)], self.c.dim)
        chips = []
        if time.time() - e.last_clip < 2.0:
            chips.append(("CLIP", self.c.warn))
        if e.muted:
            chips.append(("MUTE", self.c.warn))
        n_on = sum(f.enabled for f in self.fx.fx)
        if n_on:
            chips.append((f"FX {n_on}" + (" off" if self.fx.bypass else ""), self.c.warn if self.fx.bypass else self.c.accent))
        chips.append(("BYPASS" if eq.bypass else "EQ ON", self.c.warn if eq.bypass else self.c.ok))
        chips.append((f"dsp {e.load * 100:3.0f}%", self.c.text))
        chips.append((f"{self.fps_now:3.0f}fps", self.c.dim))
        if e.latency_ms:
            chips.append((f"~{e.latency_ms:.0f}ms", self.c.text))
        x = self.W - 1
        for text, attr in reversed(chips):
            x -= len(text) + 2
            self.put(0, x, f"[{text}]", attr)

    def draw_footer(self):
        if time.time() < self.msg_until:
            self.put(self.H - 1, 1, self.msg, self.c.accent)
            return
        if self.nerd_on:
            keys = "nerd mode:  ^/v select  o sort  n back  v view  c theme  ? help  q quit"
        elif self.mode == "fx":
            keys = ("FX:  </> knob  ^/v adjust  Tab effect  o on/off  b rack bypass  r reset  f back to EQ  "
                    "v view  ? help  q quit")
        else:
            keys = ("Esc menu  ? help  </> band  ^/v gain  b bypass  p preset  a headroom  f fx  v view  g style  "
                    "c theme  n nerd  q quit")
        self.put(self.H - 1, 1, keys, self.c.dim)

    # ---- analyzer panel -------------------------------------------------------------------
    def draw_analyzer(self, y, x, h, w):
        eq = self.eq
        name = self.view_names[self.view]
        tag = "bypass" if eq.bypass else "post-EQ"
        right = ""
        if self.view == 0:
            f = eq.freqs[self.sel]
            right = f"{visuals.STYLES[self.style]}  band {self.sel + 1}/{eq.nbands}: {fmt_freq(f)}Hz {eq.gains[self.sel]:+.1f}dB"
        self.box(y, x, h, w, f"{name} {tag}", right)
        iy, ix, ih, iw = y + 1, x + 1, h - 2, w - 2
        sw = 5 if self.view == 0 else 0
        bw = iw - sw
        bh = ih - 2 if self.view == 0 else ih
        if bw < 10 or bh < 3:
            return
        hi = min(18000.0, self.engine.rate / 2 * 0.95)
        self.update_bars(bw * 2, hi)
        mono, st = self.engine.snapshot(), self.engine.snapshot_lr()
        cx = visuals.Ctx(self.put, self.c, iy, ix + sw, bw, bh, self.disp, self.t, self.dt, self.engine.rate, mono, st)
        if self.view == 0:
            visuals.draw_bars(cx, visuals.STYLES[self.style], self.disp, self.cap)
            floor = self.ceil - RANGE_DB
            for k in range(5):
                i = round(k * (bh - 1) / 4)
                self.put(iy + i, ix, f"{self.ceil - (self.ceil - floor) * i / max(bh - 1, 1):4.0f}", self.c.dim)
            self.draw_freq_axis(iy + bh, ix + sw, bw, hi)
        else:
            self.vis[self.view - 1].draw(cx)

    def draw_freq_axis(self, y, x0, bw, hi):
        eq = self.eq

        def xpos(freq):
            return x0 + int(round(math.log(freq / self.fmin) / math.log(hi / self.fmin) * (bw - 1)))

        last = -1
        for freq in (50, 100, 200, 500, 1000, 2000, 5000, 10000):
            if freq > hi:
                continue
            label = fmt_freq(freq)
            px = xpos(freq) - len(label) // 2
            if px > last:
                self.put(y, px, label, self.c.dim)
                last = px + len(label)
        for i, freq in enumerate(eq.freqs):
            px = min(max(xpos(min(max(freq, self.fmin), hi)), x0), x0 + bw - 1)
            self.put(y + 1, px, "▲", self.c.accent if i == self.sel else self.c.dim)

    # ---- EQ faders ---------------------------------------------------------------------------
    def draw_faders(self, y, x, h, w):
        eq, bw = self.eq, self.bw
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
            cx = ix + i * bw + bw // 2
            g, sel = eq.gains[i], i == self.sel
            t = int(round((GAIN_MAX - g) / (GAIN_MAX - GAIN_MIN) * (nt - 1)))
            gtxt = f"{g:+g}" if g else "0"
            self.put(iy, cx - len(gtxt) // 2, gtxt, self.c.accent if sel else self.c.text)
            fill = self.c.dim if off else (self.c.at(0.45 + 0.55 * abs(g) / GAIN_MAX) if g > 0 else self.c.curve)
            for j in range(nt):
                ry = iy + 1 + j
                if j == tc:
                    self.put(ry, cx - 1, "┈┼┈", self.c.dim)
                else:
                    self.put(ry, cx, "│", self.c.dim)
                if (g > 0 and t <= j < tc) or (g < 0 and tc < j <= t):
                    self.put(ry, cx, "┃", fill)
            knob = self.c.accent if sel else (self.c.dim if off else fill)
            self.put(iy + 1 + t, cx - 1, "▐█▌", knob)
            lab = fmt_freq(eq.freqs[i])
            self.put(iy + ih - 1, cx - len(lab) // 2, lab, (self.c.accent | curses.A_REVERSE) if sel else self.c.dim)

    # ---- FX rack ------------------------------------------------------------------------------
    def draw_fx(self, y, x, h, w):
        fx = self.fx.fx[self.fsel]
        self.box(y, x, h, w, "FX rack", "RACK BYPASSED" if self.fx.bypass else f"{fx.name}: {'ON' if fx.enabled else 'off'}")
        iy, ix, iw, ih = y + 1, x + 1, w - 2, h - 2
        self.tabs = []
        row, cur = 0, 0
        for i, f in enumerate(self.fx.fx):
            label = ("●" if f.enabled else "○") + f.short
            if cur + len(label) + 1 > iw:
                row, cur = row + 1, 0
            attr = (self.c.accent | curses.A_REVERSE) if i == self.fsel else (self.c.ok if f.enabled else self.c.dim)
            self.put(iy + row, ix + cur, label, attr)
            self.tabs.append((iy + row, ix + cur, len(label), i))
            cur += len(label) + 2
        ty = iy + row + 2
        params = fx.PARAMS
        pitch = min(10, max(7, iw // max(len(params), 1)))
        self.knobs = []
        self.kidx = min(self.kidx, len(params) - 1)
        for j, (key, label, lo, hi, dflt, unit, kind) in enumerate(params):
            kx = ix + 1 + j * pitch
            cv = Canvas(4, 2)
            cv.circle(3.5, 3.5, 3.5)
            th = math.radians(135 + fx.norm(key) * 270)
            cv.line(3.5, 3.5, 3.5 + 2.8 * math.cos(th), 3.5 + 2.8 * math.sin(th))
            sel = j == self.kidx
            blit(self.put, ty, kx + (pitch - 4) // 2, [(cv, self.c.accent if sel else (self.c.curve if fx.enabled else self.c.dim))])
            val = fx.fmt(key)
            self.put(ty + 2, kx + (pitch - len(label)) // 2, label, self.c.text if sel else self.c.dim)
            self.put(ty + 3, kx + (pitch - len(val)) // 2, val, self.c.accent if sel else self.c.text)
            self.knobs.append((ty, kx, pitch, j))
        status = fx.desc
        meter = fx.meter()
        if meter:
            status += f"    {meter}"
        self.put(ty + 5, ix + 1, status[: iw - 2], self.c.dim)

    # ---- response / meters ----------------------------------------------------------------------
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
        yof = lambda d: (rng - np.clip(d, -rng, rng)) / (2 * rng) * dh  # noqa: E731
        ys = np.rint(yof(db)).astype(int)
        y0 = int(round(float(yof(0.0))))
        grid, sel, curve, up, dn = (Canvas(cw, ch) for _ in range(5))
        for d, step in ((0, 2), (6, 4), (-6, 4), (12, 8), (-12, 8)):
            grid.a[int(round(float(yof(d)))), ::step] = True
        for i, f in enumerate(eq.freqs):
            xd = int(round(math.log(f / fmin) / math.log(fmax / fmin) * (n - 1)))
            (sel if i == self.sel else grid).a[:: 2 if i == self.sel else 4, xd] = True
        for xd in range(n):
            ya, yb = (ys[xd], y0) if ys[xd] < y0 else (y0, ys[xd])
            (up if ys[xd] < y0 else dn).a[ya + (xd % 2):yb + 1:2, xd] = True
        prev = None
        for xd in range(n):
            if prev is not None:
                curve.vspan(xd, prev, ys[xd])
            curve.set(xd, ys[xd])
            prev = ys[xd]
        blit(self.put, iy, ix + sw, [(grid, self.c.dim), (dn, self.c.fill_dn), (up, self.c.fill_up), (sel, self.c.accent), (curve, self.c.curve)])
        for d in (12, 6, 0, -6, -12):
            self.put(iy + min(int(yof(d)) // 4, ch - 1), ix, f"{d:+d}" if d else " 0", self.c.dim)
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
            self.put(row, bx + bar_w + 1, f"{self.pk_db[k]:6.1f}", self.c.warn if self.pk_db[k] >= -0.1 else self.c.text)

    def draw_help(self):
        w, h = 58, len(HELP) + 4
        y, x = max((self.H - h) // 2, 0), max((self.W - w) // 2, 0)
        for r in range(h):
            self.put(y + r, x, " " * w)
        self.box(y, x, h, w, "DanEQ keys", "any key closes")
        for i, (k, d) in enumerate(HELP):
            self.put(y + 2 + i, x + 3, k, self.c.accent)
            self.put(y + 2 + i, x + 21, d, self.c.text)

    # ---- dedication ------------------------------------------------------------------------
    def draw_rip(self):
        text = f"┤ {RIP} ├"
        x = self.W - len(text) - 2
        if x > 2:
            self.put(self.H - 2, x, text, self.c.dim)

    # ---- Esc menu ---------------------------------------------------------------------------
    def _list_builder(self, names, current, apply):
        def build():
            cur = current()
            return [(("● " if n == cur else "○ ") + n, (lambda n=n: self._apply(apply, n))) for n in names]
        return build

    @staticmethod
    def _apply(apply, n):
        apply(n)
        return "stay"

    def _set_view(self, name):
        self.view = self.view_names.index(name)

    def _set_style(self, name):
        self.style = visuals.STYLES.index(name)
        self.view = 0

    def _set_theme(self, name):
        self.c.set_theme(name)

    def _set_preset(self, name):
        self.eq.set_gains(preset_gains(name, self.eq.freqs))
        self.preset = name

    def _toggle_fx(self):
        self.mode = "eq" if self.mode == "fx" else "fx"
        self.nerd_on = False
        return None

    def _toggle_nerd(self):
        if self.nerd:
            self.nerd_on = not self.nerd_on
            (self.collector.active.set if self.nerd_on else self.collector.active.clear)()
        return None

    def _do(self, fn):
        fn()
        return None

    def _about_lines(self):
        return [(f"DanEQ v{__version__}", lambda: "stay"), ("github.com/fourzerosix/DanEQ", lambda: "stay"),
                ("GPL-3.0 license  -  Jeremy Bell", lambda: "stay"), ("", lambda: "stay"), (RIP, lambda: "stay")]

    def menu_main(self):
        items = [
            ("Resume", lambda: None),
            (f"View          {self.view_names[self.view]}  >", lambda: ("push", "View", self._list_builder(self.view_names, lambda: self.view_names[self.view], self._set_view))),
            (f"Bar style     {visuals.STYLES[self.style]}  >", lambda: ("push", "Bar style", self._list_builder(visuals.STYLES, lambda: visuals.STYLES[self.style], self._set_style))),
            (f"Theme         {self.c.theme}  >", lambda: ("push", "Theme", self._list_builder(THEME_ORDER, lambda: self.c.theme, self._set_theme))),
            (f"EQ preset     {self.preset}  >", lambda: ("push", "EQ preset", self._list_builder(PRESET_ORDER, lambda: self.preset, self._set_preset))),
            (f"FX rack       {'shown' if self.mode == 'fx' else 'hidden'}", self._toggle_fx),
        ]
        if self.nerd:
            items.append((f"Nerd mode     {'on' if self.nerd_on else 'off'}", self._toggle_nerd))
        items += [
            ("Auto headroom", lambda: self._do(lambda: self.flash(f"auto headroom: preamp {self.eq.auto_headroom():+.1f} dB"))),
            ("Bypass EQ" if not self.eq.bypass else "Enable EQ", lambda: self._do(lambda: self.eq.set_bypass(not self.eq.bypass))),
            ("Save settings", lambda: self._do(lambda: (self.save(), self.flash("settings saved")))),
            ("Export Equalizer APO", lambda: self._do(self.export)),
            ("Keyboard help", lambda: self._do(lambda: setattr(self, "show_help", True))),
            ("About", lambda: ("push", "About", self._about_lines)),
            ("Quit", lambda: "quit"),
        ]
        return items

    def open_menu(self):
        self.menu = [["DanEQ", self.menu_main, 0]]

    def menu_activate(self, items, idx):
        res = items[idx][1]()
        if res is None:
            self.menu = None
        elif isinstance(res, tuple) and res[0] == "push":
            self.menu.append([res[1], res[2], 0])
        return res != "quit"

    def menu_key(self, k) -> bool:
        title, builder, idx = self.menu[-1]
        items = builder()
        n = len(items)
        if k in (curses.KEY_UP, ord("k")):
            idx = (idx - 1) % n
        elif k in (curses.KEY_DOWN, ord("j")):
            idx = (idx + 1) % n
        elif k == curses.KEY_HOME:
            idx = 0
        elif k == curses.KEY_END:
            idx = n - 1
        elif k in (10, 13, curses.KEY_ENTER, ord(" "), curses.KEY_RIGHT, ord("l")):
            self.menu[-1][2] = idx
            return self.menu_activate(items, idx)
        elif k in (27, curses.KEY_LEFT, ord("h"), ord("q"), ord("Q")):
            self.menu.pop()
            if not self.menu:
                self.menu = None
            return True
        elif k == curses.KEY_MOUSE:
            try:
                _, mx, my, _, st = curses.getmouse()
            except curses.error:
                return True
            y, x, w, cnt, top = self.menu_rect
            if (st & (curses.BUTTON1_PRESSED | curses.BUTTON1_CLICKED)) and x <= mx < x + w and y <= my < y + cnt:
                self.menu[-1][2] = top + my - y
                return self.menu_activate(items, top + my - y)
            return True
        self.menu[-1][2] = min(idx, n - 1)
        return True

    def draw_menu(self):
        title, builder, idx = self.menu[-1]
        items = builder()
        w = max(34, max(len(label) for label, _ in items) + 8)
        rows = min(len(items), max(self.H - 8, 3))
        top = min(max(idx - rows + 1, 0), len(items) - rows) if len(items) > rows else 0
        h = rows + 4
        y, x = max((self.H - h) // 2, 0), max((self.W - w) // 2, 0)
        for r in range(h):
            self.put(y + r, x, " " * w)
        more = f"{idx + 1}/{len(items)}  " if len(items) > rows else ""
        self.box(y, x, h, w, title, more + "Esc: back")
        self.menu_rect = (y + 2, x + 1, w - 2, rows, top)
        for i in range(rows):
            label = items[top + i][0]
            attr = (self.c.accent | curses.A_REVERSE) if top + i == idx else self.c.text
            self.put(y + 2 + i, x + 1, (" " + label).ljust(w - 2), attr)

    # ---- frame ---------------------------------------------------------------------------------------
    def draw(self):
        self.scr.erase()
        self.H, self.W = self.scr.getmaxyx()
        need_w = max(80, self.eq.nbands * 4 + 2 + 20)
        if self.H < MIN_H or self.W < need_w:
            self.put(0, 0, f"DanEQ needs at least {need_w}x{MIN_H}; this terminal is {self.W}x{self.H}", self.c.warn)
            self.scr.refresh()
            return
        self.update_meters()
        self.draw_header()
        if self.nerd_on and self.nerd:
            self.nerd.draw(self, 1, 0, self.H - 2, self.W)
        else:
            self.compute_layout()
            L = self.lay
            self.draw_analyzer(1, 0, L["spec_h"], self.W)
            by, bh = L["by"], L["bottom"]
            (self.draw_fx if self.mode == "fx" else self.draw_faders)(by, 0, bh, L["left"])
            if L["right"]:
                self.draw_response(by, L["left"], bh - 4, L["right"])
                self.draw_meters(by + bh - 4, L["left"], 4, L["right"])
        self.draw_footer()
        self.draw_rip()
        if self.show_help:
            self.draw_help()
        if self.menu:
            self.draw_menu()
        self.scr.refresh()

    # ---- input -----------------------------------------------------------------------------------------
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

    def knob_nudge(self, direction, coarse=False):
        fx = self.fx.fx[self.fsel]
        key, _, lo, hi, _, _, kind = fx.PARAMS[self.kidx]
        if kind == "int":
            step = 2 if key == "stages" else 1
            fx.p[key] = float(min(max(fx.p[key] + direction * step * (2 if coarse else 1), lo), hi))
        else:
            fx.set_norm(key, fx.norm(key) + direction * (0.1 if coarse else 0.02))

    def select_fx(self, i):
        self.fsel = i % len(self.fx.fx)
        self.kidx = 0

    def on_mouse(self):
        try:
            _, mx, my, _, st = curses.getmouse()
        except curses.error:
            return
        L = self.lay
        if st & curses.BUTTON1_RELEASED:
            self.drag = None
            return
        wheel = (1 if st & getattr(curses, "BUTTON4_PRESSED", 0) else -1 if st & getattr(curses, "BUTTON5_PRESSED", 0) else 0)
        pressed = st & (curses.BUTTON1_PRESSED | curses.BUTTON1_CLICKED)
        moving = st & curses.REPORT_MOUSE_POSITION
        if self.nerd_on or not L:
            return
        if pressed and my in (L["by"] - 1, L["by"]):
            self.drag = "h"
        elif pressed and self.mode == "eq" and L["right"] and mx in (L["left"] - 1, L["left"]) and my >= L["by"]:
            self.drag = "v"
        if self.drag == "h" and (moving or pressed):
            self.bottom_h = max(11, min(self.H - 1 - my, self.H - 2 - 8))
            return
        if self.drag == "v" and (moving or pressed):
            self.bw = min(max(int(round((mx - 1) / self.eq.nbands)), 4), 9)
            return
        if self.mode == "fx":
            for ty, kx, pitch, j in self.knobs:
                if wheel and kx <= mx < kx + pitch and ty <= my <= ty + 3:
                    self.kidx = j
                    self.knob_nudge(wheel)
                    return
                if pressed and kx <= mx < kx + pitch and ty <= my <= ty + 3:
                    self.kidx = j
                    return
            for ty, tx, n, i in self.tabs:
                if pressed and my == ty and tx <= mx < tx + n:
                    if i == self.fsel:
                        f = self.fx.fx[i]
                        f.set_enabled(not f.enabled)
                    self.select_fx(i)
                    return
            return
        ty, ix, nt = self.fader
        if nt < 3:
            return
        band = (mx - ix) // self.bw
        inside = 0 <= band < self.eq.nbands and ty - 1 <= my <= ty + nt
        if wheel:
            i = band if inside else self.sel
            self.sel = i
            self.nudge(0.5 * wheel, i)
        elif st & getattr(curses, "BUTTON1_DOUBLE_CLICKED", 0) and inside:
            self.sel = band
            self.set_band(band, 0.0)
        elif (pressed or (self.drag == "fader" and moving)) and inside:
            self.sel = band
            row = min(max(my - ty, 0), nt - 1)
            self.set_band(band, round((GAIN_MAX - row / (nt - 1) * (GAIN_MAX - GAIN_MIN)) * 2) / 2)
            self.drag = "fader"

    def on_key(self, k) -> bool:
        n = self.eq.nbands
        if self.show_help:
            self.show_help = False
            return True
        if self.menu:
            return self.menu_key(k)
        if k == 27:
            self.open_menu()
            return True
        if k in (ord("q"), ord("Q")):
            return False
        if k == ord("?"):
            self.show_help = True
            return True
        if k == curses.KEY_MOUSE:
            self.on_mouse()
            return True
        if self.nerd_on and self.nerd and self.nerd.on_key(k, curses):
            return True
        # global keys
        if k == ord("n") and self.nerd:
            self.nerd_on = not self.nerd_on
            (self.collector.active.set if self.nerd_on else self.collector.active.clear)()
            return True
        if k == ord("v"):
            self.view = (self.view + 1) % len(self.view_names)
            self.flash(f"view: {self.view_names[self.view]}")
            return True
        if k == ord("V"):
            self.view = (self.view - 1) % len(self.view_names)
            self.flash(f"view: {self.view_names[self.view]}")
            return True
        if k == ord("g"):
            self.style = (self.style + 1) % len(visuals.STYLES)
            self.view = 0
            self.flash(f"style: {visuals.STYLES[self.style]}")
            return True
        if k in (ord("c"), ord("C")):
            i = (THEME_ORDER.index(self.c.theme) + (1 if k == ord("c") else -1)) % len(THEME_ORDER)
            self.c.set_theme(THEME_ORDER[i])
            self.flash(f"theme: {THEME_ORDER[i]}")
            return True
        if k == ord("f"):
            self.mode = "eq" if self.mode == "fx" else "fx"
            self.nerd_on = False
            return True
        if k == ord("("):
            self.bottom_h = max(11, (self.lay.get("bottom", 12)) - 1)
            return True
        if k == ord(")"):
            self.bottom_h = (self.lay.get("bottom", 12)) + 1
            return True
        if k == ord("{"):
            self.bw = max(4, self.bw - 1)
            return True
        if k == ord("}"):
            self.bw = min(9, self.bw + 1)
            return True
        if k == ord("m"):
            self.engine.muted = not self.engine.muted
            return True
        if k == ord("s"):
            self.save()
            self.flash("settings saved")
            return True
        if k == ord("e"):
            self.export()
            return True
        if k == ord("t"):
            self.tilt = 0.0 if self.tilt else 3.0
            return True
        if k == ord("."):
            self.ceil = max(-40.0, self.ceil - 5.0)
            return True
        if k == ord(","):
            self.ceil = min(0.0, self.ceil + 5.0)
            return True
        if k == ord("a"):
            self.flash(f"auto headroom: preamp {self.eq.auto_headroom():+.1f} dB")
            return True
        if k in (ord("["), ord("]")):
            self.eq.set_preamp(self.eq.preamp + (0.5 if k == ord("]") else -0.5))
            return True
        if self.nerd_on:
            return True
        if self.mode == "fx":
            return self.on_key_fx(k)
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
        elif k == ord("p"):
            self.cycle_preset(1)
        elif k == ord("P"):
            self.cycle_preset(-1)
        return True

    def on_key_fx(self, k) -> bool:
        fx = self.fx.fx[self.fsel]
        np_ = len(fx.PARAMS)
        if k in (curses.KEY_LEFT, ord("h")):
            self.kidx = (self.kidx - 1) % np_
        elif k in (curses.KEY_RIGHT, ord("l")):
            self.kidx = (self.kidx + 1) % np_
        elif k in (curses.KEY_UP, ord("k")):
            self.knob_nudge(1)
        elif k in (curses.KEY_DOWN, ord("j")):
            self.knob_nudge(-1)
        elif k in (curses.KEY_PPAGE, ord("K")):
            self.knob_nudge(1, True)
        elif k in (curses.KEY_NPAGE, ord("J")):
            self.knob_nudge(-1, True)
        elif k == ord("\t"):
            self.select_fx(self.fsel + 1)
        elif k == getattr(curses, "KEY_BTAB", -9):
            self.select_fx(self.fsel - 1)
        elif ord("1") <= k <= ord("9"):
            self.select_fx(k - ord("1"))
        elif k in (ord("o"), ord(" ")):
            fx.set_enabled(not fx.enabled)
            self.flash(f"{fx.name}: {'ON' if fx.enabled else 'off'}")
        elif k == ord("0"):
            fx.reset_param(fx.PARAMS[self.kidx][0])
        elif k == ord("r"):
            for spec in fx.PARAMS:
                fx.reset_param(spec[0])
        elif k == ord("b"):
            self.fx.bypass = not self.fx.bypass
            self.flash("FX rack bypassed" if self.fx.bypass else "FX rack active")
        return True

    # ---- persistence ---------------------------------------------------------------------------------
    def state(self) -> dict:
        gains = dict(self.cfg.get("gains", {}))
        gains[str(self.eq.nbands)] = list(self.eq.gains)
        st = {**self.cfg, "bands": self.eq.nbands, "gains": gains, "preamp": self.eq.preamp,
              "tilt": self.tilt, "ceil": self.ceil, "theme": self.c.theme,
              "view": self.view_names[self.view], "style": visuals.STYLES[self.style],
              "bw": self.bw, "fx": self.fx.state()}
        st.pop("nerd_start", None)
        if self.bottom_h:
            st["bottom_h"] = int(self.bottom_h)
        return st

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
        last = time.monotonic()
        frames, fps_t = 0, last
        while True:
            if self.engine.error or self.engine.finished:
                return
            now = time.monotonic()
            self.dt = min(max(now - last, 0.001), 0.1)
            last = now
            self.t += self.dt
            self.draw()
            frames += 1
            if now - fps_t >= 1.0:
                self.fps_now, frames, fps_t = frames / (now - fps_t), 0, now
            spent = time.monotonic() - now
            self.scr.timeout(max(1, int((1.0 / self.fps - spent) * 1000)))
            k = self.scr.getch()
            while k != -1:
                if not self.on_key(k):
                    return
                self.scr.timeout(0)
                k = self.scr.getch()


def run(engine, eq, fx, cfg, info, mouse=True, collector=None):
    """Runs the TUI, returns the final state dict to persist."""
    os.environ.setdefault("ESCDELAY", "25")
    out = {}

    def main(scr):
        app = App(scr, engine, eq, fx, cfg, info, mouse, collector)
        try:
            app.run()
        finally:
            out.update(app.state())

    curses.wrapper(main)
    return out
