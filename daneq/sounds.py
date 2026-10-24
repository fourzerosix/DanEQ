"""Procedural test sounds: animals, cartoon effects, chiptune, dial-up, PA babble.

Everything here is synthesized from scratch (no recordings, no licensing questions).
Each builder returns a stereo float32 buffer that the engine loops.
"""
from __future__ import annotations

import numpy as np
from scipy import signal

from . import synth

TAU = 2.0 * np.pi


# ---- helpers ------------------------------------------------------------------
def _t(sr, dur):
    return np.arange(int(sr * dur)) / sr


def _glide(t, pts):
    xs, ys = zip(*pts)
    return np.interp(t, xs, ys)


def _env(t, a=0.02, r=0.1, dur=None):
    dur = dur if dur is not None else t[-1] + 1.0 / max(len(t), 1)
    return np.minimum(t / max(a, 1e-4), 1.0) * np.minimum((dur - t) / max(r, 1e-4), 1.0).clip(0, 1)


def _voice(f0, sr, forms, rng, noise=0.0, tilt=0.9):
    """Source-filter voice: saw + noise through resonators (formants)."""
    ph = np.cumsum(f0 / sr)
    src = (2.0 * (ph % 1.0) - 1.0) * (1.0 - noise) + rng.standard_normal(len(f0)) * noise
    src = signal.lfilter([1.0], [1.0, -tilt], src)
    out = np.zeros_like(src)
    for f, q, g in forms:
        b, a = signal.iirpeak(min(f, sr * 0.45), q, fs=sr)
        out += g * signal.lfilter(b, a, src)
    return out / max(np.abs(out).max(), 1e-9)


def _pad(sr, dur):
    return np.zeros(int(sr * dur))


def _norm(x, peak=0.8):
    return x * (peak / max(np.abs(x).max(), 1e-9))


def _pan(mono, p):
    """p in -1..1, constant power."""
    a = (p + 1.0) * np.pi / 4.0
    return np.stack((mono * np.cos(a), mono * np.sin(a)), axis=1)


# ---- animals --------------------------------------------------------------------
def dog(sr, rng):
    out = []
    for _ in range(int(rng.integers(2, 4))):
        t = _t(sr, 0.17)
        f0 = _glide(t, [(0, 430), (0.04, 390), (0.17, 250)]) * (1 + 0.04 * rng.standard_normal())
        y = _voice(f0, sr, [(700, 6, 1.0), (1250, 8, 0.7), (2600, 8, 0.3)], rng, noise=0.25)
        out += [y * np.minimum(t * 300, 1) * np.exp(-t * 13), _pad(sr, 0.13)]
    return np.concatenate(out)


def cat(sr, rng):
    t = _t(sr, 0.95)
    f0 = _glide(t, [(0, 380), (0.18, 640), (0.55, 560), (0.95, 330)]) * (1 + 0.02 * np.sin(TAU * 6 * t))
    ee = _voice(f0, sr, [(330, 8, 1.0), (2400, 10, 0.6)], rng, 0.05)
    ow = _voice(f0, sr, [(800, 8, 1.0), (1300, 9, 0.7)], rng, 0.05)
    w = np.clip((t - 0.25) / 0.35, 0, 1)
    return (ee * (1 - w) + ow * w) * _env(t, 0.08, 0.3)


def lion(sr, rng):
    t = _t(sr, 3.0)
    f0 = _glide(t, [(0, 60), (0.3, 88), (1.2, 72), (2.2, 55), (3.0, 40)])
    y = _voice(f0, sr, [(250, 5, 1.0), (600, 6, 0.8), (1100, 8, 0.4)], rng, 0.35)
    y *= (1 - 0.7 * (0.5 + 0.5 * np.sin(TAU * 27 * t))) * _env(t, 0.3, 1.0)
    cough = []
    for _ in range(3):
        tc = _t(sr, 0.22)
        yc = _voice(_glide(tc, [(0, 75), (0.22, 50)]), sr, [(300, 5, 1), (700, 6, .7)], rng, 0.4)
        cough += [yc * np.exp(-tc * 9) * np.minimum(tc * 80, 1), _pad(sr, 0.18)]
    return np.concatenate([y * 1.0, _pad(sr, 0.15)] + cough)


