"""DanEQ DSP core: RBJ biquad equalizer and spectrum analyzer."""
from __future__ import annotations

import math
import threading
from typing import List, Sequence

import numpy as np
from scipy import signal

GAIN_MIN = -12.0
GAIN_MAX = 12.0

# Band layouts. First band is a low shelf, last band is a high shelf,
# everything in between is a peaking filter.
LAYOUTS = {
    4: {"freqs": [80, 500, 3000, 12000], "q": 0.6},
    6: {"freqs": [60, 200, 600, 2000, 6000, 14000], "q": 0.9},
    8: {"freqs": [50, 125, 300, 700, 1500, 3500, 8000, 14000], "q": 1.1},
    10: {"freqs": [31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000], "q": 1.41},
}

REF_FREQS = LAYOUTS[10]["freqs"]

# Presets are defined on the 10 band layout and interpolated for the others.
PRESETS = {
    "Flat": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    "Bass boost": [6, 5, 4, 2, 0, 0, 0, 0, 0, 0],
    "Treble boost": [0, 0, 0, 0, 0, 1, 3, 4, 5, 6],
    "Vocal": [-2, -2, -1, 1, 3, 4, 3, 1, 0, -1],
    "Loudness": [6, 4, 1, 0, -1, 0, -1, 1, 4, 5],
    "Rock": [4, 3, -1, -3, -1, 2, 4, 5, 5, 5],
    "Electronic": [5, 4, 1, 0, -2, 2, 1, 1, 4, 5],
    "Classical": [0, 0, 0, 0, 0, 0, -2, -2, -2, -4],
}
PRESET_ORDER = list(PRESETS)


def fmt_freq(f: float) -> str:
    return f"{f / 1000:g}k" if f >= 1000 else f"{f:g}"


def preset_gains(name: str, freqs: Sequence[float]) -> List[float]:
    vals = PRESETS[name]
    out = np.interp(np.log2(freqs), np.log2(REF_FREQS), vals)
    return [float(round(v * 2) / 2) for v in out]


def biquad(kind: str, f0: float, gain_db: float, q: float, fs: float) -> List[float]:
    """RBJ cookbook biquad, returned as a normalized SOS row [b0 b1 b2 1 a1 a2]."""
    f0 = min(f0, 0.45 * fs)
    A = 10.0 ** (gain_db / 40.0)
    w0 = 2.0 * math.pi * f0 / fs
    cw, sw = math.cos(w0), math.sin(w0)
    alpha = sw / (2.0 * q)
    if kind == "peak":
        b0, b1, b2 = 1 + alpha * A, -2 * cw, 1 - alpha * A
        a0, a1, a2 = 1 + alpha / A, -2 * cw, 1 - alpha / A
    else:
        s = 2.0 * math.sqrt(A) * alpha
        if kind == "lowshelf":
            b0 = A * ((A + 1) - (A - 1) * cw + s)
            b1 = 2 * A * ((A - 1) - (A + 1) * cw)
            b2 = A * ((A + 1) - (A - 1) * cw - s)
            a0 = (A + 1) + (A - 1) * cw + s
            a1 = -2 * ((A - 1) + (A + 1) * cw)
            a2 = (A + 1) + (A - 1) * cw - s
        elif kind == "highshelf":
            b0 = A * ((A + 1) + (A - 1) * cw + s)
            b1 = -2 * A * ((A - 1) + (A + 1) * cw)
            b2 = A * ((A + 1) + (A - 1) * cw - s)
            a0 = (A + 1) - (A - 1) * cw + s
            a1 = 2 * ((A - 1) - (A + 1) * cw)
            a2 = (A + 1) - (A - 1) * cw - s
        else:
            raise ValueError(kind)
    return [b0 / a0, b1 / a0, b2 / a0, 1.0, a1 / a0, a2 / a0]


