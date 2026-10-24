"""DAW-style insert effects. Real time, block based, state kept between blocks.

Every effect has knobs described by PARAMS: (key, label, lo, hi, default, unit, kind)
where kind is 'lin', 'log' or 'int'. The UI drives them through norm()/set_norm().
"""
from __future__ import annotations

import math

import numpy as np
from scipy import signal

from .dsp import biquad

TAU = 2.0 * math.pi


class Effect:
    name = "Effect"
    short = "Fx"
    desc = ""
    PARAMS: list = []

    def __init__(self, rate: int):
        self.rate = rate
        self.enabled = False
        self.p = {k: d for k, _, _, _, d, _, _ in self.PARAMS}
        self.setup()

    def setup(self) -> None:
        """(Re)create all internal state."""

    def set_enabled(self, flag: bool) -> None:
        if flag and not self.enabled:
            self.setup()
        self.enabled = bool(flag)

    def spec(self, key):
        for s in self.PARAMS:
            if s[0] == key:
                return s
        raise KeyError(key)

    def norm(self, key) -> float:
        _, _, lo, hi, _, _, kind = self.spec(key)
        v = self.p[key]
        if kind == "log":
            return math.log(v / lo) / math.log(hi / lo)
        return (v - lo) / (hi - lo)

    def set_norm(self, key, v: float) -> None:
        _, _, lo, hi, _, _, kind = self.spec(key)
        v = min(max(v, 0.0), 1.0)
        if kind == "log":
            val = lo * (hi / lo) ** v
        else:
            val = lo + v * (hi - lo)
        self.p[key] = float(round(val)) if kind == "int" else float(val)

    def reset_param(self, key) -> None:
        self.p[key] = self.spec(key)[4]

    def fmt(self, key) -> str:
        _, _, lo, hi, _, unit, kind = self.spec(key)
        v = self.p[key]
        if kind == "int":
            return f"{int(v)}{unit}"
        if abs(v) >= 100:
            return f"{v:.0f}{unit}"
        if abs(v) >= 10:
            return f"{v:.1f}{unit}"
        return f"{v:.2f}{unit}"

    def meter(self):
        return ""

    def process(self, x: np.ndarray) -> np.ndarray:  # pragma: no cover - interface
        return x


def _mix(x, y, m):
    return x * (1.0 - m) + y * m