def bear(sr, rng):
    out = []
    for dur in (1.7, 1.1):
        t = _t(sr, dur)
        f0 = _glide(t, [(0, 48), (0.3 * dur, 66), (dur, 34)])
        y = _voice(f0, sr, [(200, 5, 1.0), (500, 6, 0.9), (900, 6, 0.5)], rng, 0.5)
        am = 0.55 + 0.45 * np.sin(TAU * np.cumsum(18 + 14 * rng.random(len(t)) * 0 + 8 * np.sin(TAU * 3 * t)) / sr)
        out += [y * am * _env(t, 0.15, 0.5), _pad(sr, 0.25)]
    return np.concatenate(out)


def wolf(sr, rng):
    t = _t(sr, 3.4)
    f0 = _glide(t, [(0, 280), (0.4, 520), (1.4, 610), (2.6, 520), (3.4, 330)])
    f0 = f0 * (1 + 0.015 * np.sin(TAU * 5.5 * t) * np.clip(t - 0.8, 0, 1))
    return _voice(f0, sr, [(450, 10, 1.0), (1000, 10, 0.5)], rng, 0.08) * _env(t, 0.5, 0.9)


def cow(sr, rng):
    t = _t(sr, 1.9)
    f0 = _glide(t, [(0, 110), (0.3, 138), (1.2, 126), (1.9, 94)])
    oo = _voice(f0, sr, [(300, 5, 1.0), (800, 6, 0.4)], rng, 0.03)
    aa = _voice(f0, sr, [(650, 6, 1.0), (1100, 7, 0.6)], rng, 0.03)
    w = np.clip(np.sin(np.pi * np.clip((t - 0.2) / 1.2, 0, 1)), 0, 1)
    return (oo * (1 - w) + aa * w) * _env(t, 0.12, 0.5)


def sheep(sr, rng):
    out = []
    for _ in range(2):
        t = _t(sr, 0.9)
        f0 = 320 * (1 + 0.04 * np.sin(TAU * 28 * t)) * _glide(t, [(0, 1.1), (0.9, 0.85)])
        y = _voice(f0, sr, [(900, 8, 1.0), (1700, 9, 0.7)], rng, 0.12)
        out += [y * (0.6 + 0.4 * np.sin(TAU * 32 * t)) * _env(t, 0.05, 0.25), _pad(sr, 0.2)]
    return np.concatenate(out)


def duck(sr, rng):
    out = []
    for _ in range(3):
        t = _t(sr, 0.22)
        y = _voice(_glide(t, [(0, 330), (0.22, 250)]), sr,
                   [(700, 10, 1.0), (1500, 10, 0.8), (2800, 10, 0.4)], rng, 0.15)
        out += [y * (1 + 0.5 * np.sin(TAU * 90 * t)) * np.exp(-t * 8) * np.minimum(t * 200, 1), _pad(sr, 0.12)]
    return np.concatenate(out)


def bird(sr, rng):
    out = []
    for _ in range(6):
        t = _t(sr, 0.09)
        s = 3000 + 1500 * rng.random()
        f = _glide(t, [(0, s), (0.09, s + rng.choice([-1800, 1800]))])
        ph = np.cumsum(TAU * f / sr)
        out += [(np.sin(ph) + 0.3 * np.sin(2 * ph)) * np.sin(np.pi * t / 0.09) ** 2, _pad(sr, 0.05 + 0.06 * rng.random())]
    return np.concatenate(out)


def frog(sr, rng):
    out = []
    for _ in range(2):
        t = _t(sr, 0.45)
        f = _glide(t, [(0, 620), (0.45, 430)])
        y = np.sin(np.cumsum(TAU * f / sr)) * (0.5 + 0.5 * np.sin(TAU * 55 * t))
        y += rng.standard_normal(len(t)) * 0.05
        out += [y * _env(t, 0.03, 0.15), _pad(sr, 0.25)]
    return np.concatenate(out)


def owl(sr, rng):
    out = []
    for dur in (0.3, 0.2, 0.2, 0.55):
        t = _t(sr, dur)
        f = _glide(t, [(0, 340), (0.1, 360), (dur, 300)])
        ph = np.cumsum(TAU * f / sr)
        out += [(np.sin(ph) + 0.3 * np.sin(2 * ph)) * _env(t, 0.06, 0.12), _pad(sr, 0.14)]
    return np.concatenate(out)