class Equalizer:
    """Graphic-style EQ: fixed center frequencies, adjustable gains."""

    def __init__(self, nbands: int = 10, rate: int = 48000, channels: int = 2):
        if nbands not in LAYOUTS:
            raise ValueError(f"bands must be one of {sorted(LAYOUTS)}")
        lay = LAYOUTS[nbands]
        self.nbands = nbands
        self.rate = rate
        self.channels = channels
        self.freqs = [float(f) for f in lay["freqs"]]
        self.q = float(lay["q"])
        self.kinds = ["lowshelf"] + ["peak"] * (nbands - 2) + ["highshelf"]
        self.gains = [0.0] * nbands
        self.preamp = 0.0
        self.bypass = False
        self._lock = threading.Lock()
        self._zi = np.zeros((nbands, 2, channels))
        self._sos = None
        self._pre = 1.0
        self._dirty = True

    # ---- parameter access -------------------------------------------------
    def set_gain(self, i: int, db: float) -> None:
        db = max(GAIN_MIN, min(GAIN_MAX, float(db)))
        with self._lock:
            self.gains[i] = db
            self._dirty = True

    def set_gains(self, gains: Sequence[float]) -> None:
        with self._lock:
            for i, g in enumerate(list(gains)[: self.nbands]):
                self.gains[i] = max(GAIN_MIN, min(GAIN_MAX, float(g)))
            self._dirty = True

    def set_preamp(self, db: float) -> None:
        with self._lock:
            self.preamp = max(-24.0, min(12.0, float(db)))
            self._dirty = True

    def set_bypass(self, flag: bool) -> None:
        with self._lock:
            self.bypass = bool(flag)

    def auto_headroom(self) -> float:
        """Set the preamp so the combined response never exceeds 0 dB."""
        with self._lock:
            self._ensure()
            sos = self._sos
        freqs = np.geomspace(20.0, min(20000.0, self.rate * 0.45), 512)
        _, h = signal.sosfreqz(sos, worN=2.0 * np.pi * freqs / self.rate)
        peak = float(20.0 * np.log10(np.abs(h).max()))
        self.set_preamp(-math.ceil(max(peak, 0.0) * 2.0) / 2.0 + 0.0)
        return self.preamp

    # ---- internals --------------------------------------------------------
    def _ensure(self) -> None:
        if self._dirty:
            rows = []
            for kind, f, g in zip(self.kinds, self.freqs, self.gains):
                q = self.q if kind == "peak" else 0.707
                rows.append(biquad(kind, f, g, q, self.rate))
            self._sos = np.array(rows, dtype=np.float64)
            self._pre = 10.0 ** (self.preamp / 20.0)
            self._dirty = False

    # ---- processing -------------------------------------------------------
    def process(self, x: np.ndarray) -> np.ndarray:
        """Filter a float32 block shaped (frames, channels)."""
        with self._lock:
            self._ensure()
            sos, pre, bypass = self._sos, self._pre, self.bypass
        if bypass:
            return x
        y, self._zi = signal.sosfilt(sos, x.astype(np.float64) * pre, axis=0, zi=self._zi)
        return y.astype(np.float32)

    def response_db(self, freqs: Sequence[float]) -> np.ndarray:
        """Exact magnitude response (dB) of what process() applies right now."""
        with self._lock:
            self._ensure()
            sos, bypass, preamp = self._sos, self.bypass, self.preamp
        f = np.asarray(freqs, dtype=np.float64)
        if bypass:
            return np.zeros_like(f)
        w = 2.0 * np.pi * f / self.rate
        _, h = signal.sosfreqz(sos, worN=w)
        return 20.0 * np.log10(np.maximum(np.abs(h), 1e-9)) + preamp


def to_apo(eq: "Equalizer") -> str:
    """Equalizer APO / EasyEffects style text. Shelf Q conventions differ slightly."""
    tag = {"lowshelf": "LSC", "peak": "PK", "highshelf": "HSC"}
    out = [f"Preamp: {eq.preamp:.1f} dB"]
    for i, (kind, f, g) in enumerate(zip(eq.kinds, eq.freqs, eq.gains), 1):
        q = eq.q if kind == "peak" else 0.707
        out.append(f"Filter {i}: ON {tag[kind]} Fc {f:g} Hz Gain {g:.1f} dB Q {q:.3f}")
    return "\n".join(out) + "\n"


class Spectrum:
    """Multi-resolution FFT analyzer mapping a mono block onto log-spaced bars (dB).

    Bass uses the longest window (fine frequency resolution), treble the shortest
    (fine time resolution), which makes the display both detailed and fluid.
    """

    def __init__(self, rate: int, nfft: int = 8192):
        self.rate = rate
        self.nfft = nfft
        self.sizes = (nfft, nfft // 2, nfft // 4)
        self.windows = {n: np.hanning(n) for n in self.sizes}
        self.norms = {n: 2.0 / self.windows[n].sum() for n in self.sizes}
        self._cache = {}

    def _plan(self, size: int, nbars: int, fmin: float, fmax: float):
        key = (size, nbars, fmin, fmax)
        if key not in self._cache:
            edges = np.geomspace(fmin, fmax, nbars + 1)
            binhz = self.rate / size
            nbins = size // 2 + 1
            lo = edges[:-1] / binhz
            hi = edges[1:] / binhz
            centers_hz = np.sqrt(edges[:-1] * edges[1:])
            lo_i = np.minimum(np.floor(lo).astype(int), nbins - 1)
            hi_i = np.minimum(np.maximum(np.ceil(hi).astype(int), lo_i + 1), nbins)
            wide = [(k, int(a), int(b)) for k, (a, b) in enumerate(zip(lo_i, hi_i)) if hi[k] - lo[k] >= 1.0]
            self._cache[key] = (0.5 * (lo + hi), centers_hz, wide)
        return self._cache[key]

    def _power(self, samples: np.ndarray, size: int, nbars: int, fmin: float, fmax: float):
        x = samples[-size:]
        if len(x) < size:
            x = np.concatenate((np.zeros(size - len(x), dtype=x.dtype), x))
        spec = np.abs(np.fft.rfft(x * self.windows[size])) * self.norms[size]
        p = spec * spec
        centers_bin, centers_hz, wide = self._plan(size, nbars, fmin, fmax)
        val = np.interp(centers_bin, np.arange(len(p)), p)
        for k, a, b in wide:
            val[k] = p[a:b].max()
        return val, centers_hz

    def bars(self, samples: np.ndarray, nbars: int, fmin: float = 30.0,
             fmax: float = 18000.0, tilt: float = 3.0) -> np.ndarray:
        fmax = min(fmax, self.rate / 2 * 0.95)
        big, mid, small = self.sizes
        v_big, centers = self._power(samples, big, nbars, fmin, fmax)
        v_mid, _ = self._power(samples, mid, nbars, fmin, fmax)
        v_small, _ = self._power(samples, small, nbars, fmin, fmax)
        val = np.where(centers < 300.0, v_big, np.where(centers < 2500.0, v_mid, v_small))
        db = 10.0 * np.log10(val + 1e-12)
        return db + tilt * np.log2(centers / 1000.0)
