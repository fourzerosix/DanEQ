"""Visualizations. Each Visual draws into a rectangle using a Ctx from the UI."""
from __future__ import annotations

import math
import random
from collections import deque

import numpy as np

from .braille import SHADE, Canvas, bar_rows, blit, to_str

TAU = 2.0 * math.pi
STYLES = ["braille", "line", "mirror", "dots", "blocks", "ascii"]


class Ctx:
    """Everything a visual needs. Built fresh by the UI every frame."""

    def __init__(self, put, colors, iy, ix, w, h, lvl, t, dt, rate, mono, stereo):
        self.put, self.c = put, colors
        self.iy, self.ix, self.w, self.h = iy, ix, w, h
        self.lvl, self.t, self.dt, self.rate = lvl, t, dt, rate
        self.mono, self.stereo = mono, stereo
        n = max(len(lvl), 1)
        self.bass = float(lvl[: int(n * 0.33) or 1].mean())
        self.mid = float(lvl[int(n * 0.33): int(n * 0.76) or 2].mean()) if n > 3 else 0.0
        self.high = float(lvl[int(n * 0.76):].mean()) if n > 3 else 0.0
        self.onset = 0.0


def _bands(c, k):
    return [c.at((i + 0.5) / k) for i in range(k)]


# ---- spectrum styles ----------------------------------------------------------------
def zoned(cx, y, x, s, hf, zones=10):
    """One row, colored by height with a slight shift along frequency."""
    n = len(s)
    for z in range(zones):
        a, b = n * z // zones, n * (z + 1) // zones
        if b > a:
            cx.put(y, x + a, s[a:b], cx.c.at(min(hf * 0.88 + 0.12 * z / max(zones - 1, 1), 1.0)))


def draw_bars(cx, style, lvl, cap):
    w, h = cx.w, cx.h
    n = w * 2
    if style == "blocks":
        v = lvl.reshape(-1, 2).max(axis=1) * h * 8
        table = np.array(list(" ▁▂▃▄▅▆▇█"))
        for i in range(h):
            e = np.clip(v - (h - 1 - i) * 8, 0, 8).astype(int)
            zoned(cx, cx.iy + i, cx.ix, "".join(table[e]), (h - 1 - i) / max(h - 1, 1))
        return
    if style == "ascii":
        rows = np.clip((lvl.reshape(-1, 2).max(axis=1) * h).round().astype(int), 0, h)
        for i in range(h):
            level = h - i
            s = "".join("=" if r == level else ("|" if r > level else " ") for r in rows)
            zoned(cx, cx.iy + i, cx.ix, s, (h - 1 - i) / max(h - 1, 1))
        return
    if style == "braille":
        levels = np.clip((lvl * h * 4).astype(int), 0, h * 4)
        caps = np.clip((cap * h * 4).astype(int), 0, h * 4 - 1)
        caps = np.where(cap < 0.02, -1, caps)
        for i, row in enumerate(bar_rows(levels, caps, h)):
            zoned(cx, cx.iy + i, cx.ix, row, (h - 1 - i) / max(h - 1, 1))
        return
    cv = Canvas(w, h)
    top = np.clip(((1.0 - lvl) * (h * 4 - 1)).round().astype(int), 0, h * 4 - 1)
    if style == "line":
        prev = None
        for x in range(n):
            if prev is not None:
                cv.vspan(x, prev, top[x])
            cv.set(x, top[x])
            prev = top[x]
    elif style == "dots":
        for x in range(n):
            cv.a[top[x]::3, x] = True
            if cap[x] > 0.02:
                cv.set(x, int((1 - cap[x]) * (h * 4 - 1)))
    elif style == "mirror":
        hh = h // 2
        ys = np.arange(hh * 4)[:, None]
        up = ys >= (hh * 4 - (lvl[None, :] * hh * 4))
        cv = Canvas(w, hh * 2)
        cv.a[: hh * 4] = up
        cv.a[hh * 4:] = up[::-1]
    k = cv.h
    layers = [(b, cx.c.at(1.0 - (i + 0.5) / k if style != "mirror" else abs(1.0 - (i + 0.5) / k * 2)))
              for i, b in enumerate(cv.bands(k))]
    blit(cx.put, cx.iy, cx.ix, layers)