def rooster(sr, rng):
    out = []
    for dur, a, b in ((0.3, 650, 900), (0.2, 780, 780), (0.35, 1000, 1120), (1.0, 1060, 680)):
        t = _t(sr, dur)
        f0 = _glide(t, [(0, a), (dur, b)]) * (1 + 0.02 * np.sin(TAU * 8 * t) * (dur > 0.9))
        y = _voice(f0, sr, [(900, 8, 1.0), (2000, 9, 0.7)], rng, 0.1)
        out += [y * _env(t, 0.02, 0.08), _pad(sr, 0.04)]
    return np.concatenate(out)


def horse(sr, rng):
    t = _t(sr, 2.3)
    f0 = _glide(t, [(0, 600), (0.2, 1100), (0.6, 900), (1.4, 700), (2.3, 350)])
    f0 *= 1 + 0.08 * np.sin(TAU * 10 * t) * np.clip(t - 0.5, 0, 1) * (t < 1.5)
    y = _voice(f0, sr, [(700, 6, 1.0), (1800, 8, 0.8), (3000, 8, 0.3)], rng, 0.2)
    return y * _env(t, 0.05, 0.5)


def elephant(sr, rng):
    t = _t(sr, 1.9)
    f0 = _glide(t, [(0, 400), (0.3, 750), (1.2, 850), (1.9, 600)])
    y = _voice(f0, sr, [(800, 5, 1.0), (2000, 6, 0.9), (3200, 7, 0.4)], rng, 0.15)
    y = np.tanh(y * 3.0) * (1 - 0.25 * (0.5 + 0.5 * np.sin(TAU * 14 * t)))
    return y * _env(t, 0.1, 0.5)


def pig(sr, rng):
    out = []
    for _ in range(2):
        t = _t(sr, 0.55)
        f0 = _glide(t, [(0, 170), (0.1, 240), (0.55, 140)]) * (1 + 0.03 * np.sin(TAU * 20 * t))
        y = _voice(f0, sr, [(400, 7, 1.0), (1500, 8, 0.6)], rng, 0.25)
        out += [y * _env(t, 0.03, 0.2), _pad(sr, 0.25)]
    return np.concatenate(out)


def whale(sr, rng):
    t = _t(sr, 9.0)
    f = _glide(t, [(0, 110), (2, 300), (4, 180), (6, 420), (9, 150)]) * (1 + 0.04 * np.sin(TAU * 0.4 * t))
    ph = np.cumsum(TAU * f / sr)
    y = sum(np.sin(k * ph) / k for k in range(1, 5))
    return y * _env(t, 1.5, 2.5)


def cricket(sr, rng):
    out = []
    for _ in range(14):
        for _ in range(3):
            t = _t(sr, 0.02)
            out += [np.sin(TAU * 4500 * t) * np.sin(np.pi * t / 0.02), _pad(sr, 0.012)]
        out.append(_pad(sr, 0.09 + 0.05 * rng.random()))
    return np.concatenate(out) * 0.6


ANIMALS = {f.__name__: f for f in (dog, cat, lion, bear, wolf, cow, sheep, duck, bird, frog,
                                   owl, rooster, horse, elephant, pig, whale, cricket)}


def _animal_buffer(sr, fns, seconds=24.0, seed=5):
    rng = np.random.default_rng(seed)
    parts, total, k = [], 0.0, 0
    while total < seconds:
        fn = fns[k % len(fns)]
        clip = _norm(fn(sr, rng), 0.8)
        st = _pan(clip, float(rng.uniform(-0.7, 0.7)))
        gap = np.zeros((int(sr * (0.5 + rng.random() * 0.9)), 2))
        parts += [st, gap]
        total += (len(st) + len(gap)) / sr
        k += 1
    return np.vstack(parts)


# ---- cartoon sound effects ------------------------------------------------------
def _tone(sr, f, dur, shape="sine", a=0.01, r=0.05, vib=0.0):
    t = _t(sr, dur)
    ff = f * (1 + vib * np.sin(TAU * 6 * t)) if np.isscalar(f) else f
    ph = np.cumsum(TAU * (ff if not np.isscalar(ff) else np.full(len(t), ff)) / sr)
    y = np.sin(ph) if shape == "sine" else signal.sawtooth(ph) if shape == "saw" else np.sign(np.sin(ph))
    return y * _env(t, a, r)


