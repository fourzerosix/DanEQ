"""Built-in signal generators for demos and testing (no audio hardware needed)."""
from __future__ import annotations

import numpy as np
from scipy import signal

TAU = 2.0 * np.pi


def music(rate: int, block: int, bpm: float = 120.0):
    """A looping drum + bass + arp + pad groove with energy across the spectrum."""
    rng = np.random.default_rng(7)
    beat = 60.0 / bpm
    bass_notes = np.array([55.0, 55.0, 73.42, 65.41])
    arp = np.array([440.0, 523.25, 659.25, 783.99, 659.25, 523.25, 440.0, 392.0])
    pos = 0
    while True:
        t = (pos + np.arange(block)) / rate
        tb = t % beat
        kick = np.sin(TAU * (45 * tb + 90 * (1 - np.exp(-30 * tb)) / 30)) * np.exp(-tb * 10)
        th = (t + beat / 2) % beat
        hat = np.diff(rng.standard_normal(block + 1)) * np.exp(-th * 70) * 0.25
        ts = (t - beat) % (2 * beat)
        snare = (rng.standard_normal(block) * 0.5 + np.sin(TAU * 190 * ts)) * np.exp(-ts * 18) * 0.35
        fb = bass_notes[(t // beat).astype(int) % 4]
        bass = (np.sin(TAU * fb * t) + 0.4 * np.sin(2 * TAU * fb * t) + 0.2 * np.sin(3 * TAU * fb * t))
        bass *= np.exp(-tb * 2.0) * np.minimum(tb * 150, 1.0) * 0.35
        ta = t % (beat / 2)
        fa = arp[(t // (beat / 2)).astype(int) % len(arp)]
        lead = (np.sin(TAU * fa * t) + 0.3 * np.sin(2 * TAU * fa * t)) * np.exp(-ta * 7) * np.minimum(ta * 300, 1.0) * 0.18
        pad = sum(np.sin(TAU * f * t) for f in (220.0, 261.63, 329.63)) * 0.03 * (0.6 + 0.4 * np.sin(TAU * 0.2 * t))
        left = kick * 0.8 + snare * 0.7 + hat * 0.4 + bass + lead * 0.7 + pad
        right = kick * 0.8 + snare * 0.7 + hat * 0.8 + bass + lead * 1.0 + pad
        out = np.tanh(np.stack((left, right), axis=1)) * 0.7
        pos += block
        yield out.astype(np.float32)


def pink(rate: int, block: int, level: float = 1.4):
    """Pink noise (Paul Kellet filter). Great for checking EQ response by eye."""
    rng = np.random.default_rng(1)
    b = [0.049922035, -0.095993537, 0.050612699, -0.004408786]
    a = [1.0, -2.494956002, 2.017265875, -0.522189400]
    zi = np.zeros((max(len(a), len(b)) - 1, 2))
    while True:
        w = rng.standard_normal((block, 2))
        y, zi = signal.lfilter(b, a, w, axis=0, zi=zi)
        yield (y * level).astype(np.float32)


def sweep(rate: int, block: int, seconds: float = 12.0, f0: float = 20.0, f1: float = 20000.0):
    """Repeating logarithmic sine sweep. Shows the EQ curve as a moving peak."""
    f1 = min(f1, rate * 0.45)
    r = f1 / f0
    k = TAU * f0 * seconds / np.log(r)
    pos = 0
    while True:
        t = ((pos + np.arange(block)) / rate) % seconds
        y = 0.3 * np.sin(k * (r ** (t / seconds) - 1.0))
        pos += block
        yield np.stack((y, y), axis=1).astype(np.float32)


GENERATORS = {"music": music, "pink": pink, "sweep": sweep}