class Compressor(Effect):
    name, short = "Compressor", "Comp"
    desc = "Feed-forward compressor, linked stereo"
    PARAMS = [
        ("thresh", "Thresh", -40.0, 0.0, -18.0, "dB", "lin"),
        ("ratio", "Ratio", 1.0, 20.0, 4.0, ":1", "log"),
        ("attack", "Attack", 1.0, 100.0, 8.0, "ms", "log"),
        ("release", "Release", 20.0, 1000.0, 150.0, "ms", "log"),
        ("makeup", "Makeup", 0.0, 24.0, 3.0, "dB", "lin"),
        ("mix", "Mix", 0.0, 1.0, 1.0, "", "lin"),
    ]
    CH = 32

    def setup(self):
        self.env = -90.0
        self.gr = 0.0

    def meter(self):
        return f"GR -{self.gr:4.1f} dB"

    def process(self, x):
        p, ch, n = self.p, self.CH, len(x)
        mag = np.abs(x).max(axis=1)
        m = -(-n // ch)
        if m * ch > n:
            mag = np.concatenate((mag, np.zeros(m * ch - n)))
        lev = 20.0 * np.log10(np.maximum(mag.reshape(m, ch).max(axis=1), 1e-6))
        att = 1.0 - math.exp(-ch / (self.rate * p["attack"] / 1000.0))
        rel = 1.0 - math.exp(-ch / (self.rate * p["release"] / 1000.0))
        slope = 1.0 - 1.0 / p["ratio"]
        g = np.empty(m)
        env, top = self.env, 0.0
        for i in range(m):
            env += (lev[i] - env) * (att if lev[i] > env else rel)
            red = max(env - p["thresh"], 0.0) * slope
            g[i] = -red
            top = max(top, red)
        self.env = env
        self.gr += (top - self.gr) * 0.4
        gdb = np.interp(np.arange(n), np.arange(m) * ch + ch / 2.0, g) + p["makeup"]
        return _mix(x, x * (10.0 ** (gdb / 20.0))[:, None], p["mix"])


class Overdrive(Effect):
    name, short = "Overdrive", "Drive"
    desc = "Tanh saturation with tone control"
    PARAMS = [
        ("drive", "Drive", 0.0, 40.0, 12.0, "dB", "lin"),
        ("tone", "Tone", 500.0, 12000.0, 4500.0, "Hz", "log"),
        ("level", "Level", -24.0, 6.0, -6.0, "dB", "lin"),
        ("mix", "Mix", 0.0, 1.0, 1.0, "", "lin"),
    ]

    def setup(self):
        self.zi = np.zeros((1, 2, 2))

    def process(self, x):
        p = self.p
        y = np.tanh(x * 10.0 ** (p["drive"] / 20.0))
        sos = signal.butter(1, min(p["tone"], self.rate * 0.45), fs=self.rate, output="sos")
        y, self.zi = signal.sosfilt(sos, y, axis=0, zi=self.zi)
        return _mix(x, y * 10.0 ** (p["level"] / 20.0), p["mix"])


class Crusher(Effect):
    name, short = "Bitcrusher", "Crush"
    desc = "Bit depth and sample rate reduction"
    PARAMS = [
        ("bits", "Bits", 3.0, 16.0, 8.0, "", "int"),
        ("down", "Downsmp", 1.0, 32.0, 4.0, "x", "int"),
        ("mix", "Mix", 0.0, 1.0, 1.0, "", "lin"),
    ]

    def setup(self):
        self.pos = 0
        self.held = np.zeros(2)

    def process(self, x):
        p, n = self.p, len(x)
        q = 2.0 ** (p["bits"] - 1)
        y = np.round(x * q) / q
        d = max(int(p["down"]), 1)
        if d > 1:
            pos = self.pos + np.arange(n)
            src = (pos - pos % d) - self.pos          # <= 0 means "held from last block"
            ext = np.vstack((self.held[None, :], y))
            y = ext[np.maximum(src, -1) + 1]
            self.held = y[-1].copy()
        self.pos = (self.pos + n) % max(d, 1)
        return _mix(x, y, p["mix"])


class Megaphone(Effect):
    name, short = "Megaphone", "Mega"
    desc = "Bullhorn / PA loudspeaker with slapback"
    PARAMS = [
        ("drive", "Drive", 0.0, 30.0, 10.0, "dB", "lin"),
        ("honk", "Honk", 0.0, 12.0, 6.0, "dB", "lin"),
        ("slap", "Slap", 0.0, 1.0, 0.25, "", "lin"),
        ("mix", "Mix", 0.0, 1.0, 1.0, "", "lin"),
    ]

    def setup(self):
        r = self.rate
        self.bp = np.vstack((signal.butter(2, 450, "highpass", fs=r, output="sos"),
                             signal.butter(2, 3400, "lowpass", fs=r, output="sos")))
        self.zi = np.zeros((self.bp.shape[0] + 1, 2))
        self.L = int(r * 0.4)
        self.buf = np.zeros(self.L)
        self.w = 0

    def process(self, x):
        p, n = self.p, len(x)
        mono = x.mean(axis=1)
        pk = np.array([biquad("peak", 1400.0, p["honk"], 2.0, self.rate)])
        sos = np.vstack((self.bp, pk))
        y, self.zi = signal.sosfilt(sos, mono, zi=self.zi)
        y = np.tanh(y * 10.0 ** (p["drive"] / 20.0)) * 0.45
        d = int(self.rate * 0.12)
        idx = (self.w - d + np.arange(n)) % self.L
        y = y + self.buf[idx] * p["slap"]
        self.buf[(self.w + np.arange(n)) % self.L] = y
        self.w = (self.w + n) % self.L
        return _mix(x, np.stack((y, y), axis=1), p["mix"])


class ModDelay:
    """Fractional delay line with per-sample delay times and optional feedback."""

    def __init__(self, max_delay: int, channels: int = 2):
        self.L = int(max_delay) + 8
        self.buf = np.zeros((self.L, channels))
        self.ch = channels

    def run(self, x, delays, fb=0.0, chunk=32):
        n = len(x)
        wet = np.empty((n, self.ch))
        cols = np.arange(self.ch)[None, :]
        for s in range(0, n, chunk):
            m = min(chunk, n - s)
            d = np.clip(delays[s:s + m], chunk + 2, self.L - 2)
            p = self.L + np.arange(m)[:, None] - d
            i0 = np.floor(p).astype(int)
            f = p - i0
            w = self.buf[i0, cols] * (1.0 - f) + self.buf[i0 + 1, cols] * f
            wet[s:s + m] = w
            self.buf = np.concatenate((self.buf[m:], x[s:s + m] + fb * w))
        return wet


class Flanger(Effect):
    name, short = "Flanger", "Flang"
    desc = "Swept comb filter with feedback"
    PARAMS = [
        ("rate", "Rate", 0.05, 5.0, 0.25, "Hz", "log"),
        ("depth", "Depth", 0.0, 1.0, 0.7, "", "lin"),
        ("delay", "Delay", 0.8, 8.0, 2.5, "ms", "lin"),
        ("fb", "Feedback", -0.9, 0.9, 0.5, "", "lin"),
        ("mix", "Mix", 0.0, 1.0, 0.5, "", "lin"),
    ]

    def setup(self):
        self.ph = 0.0
        self.line = ModDelay(self.rate * 0.02)

    def process(self, x):
        p, n = self.p, len(x)
        t = (np.arange(n) / self.rate * p["rate"] + self.ph)[:, None] + np.array([[0.0, 0.2]])
        base = p["delay"] * self.rate / 1000.0
        d = base * (1.0 + 0.9 * p["depth"] * np.sin(TAU * t))
        self.ph = (self.ph + n / self.rate * p["rate"]) % 1.0
        wet = self.line.run(x, d, fb=p["fb"])
        return x * (1.0 - 0.5 * p["mix"]) + wet * p["mix"]


class Chorus(Effect):
    name, short = "Chorus", "Chorus"
    desc = "Detuned modulated delay, stereo"
    PARAMS = [
        ("rate", "Rate", 0.1, 5.0, 0.8, "Hz", "log"),
        ("depth", "Depth", 0.0, 1.0, 0.5, "", "lin"),
        ("delay", "Delay", 10.0, 40.0, 20.0, "ms", "lin"),
        ("mix", "Mix", 0.0, 1.0, 0.45, "", "lin"),
    ]

    def setup(self):
        self.ph = 0.0
        self.line = ModDelay(self.rate * 0.06)

    def process(self, x):
        p, n = self.p, len(x)
        t = (np.arange(n) / self.rate * p["rate"] + self.ph)[:, None] + np.array([[0.0, 0.25]])
        base = p["delay"] * self.rate / 1000.0
        d = base * (1.0 + 0.35 * p["depth"] * np.sin(TAU * t))
        self.ph = (self.ph + n / self.rate * p["rate"]) % 1.0
        wet = self.line.run(x, d)
        return _mix(x, wet, p["mix"] * 0.6) + wet * 0.0


class Phaser(Effect):
    name, short = "Phaser", "Phase"
    desc = "All-pass notch sweep (feedback is chunk-delayed)"
    PARAMS = [
        ("rate", "Rate", 0.05, 5.0, 0.4, "Hz", "log"),
        ("depth", "Depth", 0.0, 1.0, 0.7, "", "lin"),
        ("fb", "Feedback", 0.0, 0.9, 0.4, "", "lin"),
        ("stages", "Stages", 2.0, 8.0, 4.0, "", "int"),
        ("mix", "Mix", 0.0, 1.0, 0.5, "", "lin"),
    ]
    CH = 32

    def setup(self):
        self.ph = 0.0
        self.zi = [np.zeros((1, 2)) for _ in range(8)]
        self.prev = np.zeros((self.CH, 2))

    def process(self, x):
        p, n, ch = self.p, len(x), self.CH
        out = np.empty_like(x)
        st = min(max(int(round(p["stages"] / 2.0)) * 2, 2), 8)
        for s in range(0, n, ch):
            m = min(ch, n - s)
            ph = self.ph + (s + m / 2.0) / self.rate * p["rate"]
            lfo = 0.5 + 0.5 * p["depth"] * math.sin(TAU * ph)
            fc = min(200.0 * (3500.0 / 200.0) ** lfo, self.rate * 0.45)
            t = math.tan(math.pi * fc / self.rate)
            a = (t - 1.0) / (t + 1.0)
            y = x[s:s + m] + p["fb"] * self.prev[:m]
            for k in range(st):
                y, self.zi[k] = signal.lfilter([a, 1.0], [1.0, a], y, axis=0, zi=self.zi[k])
            self.prev[:m] = y
            out[s:s + m] = y
        self.ph = (self.ph + n / self.rate * p["rate"]) % 1.0
        return _mix(x, out, p["mix"])


class Tremolo(Effect):
    name, short = "Tremolo", "Trem"
    desc = "Amplitude LFO; stereo phase turns it into an auto-pan"
    PARAMS = [
        ("rate", "Rate", 0.5, 20.0, 5.0, "Hz", "log"),
        ("depth", "Depth", 0.0, 1.0, 0.6, "", "lin"),
        ("stereo", "Stereo", 0.0, 1.0, 0.0, "", "lin"),
    ]

    def setup(self):
        self.ph = 0.0

    def process(self, x):
        p, n = self.p, len(x)
        t = (np.arange(n) / self.rate * p["rate"] + self.ph)[:, None] + np.array([[0.0, 0.5 * p["stereo"]]])
        g = 1.0 - p["depth"] * (0.5 + 0.5 * np.sin(TAU * t))
        self.ph = (self.ph + n / self.rate * p["rate"]) % 1.0
        return x * g


class Echo(Effect):
    name, short = "Echo", "Echo"
    desc = "Tape-style delay with filtered feedback"
    PARAMS = [
        ("time", "Time", 60.0, 1000.0, 350.0, "ms", "log"),
        ("fb", "Feedback", 0.0, 0.95, 0.4, "", "lin"),
        ("tone", "Tone", 500.0, 12000.0, 5000.0, "Hz", "log"),
        ("mix", "Mix", 0.0, 1.0, 0.35, "", "lin"),
    ]

    def setup(self):
        self.L = int(self.rate * 1.05)
        self.buf = np.zeros((self.L, 2))
        self.w = 0
        self.zi = np.zeros((1, 2, 2))

    def process(self, x):
        p, n = self.p, len(x)
        d = max(int(p["time"] * self.rate / 1000.0), n)
        idx = (self.w - d + np.arange(n)) % self.L
        old = self.buf[idx]
        sos = signal.butter(1, min(p["tone"], self.rate * 0.45), fs=self.rate, output="sos")
        wet, self.zi = signal.sosfilt(sos, old, axis=0, zi=self.zi)
        self.buf[(self.w + np.arange(n)) % self.L] = x + p["fb"] * wet
        self.w = (self.w + n) % self.L
        return x + wet * p["mix"]


class _Comb:
    def __init__(self, d):
        self.d, self.buf, self.w, self.zi = d, np.zeros(d), 0, np.zeros(1)

    def run(self, x, fb, damp):
        out = np.empty(len(x))
        for s in range(0, len(x), self.d):
            m = min(self.d, len(x) - s)
            pos = (self.w + np.arange(m)) % self.d
            old = self.buf[pos]
            lp, self.zi = signal.lfilter([1.0 - damp], [1.0, -damp], old, zi=self.zi)
            self.buf[pos] = x[s:s + m] + fb * lp
            self.w = (self.w + m) % self.d
            out[s:s + m] = old
        return out


class _Allpass:
    def __init__(self, d):
        self.d, self.buf, self.w = d, np.zeros(d), 0

    def run(self, x, g=0.5):
        out = np.empty(len(x))
        for s in range(0, len(x), self.d):
            m = min(self.d, len(x) - s)
            pos = (self.w + np.arange(m)) % self.d
            old = self.buf[pos]
            w = x[s:s + m] + g * old
            out[s:s + m] = -g * w + old
            self.buf[pos] = w
            self.w = (self.w + m) % self.d
        return out


class Reverb(Effect):
    name, short = "Reverb", "Verb"
    desc = "Freeverb-style room: 8 combs + 4 all-passes per side"
    PARAMS = [
        ("size", "Size", 0.0, 1.0, 0.6, "", "lin"),
        ("damp", "Damping", 0.0, 1.0, 0.5, "", "lin"),
        ("width", "Width", 0.0, 1.0, 1.0, "", "lin"),
        ("mix", "Mix", 0.0, 1.0, 0.25, "", "lin"),
    ]
    COMBS = (1116, 1188, 1277, 1356, 1422, 1491, 1557, 1617)
    ALLP = (556, 441, 341, 225)
    GAIN = 0.55

    def setup(self):
        k = self.rate / 44100.0
        self.combs = [[_Comb(int(d * k) + s) for d in self.COMBS] for s in (0, int(23 * k))]
        self.allp = [[_Allpass(int(d * k) + s) for d in self.ALLP] for s in (0, int(23 * k))]

    def process(self, x):
        p = self.p
        fb = 0.7 + 0.28 * p["size"]
        damp = 0.05 + 0.85 * p["damp"] * 0.6
        mono = x.mean(axis=1) * 0.03
        wet = []
        for side in range(2):
            acc = np.zeros(len(x))
            for c in self.combs[side]:
                acc += c.run(mono, fb, damp)
            for a in self.allp[side]:
                acc = a.run(acc)
            wet.append(acc * self.GAIN * 5.0)
        l, r = wet
        w = p["width"]
        wl = l * (0.5 + 0.5 * w) + r * (0.5 - 0.5 * w)
        wr = r * (0.5 + 0.5 * w) + l * (0.5 - 0.5 * w)
        return x * (1.0 - 0.3 * p["mix"]) + np.stack((wl, wr), axis=1) * p["mix"]


class Widener(Effect):
    name, short = "Stereo Widener", "Wide"
    desc = "Mid/side width: 0 mono, 1 unchanged, 2 extra wide"
    PARAMS = [("width", "Width", 0.0, 2.0, 1.4, "", "lin")]

    def process(self, x):
        mid = (x[:, 0] + x[:, 1]) * 0.5
        side = (x[:, 0] - x[:, 1]) * 0.5 * self.p["width"]
        return np.stack((mid + side, mid - side), axis=1)


ORDER = [Compressor, Overdrive, Crusher, Megaphone, Phaser, Flanger, Chorus, Tremolo, Echo, Reverb, Widener]


class FxRack:
    def __init__(self, rate: int):
        self.rate = rate
        self.fx = [cls(rate) for cls in ORDER]
        self.bypass = False

    def any_on(self) -> bool:
        return any(f.enabled for f in self.fx)

    def process(self, x: np.ndarray) -> np.ndarray:
        if self.bypass or not self.any_on():
            return x
        y = x.astype(np.float64)
        for f in self.fx:
            if f.enabled:
                y = f.process(y)
        return y.astype(np.float32)

    def by_short(self, name: str):
        for f in self.fx:
            if f.short.lower() == name.lower() or f.name.lower() == name.lower():
                return f
        return None

    def state(self) -> dict:
        return {f.short: {"on": f.enabled, **f.p} for f in self.fx}

    def load(self, st: dict) -> None:
        for f in self.fx:
            d = st.get(f.short)
            if not isinstance(d, dict):
                continue
            for k in f.p:
                if k in d:
                    try:
                        f.p[k] = float(d[k])
                    except (TypeError, ValueError):
                        pass
            f.set_enabled(bool(d.get("on", False)))