def cartoon(sr, block=None, **_):
    rng = np.random.default_rng(9)
    g = lambda d: np.zeros(int(sr * d))  # noqa: E731
    parts = []
    t = _t(sr, 0.7)                                      # slide whistle up
    parts += [np.sin(np.cumsum(TAU * _glide(t, [(0, 300), (0.7, 1800)]) * (1 + .01 * np.sin(TAU * 7 * t)) / sr)) * _env(t, .02, .05), g(.4)]
    t = _t(sr, 0.7)                                      # and down
    parts += [np.sin(np.cumsum(TAU * _glide(t, [(0, 1800), (0.7, 250)]) / sr)) * _env(t, .02, .05), g(.5)]
    t = _t(sr, 0.9)                                      # boing
    f = 140 + 220 * np.exp(-t * 4) * (1 + 0.6 * np.sin(TAU * 11 * t))
    parts += [np.sin(np.cumsum(TAU * f / sr)) * np.exp(-t * 3.5), g(.5)]
    t = _t(sr, 0.25)                                     # bonk
    parts += [np.sin(np.cumsum(TAU * _glide(t, [(0, 260), (0.25, 90)]) / sr)) * np.exp(-t * 18), g(.5)]
    for k, f0 in enumerate([1047, 1175, 1319, 1397, 1568, 1760, 1976, 2093]):   # xylophone run
        t = _t(sr, 0.3)
        y = (np.sin(TAU * f0 * t) + 0.35 * np.sin(TAU * 3.9 * f0 * t)) * np.exp(-t * 14)
        parts += [y, g(0.07)]
    parts.append(g(.5))
    for f0, d in ((233, 0.45), (220, 0.45), (208, 0.45), (196, 1.3)):               # sad trombone
        t = _t(sr, d)
        f = f0 * (1 + 0.02 * np.sin(TAU * 5.5 * t) * (d > 1)) * (1 - 0.06 * (t / d) ** 3 * (d > 1))
        y = signal.sawtooth(np.cumsum(TAU * f / sr))
        sos = signal.butter(2, 900 + 600 * np.sin(TAU * 2 * t) ** 2 * (d > 1), fs=sr, output="sos") if False else signal.butter(2, 1100, fs=sr, output="sos")
        parts += [signal.sosfilt(sos, y) * _env(t, .04, .08), g(.04)]
    parts.append(g(.6))
    chord = np.zeros(int(sr * 1.2))                                                  # ta-da
    for f0, st, d in ((392, 0.0, 0.18), (523, 0.18, 0.18), (659, 0.36, 0.84), (784, 0.36, 0.84), (1047, 0.36, 0.84)):
        y = signal.sawtooth(np.cumsum(TAU * np.full(int(sr * d), f0) / sr)) * _env(_t(sr, d), .01, .2)
        i = int(sr * st)
        chord[i:i + len(y)] += y * 0.4
    parts += [signal.sosfilt(signal.butter(2, 3000, fs=sr, output="sos"), chord), g(.6)]
    n = rng.standard_normal(int(sr * 0.35))                                          # zip
    sw = signal.sosfilt(signal.butter(2, [800, 3000], "bandpass", fs=sr, output="sos"), n)
    parts += [sw * np.linspace(0.1, 1, len(sw)), g(.5)]
    for _ in range(5):                                                               # record scratch
        d = 0.09 + 0.08 * rng.random()
        t = _t(sr, d)
        nz = signal.sosfilt(signal.butter(2, [300 + 1500 * rng.random(), 3500], "bandpass", fs=sr, output="sos"),
                            rng.standard_normal(len(t)))
        parts += [nz * np.sin(np.pi * t / d) * 1.2]
    parts.append(g(.5))
    for f0, d in ((784, 0.28), (622, 0.4)):                                          # cuckoo
        parts += [_tone(sr, f0, d, a=.02, r=.12)]
    parts.append(g(.5))
    t = _t(sr, 0.35)                                                                 # ricochet
    f = 2600 * np.exp(-t * 7) + 200
    parts += [np.sin(np.cumsum(TAU * f * (1 + 0.1 * np.sin(TAU * 40 * t)) / sr)) * np.exp(-t * 6), g(1.0)]
    mono = _norm(np.concatenate(parts), 0.8)
    return np.stack((mono, mono), axis=1).astype(np.float32)


# ---- chiptune melodies ----------------------------------------------------------
_NOTE = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def _freq(name):
    if name == "R":
        return 0.0
    n = _NOTE[name[0]] + (1 if "#" in name else 0)
    octave = int(name[-1])
    return 440.0 * 2 ** ((12 * (octave + 1) + n - 69) / 12.0)