# ---- visuals -------------------------------------------------------------------------------
class Visual:
    name = "?"

    def draw(self, cx):  # pragma: no cover
        raise NotImplementedError


class Waterfall(Visual):
    name = "Waterfall"

    def __init__(self):
        self.hist, self.acc = deque(maxlen=128), 0.0

    def draw(self, cx):
        self.acc += cx.dt
        if self.acc >= 0.045 or not self.hist:
            self.acc = 0.0
            self.hist.appendleft(cx.lvl.reshape(-1, 2).max(axis=1).copy())
        n = len(cx.c.grad)
        for i in range(min(cx.h, len(self.hist))):
            v = self.hist[i]
            if len(v) != cx.w:
                continue
            dots = np.minimum((v * 9).astype(int), 8)
            ci = np.minimum((v * (n - 1) + 0.5).astype(int), n - 1)
            j = 0
            while j < cx.w:
                k = j
                while k < cx.w and ci[k] == ci[j]:
                    k += 1
                cx.put(cx.iy + i, cx.ix + j, "".join(SHADE[d] for d in dots[j:k]), cx.c.grad[ci[j]])
                j = k


class Scope(Visual):
    name = "Scope"

    def __init__(self):
        self.amp = 0.25

    def draw(self, cx):
        x = cx.mono
        n = cx.w * 2
        chunk = max(len(x) // n, 1)
        seg = x[len(x) - chunk * n:].reshape(n, chunk) if len(x) >= chunk * n else np.zeros((n, 1))
        mn, mx = seg.min(axis=1), seg.max(axis=1)
        self.amp = max(float(np.abs(x).max()), 0.05, self.amp * 0.98)
        dh = cx.h * 4 - 1
        cv, mid = Canvas(cx.w, cx.h), Canvas(cx.w, cx.h)
        y = lambda v: (1.0 - np.clip(v / self.amp, -1, 1)) / 2.0 * dh  # noqa: E731
        y0, y1 = y(mx), y(mn)
        for xd in range(n):
            cv.vspan(xd, y0[xd], y1[xd])
        mid.a[dh // 2, ::4] = True
        k = cx.h
        layers = [(mid, cx.c.dim)] + [(b, cx.c.at(1.0 - abs((i + 0.5) / k * 2 - 1))) for i, b in enumerate(cv.bands(k))]
        blit(cx.put, cx.iy, cx.ix, layers)


class Vector(Visual):
    name = "Vectorscope"

    def __init__(self):
        self.amp = 0.3

    def draw(self, cx):
        st = cx.stereo
        W, H = cx.w * 2, cx.h * 4
        cxx, cyy, R = W / 2.0, H / 2.0, min(W, H) / 2.0 - 2
        grid, tr = Canvas(cx.w, cx.h), Canvas(cx.w, cx.h)
        grid.circle(cxx, cyy, R)
        grid.circle(cxx, cyy, R / 2)
        grid.a[int(cyy), ::3] = True
        grid.a[::3, int(cxx)] = True
        if len(st):
            l, r = st[:, 0], st[:, 1]
            self.amp = max(float(np.abs(st).max()), 0.05, self.amp * 0.98)
            m, s = (l + r) * 0.7071 / self.amp, (l - r) * 0.7071 / self.amp
            tr.points(cxx + s * R, cyy - m * R)
        corr = float(np.corrcoef(st[:, 0], st[:, 1])[0, 1]) if len(st) > 8 and st.std() > 1e-6 else 1.0
        blit(cx.put, cx.iy, cx.ix, [(grid, cx.c.dim), (tr, cx.c.curve)])
        cx.put(cx.iy + cx.h - 1, cx.ix + 1, f"L/R corr {corr:+.2f}  (+1 mono, 0 wide, -1 out of phase)", cx.c.dim)


class Radial(Visual):
    name = "Radial"

    def __init__(self):
        self.rot = 0.0

    def draw(self, cx):
        W, H = cx.w * 2, cx.h * 4
        cxx, cyy = W / 2.0, H / 2.0
        rmax, r0 = min(W, H) / 2.0 - 2, min(W, H) * 0.16
        self.rot += cx.dt * (0.15 + cx.bass * 0.9)
        k = 6
        cvs = [Canvas(cx.w, cx.h) for _ in range(k)]
        nb = 120
        half = np.interp(np.linspace(0, len(cx.lvl) - 1, nb // 2), np.arange(len(cx.lvl)), cx.lvl)
        vals = np.concatenate((half, half[::-1]))
        ang = self.rot + np.arange(nb) * TAU / nb
        ln = r0 + vals * (rmax - r0)
        rr = np.arange(0.0, rmax - r0 + 1, 0.7)[None, :] + r0
        m = rr <= ln[:, None]
        px, py = cxx + rr * np.cos(ang)[:, None], cyy + rr * np.sin(ang)[:, None]
        band = np.minimum(((rr - r0) / (rmax - r0) * k).astype(int), k - 1) * np.ones_like(m, dtype=int)
        for b in range(k):
            sel = m & (band == b)
            cvs[b].points(px[sel], py[sel])
        ring = Canvas(cx.w, cx.h)
        ring.circle(cxx, cyy, r0 - 2 - cx.bass * 3)
        blit(cx.put, cx.iy, cx.ix, [(ring, cx.c.accent)] + [(c, cx.c.at((i + 0.5) / k)) for i, c in enumerate(cvs)])


class Vinyl(Visual):
    name = "Vinyl"

    def __init__(self):
        self.ang, self.spin = 0.0, 0.0
        rnd = random.Random(4)
        self.specks = [(rnd.random() * TAU, 0.35 + 0.6 * rnd.random()) for _ in range(46)]

    def draw(self, cx):
        W, H = cx.w * 2, cx.h * 4
        R = min(W / 2.7, H / 2.0 - 2)
        c0x, c0y = W * 0.42, H / 2.0
        lr = R * 0.34
        self.spin += (1.0 - self.spin) * min(cx.dt * 1.2, 1.0)
        self.ang = (self.ang + cx.dt * self.spin * TAU * (100.0 / 180.0)) % TAU
        base, sheen, label, speck, arm = (Canvas(cx.w, cx.h) for _ in range(5))
        base.circle(c0x, c0y, R)
        base.circle(c0x, c0y, R - 1.2)
        radii = [r for r in np.arange(lr + 3, R - 2.5, 2.6) if not (abs(r - (lr + (R - lr) * 0.45)) < 2.0 or abs(r - (lr + (R - lr) * 0.75)) < 2.0)]
        wob = cx.bass * 0.9
        width = 0.35 + 0.9 * cx.mid
        for r in radii:
            base.circle(c0x, c0y, r + wob * math.sin(r))
            for s in (self.ang, self.ang + math.pi):
                sheen.circle(c0x, c0y, r + wob * math.sin(r), s - width, s + width)
        label.circle(c0x, c0y, lr)
        label.circle(c0x, c0y, lr * 0.55)
        label.circle(c0x, c0y, 1.6)
        for k in range(3):
            a = self.ang + k * TAU / 3
            label.circle(c0x, c0y, lr * 0.8, a, a + 0.9)
        label.line(c0x, c0y, c0x + lr * 0.95 * math.cos(self.ang), c0y + lr * 0.95 * math.sin(self.ang))
        for a, rf in self.specks:
            a2 = a + self.ang
            speck.set(c0x + R * rf * math.cos(a2), c0y + R * rf * math.sin(a2))
        px, py = W * 0.9, H * 0.1
        prog = (cx.t / 90.0) % 1.0
        dist = math.hypot(px - c0x, py - c0y)
        larm = dist - lr * 1.15
        a0 = math.atan2(c0y - py, c0x - px)
        deltas = np.linspace(0, 1.3, 200)
        ds = np.hypot(px + larm * np.cos(a0 + deltas) - c0x, py + larm * np.sin(a0 + deltas) - c0y)
        target = (R * 0.9) - prog * (R * 0.9 - lr * 1.2)
        d = float(np.interp(target, ds, deltas)) if ds[0] < ds[-1] else 0.0
        nx = px + larm * math.cos(a0 + d) + cx.high * math.sin(cx.t * 90)
        ny = py + larm * math.sin(a0 + d) + cx.high * math.cos(cx.t * 70)
        arm.circle(px, py, 3.2)
        arm.line(px, py, nx, ny)
        arm.line(nx, ny, nx + 4 * math.cos(a0 + d + 0.5), ny + 4 * math.sin(a0 + d + 0.5))
        blit(cx.put, cx.iy, cx.ix, [(base, cx.c.dim), (sheen, cx.c.curve), (speck, cx.c.text), (label, cx.c.accent), (arm, cx.c.text)])
        cx.put(cx.iy + cx.h - 2, cx.ix + 2, "33 1/3 RPM", cx.c.dim)
        cx.put(cx.iy + cx.h - 1, cx.ix + 2, f"SIDE A  {int(cx.t // 60):02d}:{int(cx.t % 60):02d}", cx.c.dim)


class Reel(Visual):
    name = "Reel-to-reel"

    def __init__(self):
        self.al = self.ar = 0.0
        self.tape_t = 0.0

    def draw(self, cx):
        W, H = cx.w * 2, cx.h * 4
        R = min(H * 0.40, W * 0.21)
        ly, lxl, lxr = H * 0.40, W * 0.26, W * 0.74
        rmin = R * 0.32
        self.tape_t += cx.dt
        p = (self.tape_t / 120.0) % 1.0
        rr = math.sqrt(rmin ** 2 + p * (R * R * 0.9 - rmin ** 2))
        rl = math.sqrt(rmin ** 2 + (1 - p) * (R * R * 0.9 - rmin ** 2))
        speed = 22.0                                   # tape speed in dots per second
        self.al += cx.dt * speed / rl
        self.ar += cx.dt * speed / rr
        body, pack, spokes, head, tape, glow = (Canvas(cx.w, cx.h) for _ in range(6))
        for x0, rp, ang in ((lxl, rl, self.al), (lxr, rr, self.ar)):
            body.circle(x0, ly, R)
            body.circle(x0, ly, R - 1.3)
            for r in np.arange(rmin + 1, rp, 2.2):
                pack.circle(x0, ly, r)
            pack.circle(x0, ly, rp)
            spokes.circle(x0, ly, rmin)
            spokes.circle(x0, ly, 2.0)
            for k in range(3):
                a = ang + k * TAU / 3
                spokes.line(x0 + 2.5 * math.cos(a), ly + 2.5 * math.sin(a), x0 + rmin * math.cos(a), ly + rmin * math.sin(a))
                spokes.circle(x0, ly, rmin * 0.62, a + 0.25, a + 0.95)
        gy = ly + R * 0.95
        gl, gr, hx = W * 0.40, W * 0.60, W * 0.50
        tape.line(lxl + rl * 0.7, ly + rl * 0.72, gl, gy)
        tape.line(gl, gy, gr, gy)
        tape.line(gr, gy, lxr - rr * 0.7, ly + rr * 0.72)
        for gx in (gl, gr):
            head.circle(gx, gy - 2, 2.2)
        for k, off in enumerate((-8, 0, 8)):
            head.hspan(gy + 3, hx + off - 2, hx + off + 2)
            head.hspan(gy + 4, hx + off - 2, hx + off + 2)
        glow.circle(hx, gy + 3, 5 + cx.mid * 8)
        capx = W * 0.62 + 12
        head.circle(capx, gy + 1, 3.0)
        cap_a = self.tape_t * 6
        head.line(capx, gy + 1, capx + 3 * math.cos(cap_a), gy + 1 + 3 * math.sin(cap_a))
        blit(cx.put, cx.iy, cx.ix, [(body, cx.c.dim), (pack, cx.c.curve), (tape, cx.c.text), (spokes, cx.c.accent), (head, cx.c.text), (glow, cx.c.at(0.8))])
        tt = int(self.tape_t)
        rec = "REC" if int(cx.t * 2) % 2 == 0 else "   "
        cx.put(cx.iy + cx.h - 1, cx.ix + 2, f"15 IPS  {tt // 3600:02d}:{tt // 60 % 60:02d}:{tt % 60:02d}  {rec}", cx.c.warn if rec.strip() else cx.c.dim)


class Fire(Visual):
    name = "Fire"

    def __init__(self):
        self.heat, self.acc = None, 0.0
        self.rng = np.random.default_rng(3)

    def draw(self, cx):
        w, h = cx.w, cx.h
        if self.heat is None or self.heat.shape != (h + 1, w):
            self.heat = np.zeros((h + 1, w))
        self.acc += cx.dt
        steps = 0
        while self.acc >= 1 / 40.0 and steps < 3:
            self.acc -= 1 / 40.0
            steps += 1
            cells = cx.lvl.reshape(-1, 2).max(axis=1)
            self.heat[h] = np.clip(0.12 + cells * 1.5 + self.rng.random(w) * 0.15, 0, 1.2)
            cool = 1.15 / max(h, 1)
            for y in range(h - 1, -1, -1):
                b = self.heat[y + 1]
                src = (np.roll(b, 1) + b + np.roll(b, -1) + self.heat[min(y + 2, h)]) / 4.0
                self.heat[y] = np.maximum(src - cool * (0.4 + 1.2 * self.rng.random(w)), 0)
        self.acc = min(self.acc, 0.1)
        n = len(cx.c.grad)
        for y in range(h):
            v = np.clip(self.heat[y], 0, 1)
            dots = np.minimum((v * 9).astype(int), 8)
            ci = np.minimum((v * (n - 1) + 0.5).astype(int), n - 1)
            j = 0
            while j < w:
                k = j
                while k < w and ci[k] == ci[j]:
                    k += 1
                if dots[j:k].any():
                    cx.put(cx.iy + y, cx.ix + j, "".join(SHADE[d] for d in dots[j:k]), cx.c.grad[ci[j]])
                j = k


class Starfield(Visual):
    name = "Starfield"

    def __init__(self):
        rng = np.random.default_rng(8)
        self.n = 260
        self.x, self.y = rng.uniform(-1, 1, self.n), rng.uniform(-1, 1, self.n)
        self.z = rng.uniform(0.05, 1.0, self.n)
        self.boost = 0.0
        self.rng = rng

    def draw(self, cx):
        W, H = cx.w * 2, cx.h * 4
        self.boost = max(self.boost * (1 - cx.dt * 3), cx.bass * 2.5)
        speed = 0.12 + self.boost * 0.9
        pz = self.z.copy()
        self.z -= speed * cx.dt
        dead = (self.z <= 0.02)
        self.z[dead] = 1.0
        self.x[dead], self.y[dead] = self.rng.uniform(-1, 1, dead.sum()), self.rng.uniform(-1, 1, dead.sum())
        pz[dead] = 1.0
        s = min(W, H) * 0.55
        sx, sy = W / 2 + self.x / self.z * s * 0.5, H / 2 + self.y / self.z * s * 0.5
        px, py = W / 2 + self.x / pz * s * 0.5, H / 2 + self.y / pz * s * 0.5
        layers = [Canvas(cx.w, cx.h) for _ in range(3)]
        for i in range(self.n):
            k = 0 if self.z[i] > 0.66 else 1 if self.z[i] > 0.33 else 2
            if 0 <= sx[i] < W and 0 <= sy[i] < H:
                if self.boost > 0.3 and k > 0:
                    layers[k].line(px[i], py[i], sx[i], sy[i])
                else:
                    layers[k].set(sx[i], sy[i])
        blit(cx.put, cx.iy, cx.ix, [(layers[0], cx.c.dim), (layers[1], cx.c.at(0.55)), (layers[2], cx.c.at(1.0))])


class Ripples(Visual):
    name = "Ripples"

    def __init__(self):
        self.drops, self.avg, self.cool = [], 0.0, 0.0
        self.rng = random.Random(12)

    def draw(self, cx):
        W, H = cx.w * 2, cx.h * 4
        self.avg += (cx.bass - self.avg) * min(cx.dt * 3, 1)
        self.cool -= cx.dt
        if cx.bass > self.avg + 0.08 and self.cool <= 0:
            self.drops.append([self.rng.uniform(0.15, 0.85) * W, self.rng.uniform(0.2, 0.8) * H, 0.0, 1.0])
            self.cool = 0.18
        if self.rng.random() < cx.high * cx.dt * 12:
            self.drops.append([self.rng.uniform(0.05, 0.95) * W, self.rng.uniform(0.1, 0.9) * H, 0.0, 0.5])
        layers = [Canvas(cx.w, cx.h) for _ in range(3)]
        keep = []
        for d in self.drops:
            d[2] += cx.dt
            r = d[2] * 28 * d[3] ** 0.5
            if r > max(W, H) * 0.7 or d[2] > 3.5:
                continue
            keep.append(d)
            k = 2 if d[2] < 0.8 else 1 if d[2] < 1.8 else 0
            for off in (0, 5, 10):
                if r - off > 1:
                    layers[k].circle(d[0], d[1], r - off)
        self.drops = keep[-24:]
        blit(cx.put, cx.iy, cx.ix, [(layers[0], cx.c.dim), (layers[1], cx.c.at(0.45)), (layers[2], cx.c.at(0.9))])


class Matrix(Visual):
    name = "Matrix"
    CHARS = "01abcdefABCDEF$#@%&*+=<>/\\|?"

    def __init__(self):
        self.cols = {}
        self.rng = random.Random(6)

    def draw(self, cx):
        w, h = cx.w, cx.h
        cells = cx.lvl.reshape(-1, 2).max(axis=1)
        for c in range(w):
            col = self.cols.get(c)
            if col is None:
                if self.rng.random() < (0.01 + cells[c] * 0.25) * cx.dt * 30:
                    self.cols[c] = [0.0, self.rng.uniform(8, 22), self.rng.randint(5, max(6, h))]
                continue
            col[0] += col[1] * (0.7 + cells[c] * 1.5) * cx.dt
            if col[0] - col[2] > h:
                del self.cols[c]
                continue
            head = int(col[0])
            for i in range(col[2]):
                y = head - i
                if 0 <= y < h:
                    fr = 1.0 - i / col[2]
                    attr = cx.c.accent if i == 0 else cx.c.at(0.25 + 0.65 * fr)
                    cx.put(cx.iy + y, cx.ix + c, self.rng.choice(self.CHARS) if i < 3 or self.rng.random() < 0.05 else self.CHARS[(c * 7 + y * 3) % len(self.CHARS)], attr)


def make_all():
    return [Waterfall(), Scope(), Vector(), Radial(), Vinyl(), Reel(), Fire(), Starfield(), Ripples(), Matrix()]
