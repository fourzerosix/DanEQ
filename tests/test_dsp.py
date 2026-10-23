import numpy as np
import pytest

from daneq.braille import bar_rows
from daneq.dsp import LAYOUTS, PRESETS, Equalizer, Spectrum, preset_gains, to_apo

RATE = 48000


def tone(f, seconds=2.0, amp=0.1):
    t = np.arange(int(RATE * seconds)) / RATE
    return (amp * np.sin(2 * np.pi * f * t)).astype(np.float32)[:, None]


def gain_db(eq, f):
    x = tone(f)
    y = eq.process(x)[RATE:]
    return 20 * np.log10(y.std() / x[RATE:].std())


@pytest.mark.parametrize("nb", sorted(LAYOUTS))
def test_flat_is_transparent(nb):
    eq = Equalizer(nb, RATE, 1)
    x = (np.random.default_rng(0).standard_normal((RATE, 1)) * 0.1).astype(np.float32)
    assert np.abs(eq.process(x) - x).max() < 1e-6


@pytest.mark.parametrize("nb", sorted(LAYOUTS))
@pytest.mark.parametrize("gain", [9.0, -9.0])
def test_audio_matches_displayed_curve(nb, gain):
    for i, f in enumerate(LAYOUTS[nb]["freqs"]):
        eq = Equalizer(nb, RATE, 1)
        eq.set_gain(i, gain)
        assert abs(gain_db(eq, f) - float(eq.response_db([f])[0])) < 0.1


def test_peak_band_hits_requested_gain():
    eq = Equalizer(10, RATE, 1)
    eq.set_gain(5, 6.0)
    assert abs(gain_db(eq, 1000) - 6.0) < 0.1
    assert abs(gain_db(eq, 100)) < 0.5  # far away bands untouched


def test_preamp_and_bypass():
    eq = Equalizer(4, RATE, 1)
    eq.set_preamp(-6.0)
    assert abs(gain_db(eq, 1000) + 6.0) < 0.05
    eq.set_bypass(True)
    x = tone(1000)
    assert np.array_equal(eq.process(x), x)


def test_gain_is_clamped():
    eq = Equalizer(4, RATE, 2)
    eq.set_gain(0, 99)
    assert eq.gains[0] == 12.0


def test_presets_cover_all_layouts():
    for nb in LAYOUTS:
        for name in PRESETS:
            assert len(preset_gains(name, LAYOUTS[nb]["freqs"])) == nb


def test_spectrum_peak_lands_on_the_tone():
    sp = Spectrum(RATE)
    bars = sp.bars(tone(1000, 0.5)[:, 0], 200, 30, 18000, tilt=0.0)
    centers = np.geomspace(30, 18000, 201)
    centers = np.sqrt(centers[:-1] * centers[1:])
    assert abs(np.log2(centers[int(np.argmax(bars))] / 1000)) < 0.1


def test_bar_rows_shape():
    rows = bar_rows(np.array([0, 4, 8, 16] * 5), np.full(20, -1), 4)
    assert len(rows) == 4 and all(len(r) == 10 for r in rows)


def test_auto_headroom_keeps_peak_at_or_below_zero():
    eq = Equalizer(10, RATE, 2)
    eq.set_gains([6, 6, 6, 0, 0, 0, 0, 0, 0, 0])
    pre = eq.auto_headroom()
    assert pre < -5.0
    assert float(eq.response_db(np.geomspace(20, 20000, 256)).max()) <= 0.05


def test_apo_export_lists_every_band():
    eq = Equalizer(6, RATE, 2)
    eq.set_gain(2, 3.5)
    text = to_apo(eq)
    assert text.startswith("Preamp:") and text.count("Filter ") == 6
    assert "PK Fc 600 Hz Gain 3.5 dB" in text and "LSC" in text and "HSC" in text


def test_shade_ramp():
    from daneq.braille import SHADE
    assert SHADE[0] == chr(0x2800) and SHADE[8] == chr(0x28FF)