def _chip(sr, notes, bpm):
    beat = 60.0 / bpm
    out = []
    for name, beats in notes:
        d = beats * beat
        f = _freq(name)
        t = _t(sr, d)
        if f == 0:
            out.append(np.zeros(len(t)))
            continue
        sq = np.sign(np.sin(TAU * f * t + 0.0)) * 0.5 + np.sign(np.sin(TAU * f * 0.5 * t)) * 0.18
        out.append(sq * _env(t, 0.004, min(0.05, d * 0.5)) * (0.55 + 0.45 * np.exp(-t * 3)))
        out[-1] = out[-1] * np.minimum((d - t) / 0.02, 1)
    mono = _norm(np.concatenate(out + [np.zeros(int(sr * beat))]), 0.6)
    return np.stack((mono, mono), axis=1)


def _parse(s):
    return [(a, float(b)) for a, b in (tok.split(":") for tok in s.split())]


MELODIES = {
    "tetris": (150, "E5:1 B4:.5 C5:.5 D5:1 C5:.5 B4:.5 A4:1 A4:.5 C5:.5 E5:1 D5:.5 C5:.5 B4:1.5 C5:.5 D5:1 E5:1 C5:1 A4:1 A4:1 R:1 "
                    "D5:1.5 F5:.5 A5:1 G5:.5 F5:.5 E5:1.5 C5:.5 E5:1 D5:.5 C5:.5 B4:1 B4:.5 C5:.5 D5:1 E5:1 C5:1 A4:1 A4:1 R:1"),
    "ode": (116, "E4:1 E4:1 F4:1 G4:1 G4:1 F4:1 E4:1 D4:1 C4:1 C4:1 D4:1 E4:1 E4:1.5 D4:.5 D4:2 "
                 "E4:1 E4:1 F4:1 G4:1 G4:1 F4:1 E4:1 D4:1 C4:1 C4:1 D4:1 E4:1 D4:1.5 C4:.5 C4:2"),
    "elise": (130, "E5:.5 D#5:.5 E5:.5 D#5:.5 E5:.5 B4:.5 D5:.5 C5:.5 A4:1.5 C4:.5 E4:.5 A4:.5 B4:1.5 E4:.5 G#4:.5 B4:.5 C5:1.5 "
                   "E4:.5 E5:.5 D#5:.5 E5:.5 D#5:.5 E5:.5 B4:.5 D5:.5 C5:.5 A4:1.5 C4:.5 E4:.5 A4:.5 B4:1.5 E4:.5 C5:.5 B4:.5 A4:3"),
    "birthday": (110, "G4:.75 G4:.25 A4:1 G4:1 C5:1 B4:2 G4:.75 G4:.25 A4:1 G4:1 D5:1 C5:2 "
                      "G4:.75 G4:.25 G5:1 E5:1 C5:1 B4:1 A4:1 F5:.75 F5:.25 E5:1 C5:1 D5:1 C5:2"),
}


# ---- dial-up modem (impressionistic) ---------------------------------------------
_DTMF = {"1": (697, 1209), "2": (697, 1336), "3": (697, 1477), "4": (770, 1209), "5": (770, 1336),
         "6": (770, 1477), "7": (852, 1209), "8": (852, 1336), "9": (852, 1477), "*": (941, 1209),
         "0": (941, 1336), "#": (941, 1477)}


def _dtmf(sr, digits, tone=0.09, gap=0.07):
    out = []
    for ch in digits:
        if ch not in _DTMF:
            continue
        lo, hi = _DTMF[ch]
        t = _t(sr, tone)
        out += [(np.sin(TAU * lo * t) + np.sin(TAU * hi * t)) * 0.5 * np.minimum(np.minimum(t, tone - t) / 0.004, 1),
                np.zeros(int(sr * gap))]
    return np.concatenate(out)


def dtmf(sr, block=None, **_):
    mono = _norm(np.concatenate([_dtmf(sr, "8675309", 0.12, 0.08), _pad(sr, 1.2)]), 0.7)
    return np.stack((mono, mono), axis=1).astype(np.float32)


def dialup(sr, block=None, **_):
    rng = np.random.default_rng(11)
    t = _t(sr, 1.0)
    dial = 0.4 * (np.sin(TAU * 350 * t) + np.sin(TAU * 440 * t))
    seq = [dial, _dtmf(sr, "5551212"), _pad(sr, 0.8)]
    for _ in range(2):                                        # ring
        t = _t(sr, 0.9)
        seq += [0.3 * (np.sin(TAU * 440 * t) + np.sin(TAU * 480 * t)) * (t < 0.4), _pad(sr, 0.2)]
    t = _t(sr, 1.6)                                           # answer tone with phase reversals
    seq.append(0.5 * np.sin(TAU * 2100 * t + np.pi * (np.floor(t / 0.45) % 2)))
    t = _t(sr, 0.5)
    seq.append(0.4 * np.sin(np.cumsum(TAU * _glide(t, [(0, 1300), (0.5, 2400)]) / sr)))
    for dur in (3.0, 2.5):                                    # training screech
        n = int(sr * dur)
        t = np.arange(n) / sr
        fsk = np.where(rng.random(int(dur * 60) + 2)[(t * 60).astype(int)] > 0.5, 2400.0, 1200.0)
        carrier = np.sin(np.cumsum(TAU * fsk / sr))
        nz = signal.sosfilt(signal.butter(2, [600, 3200], "bandpass", fs=sr, output="sos"), rng.standard_normal(n))
        sweep = np.sin(np.cumsum(TAU * (900 + 1500 * (0.5 + 0.5 * np.sin(TAU * 0.7 * t))) / sr))
        seq.append((0.35 * carrier + 0.45 * nz * (0.6 + 0.4 * np.sin(TAU * 3 * t)) + 0.3 * sweep) * np.minimum(t / 0.1, 1))
    n = int(sr * 3.0)
    nz = signal.sosfilt(signal.butter(2, [400, 2800], "bandpass", fs=sr, output="sos"), rng.standard_normal(n))
    seq += [nz * 0.5, _pad(sr, 2.0)]
    mono = _norm(np.concatenate(seq), 0.7)
    return np.stack((mono, mono), axis=1).astype(np.float32)


# ---- loudspeaker babble -----------------------------------------------------------
_VOWELS = [(730, 1090), (270, 2290), (300, 870), (530, 1840), (660, 1720)]


def loudspeaker(sr, block=None, **_):
    """Speech-like syllable babble (no words) through a bullhorn: a PA test signal."""
    rng = np.random.default_rng(21)
    parts = []
    for _ in range(5):
        base = 120 + 25 * rng.random()
        for k in range(int(rng.integers(6, 11))):
            d = 0.11 + 0.14 * rng.random()
            t = _t(sr, d)
            f0 = base * (1.12 - 0.02 * k) * _glide(t, [(0, 1.03), (d, 0.96)])
            v1, v2 = _VOWELS[int(rng.integers(0, 5))], _VOWELS[int(rng.integers(0, 5))]
            w = np.clip(t / d, 0, 1)
            y1 = _voice(f0, sr, [(v1[0], 9, 1.0), (v1[1], 11, 0.6), (2600, 12, 0.2)], rng, 0.04)
            y2 = _voice(f0, sr, [(v2[0], 9, 1.0), (v2[1], 11, 0.6), (2600, 12, 0.2)], rng, 0.04)
            y = (y1 * (1 - w) + y2 * w) * np.sin(np.pi * t / d) ** 0.6
            burst = rng.standard_normal(int(sr * 0.02)) * 0.25 * np.exp(-np.arange(int(sr * 0.02)) / (sr * 0.006))
            parts += [np.concatenate((burst, y * 0.9)), _pad(sr, 0.02 + 0.05 * rng.random())]
        parts.append(_pad(sr, 0.7))
    x = np.concatenate(parts)
    sos = np.vstack((signal.butter(3, 420, "highpass", fs=sr, output="sos"),
                     signal.butter(3, 3400, "lowpass", fs=sr, output="sos")))
    x = np.tanh(signal.sosfilt(sos, x) * 4.0) * 0.7
    for d, g in ((0.18, 0.32), (0.43, 0.18), (0.8, 0.08)):      # reflections off buildings
        i = int(sr * d)
        x[i:] += g * x[:-i]
    n = len(x)
    x += 0.02 * signal.sosfilt(signal.butter(2, [300, 4000], "bandpass", fs=sr, output="sos"), rng.standard_normal(n))
    for at in (9.0, 24.0):                                       # a little feedback squeal
        i = int(sr * at)
        t = _t(sr, 0.45)
        sq = 0.25 * np.sin(np.cumsum(TAU * _glide(t, [(0, 2300), (0.45, 2750)]) / sr)) * np.sin(np.pi * t / 0.45) ** 2
        if i + len(sq) < n:
            x[i:i + len(sq)] += sq
    mono = _norm(x, 0.8)
    return np.stack((mono, mono), axis=1).astype(np.float32)


def siren(sr, block=None, **_):
    t = _t(sr, 8.0)
    wail = 650 + 450 * (0.5 - 0.5 * np.cos(TAU * t / 4.0))
    yelp = 650 + 450 * (0.5 - 0.5 * np.cos(TAU * t * 3.0))
    f = np.where(t < 4.0, wail, yelp)
    y = np.sign(np.sin(np.cumsum(TAU * f / sr))) * 0.4 + np.sin(np.cumsum(TAU * f / sr)) * 0.3
    return np.stack((y, y), axis=1).astype(np.float32)


_MORSE = {"A": ".-", "D": "-..", "E": ".", "N": "-.", "Q": "--.-", "S": "...", "O": "---"}


def morse(sr, block=None, text="DANEQ", wpm=15, **_):
    unit = 1.2 / wpm
    parts = []
    for ch in text.upper():
        for sym in _MORSE.get(ch, ""):
            d = unit * (3 if sym == "-" else 1)
            t = _t(sr, d)
            parts += [np.sin(TAU * 650 * t) * np.minimum(np.minimum(t, d - t) / 0.005, 1), _pad(sr, unit)]
        parts.append(_pad(sr, unit * 2))
    parts.append(_pad(sr, unit * 7))
    y = _norm(np.concatenate(parts), 0.6)
    return np.stack((y, y), axis=1).astype(np.float32)


# ---- registry -------------------------------------------------------------------------
def _loop(buf: np.ndarray, block: int):
    n, pos = len(buf), 0
    while True:
        if pos + block <= n:
            out = buf[pos:pos + block]
            pos += block
        else:
            out = np.concatenate((buf[pos:], buf[: pos + block - n]))
            pos = pos + block - n
        yield np.ascontiguousarray(out, dtype=np.float32)


def _make_animal(name):
    def factory(rate, block, **_):
        fns = list(ANIMALS.values()) if name == "zoo" else [ANIMALS[name]]
        return _loop(_animal_buffer(rate, fns, 60.0 if name == "zoo" else 24.0).astype(np.float32), block)
    return factory


def _make_buffered(fn):
    def factory(rate, block, **opts):
        return _loop(fn(rate, **opts), block)
    return factory


def _make_melody(name):
    bpm, notes = MELODIES[name]

    def factory(rate, block, **_):
        return _loop(_chip(rate, _parse(notes), bpm).astype(np.float32), block)
    return factory


BUFFERED = {name: _make_animal(name) for name in ANIMALS}
BUFFERED["zoo"] = _make_animal("zoo")
BUFFERED.update({name: _make_melody(name) for name in MELODIES})
BUFFERED.update({n: _make_buffered(f) for n, f in (("cartoon", cartoon), ("dialup", dialup), ("dtmf", dtmf),
                                                   ("loudspeaker", loudspeaker), ("siren", siren), ("morse", morse))})

ALL = {**synth.GENERATORS, **BUFFERED}

DESCRIPTIONS = {
    "music": "built-in groove with drums, bass and arp", "pink": "pink noise (best EQ test)",
    "white": "white noise", "brown": "brown noise", "sweep": "20 Hz to 20 kHz log sweep",
    "binaural": "binaural beat (headphones; --beat HZ|alpha|theta..., --carrier HZ)",
    "zoo": "every animal in turn", "cartoon": "slide whistle, boing, bonk, sad trombone and friends",
    "dialup": "56k modem handshake (impressionistic)", "dtmf": "touch tones", "siren": "wail and yelp",
    "morse": "DANEQ in morse code", "loudspeaker": "speech-like babble through a bullhorn",
    "tetris": "Korobeiniki (public domain folk tune) in chiptune", "ode": "Ode to Joy, chiptune",
    "elise": "Fur Elise, chiptune", "birthday": "Happy Birthday, chiptune",
}
for _a in ANIMALS:
    DESCRIPTIONS[_a] = f"synthesized {_a}"
