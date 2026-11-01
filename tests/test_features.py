import numpy as np
import pytest

from daneq import clips, nerd, sounds, visuals
from daneq.cli import build_parser, parse_beat
from daneq.effects import ORDER, Compressor, Crusher, Echo, FxRack, Reverb, Tremolo, Widener
from daneq.themes import THEMES, gradient, rgb_to_256

RATE = 48000


def run(fx, x, bs=1024):
    fx.set_enabled(True)
    return np.vstack([fx.process(x[i:i + bs]) for i in range(0, len(x), bs)])


@pytest.mark.parametrize("cls", ORDER)
def test_every_effect_is_finite_and_keeps_shape(cls):
    x = np.random.default_rng(0).standard_normal((RATE // 2 + 37, 2)) * 0.1
    y = run(cls(RATE), x)
    assert y.shape == x.shape and np.isfinite(y).all()


def test_echo_repeats_at_the_requested_time():
    x = np.zeros((RATE * 2, 2))
    x[100] = 1.0
    fx = Echo(RATE)
    fx.p["mix"] = 1.0
    y = run(fx, x)
    peak = int(np.argmax(np.abs(y[2000:, 0]))) + 2000
    assert abs((peak - 100) / RATE * 1000 - 350) < 1.0


def test_reverb_has_a_decaying_tail():
    x = np.zeros((RATE * 3, 2))
    x[:RATE] = np.random.default_rng(0).standard_normal((RATE, 2)) * 0.1
    fx = Reverb(RATE)
    fx.p["mix"] = 1.0
    y = run(fx, x)
    early, late = y[int(1.1 * RATE):int(1.3 * RATE)].std(), y[int(2.5 * RATE):int(2.7 * RATE)].std()
    assert early > 0.002 and late < early


def test_compressor_reduces_by_the_expected_amount():
    t = np.arange(RATE * 2) / RATE
    s = 0.5 * np.sin(2 * np.pi * 440 * t)
    fx = Compressor(RATE)
    fx.p["makeup"] = 0.0
    y = run(fx, np.stack((s, s), 1))
    change = 20 * np.log10(y[RATE:].std() / s[RATE:].std())
    assert abs(change - (-9.0)) < 1.0


def test_widener_zero_is_mono_and_tremolo_hits_zero():
    fx = Widener(RATE)
    fx.p["width"] = 0.0
    y = run(fx, np.random.default_rng(1).standard_normal((2048, 2)))
    assert np.abs(y[:, 0] - y[:, 1]).max() < 1e-12
    fx = Tremolo(RATE)
    fx.p["depth"] = 1.0
    assert run(fx, np.ones((RATE, 2))).min() < 0.01


def test_crusher_limits_levels():
    fx = Crusher(RATE)
    fx.p.update(bits=4, down=1)
    t = np.arange(4096) / RATE
    s = 0.5 * np.sin(2 * np.pi * 440 * t)
    assert len(np.unique(run(fx, np.stack((s, s), 1))[:, 0])) <= 16


def test_knob_mapping_roundtrip_and_rack_state():
    fx = Echo(RATE)
    for key, *_ in fx.PARAMS:
        fx.set_norm(key, 0.5)
        assert abs(fx.norm(key) - 0.5) < 1e-9
    rack = FxRack(RATE)
    rack.fx[8].set_enabled(True)
    rack.fx[8].p["time"] = 500.0
    other = FxRack(RATE)
    other.load(rack.state())
    assert other.fx[8].enabled and other.fx[8].p["time"] == 500.0


@pytest.mark.parametrize("name", sorted(sounds.ALL))
def test_every_demo_signal_streams_stereo_blocks(name):
    gen = sounds.ALL[name](RATE, 1024, beat=10.0, carrier=220.0)
    x = np.vstack([next(gen) for _ in range(3)])
    assert x.shape == (3072, 2) and x.dtype == np.float32 and np.isfinite(x).all()


def test_binaural_beat_is_the_frequency_difference():
    gen = sounds.ALL["binaural"](RATE, 1024, beat=8.0, carrier=200.0)
    x = np.vstack([next(gen) for _ in range(200)])[RATE:]
    freqs = np.fft.rfftfreq(len(x), 1 / RATE)
    left = freqs[np.argmax(np.abs(np.fft.rfft(x[:, 0])))]
    right = freqs[np.argmax(np.abs(np.fft.rfft(x[:, 1])))]
    assert abs((right - left) - 8.0) < 0.5
    assert parse_beat("alpha") == 10.0 and parse_beat("7.5") == 7.5


def test_cli_exposes_animal_shortcuts():
    ns = build_parser().parse_args(["--bear"])
    assert ns.demo == "bear"
    assert build_parser().parse_args(["--lion", "--no-output"]).demo == "lion"


class FakeColors:
    grad = list(range(1, 25))
    accent = curve = dim = text = warn = border = title = 1

    def at(self, f):
        return 1 + int(min(max(f, 0), 1) * 23)


@pytest.mark.parametrize("size", [(60, 8), (100, 15), (150, 30)])
def test_all_visuals_and_styles_draw_without_error(size):
    w, h = size
    rng = np.random.default_rng(0)
    lvl = np.clip(rng.random(w * 2), 0, 1)
    mono, st = rng.standard_normal(8192) * 0.2, rng.standard_normal((4096, 2)) * 0.2
    calls = []
    put = lambda y, x, s, a=0: calls.append((y, x, s))  # noqa: E731
    for v in visuals.make_all():
        for f in range(20):
            v.draw(visuals.Ctx(put, FakeColors(), 1, 1, w, h, lvl, f * 0.03, 0.03, RATE, mono, st))
    for s in visuals.STYLES:
        visuals.draw_bars(visuals.Ctx(put, FakeColors(), 1, 1, w, h, lvl, 0, 0.03, RATE, mono, st), s, lvl, lvl)
    assert calls


def test_nerd_parsers():
    streams = nerd.parse_streams(
        'Sink Input #7\n\tSink: 1\n\tVolume: front-left: 1 / 80% / -5 dB\n\tMute: yes\n\tCorked: no\n'
        '\tBuffer Latency: 25000 usec\n\tProperties:\n\t\tapplication.name = "mpv"\n'
        '\t\tapplication.process.id = "99"\n', "Sink Input #")
    assert streams[0]["app"] == "mpv" and streams[0]["vol"] == 80 and streams[0]["mute"]
    assert streams[0]["pid"] == 99 and streams[0]["lat"] == 25.0
    devs = nerd.parse_devices("Sink #1\n\tState: RUNNING\n\tName: alsa_output.x\n\tDescription: Speakers\n"
                              "\tVolume: front-left: 1 / 50% / -18 dB\n\tMute: no\n", "Sink #")
    assert devs[0]["state"] == "RUNNING" and devs[0]["desc"] == "Speakers" and devs[0]["vol"] == 50
    assert nerd.parse_info("Server Name: PulseAudio (on PipeWire 1.0)\nDefault Sink: x\n")["Default Sink"] == "x"
    assert len(nerd.spark([0, 50, 100, 20], 4)) == 4


def test_nerd_collector_sees_this_process():
    col = nerd.Collector()
    col.collect()
    assert any("daneq" in p["tags"] for p in col.data["procs"])
    assert nerd.sort_procs([{"cpu": 1, "pid": 2, "rss": 1, "name": "b"}, {"cpu": 5, "pid": 1, "rss": 1, "name": "a"}], "cpu")[0]["pid"] == 1


def test_themes_are_valid_gradients():
    assert len(THEMES) >= 20
    for t in THEMES.values():
        g = gradient(t["a"])
        assert len(g) == 24 and all(16 <= i <= 255 for i in g)
    assert rgb_to_256(255, 0, 0) == 196


def test_clip_resolve_local_and_unknown(tmp_path):
    f = tmp_path / "a.wav"
    f.write_bytes(b"x")
    assert clips.resolve(str(f)) == str(f)
    with pytest.raises(clips.ClipError):
        clips.resolve("definitely-not-a-clip")


def test_builtin_clips_are_https_urls_with_notes():
    assert set(clips.BUILTIN) >= {"moon", "infamy", "jfk"}
    for v in clips.BUILTIN.values():
        assert v["url"].startswith("https://") and v["about"]


def test_new_public_domain_melodies_stream():
    for name in ("grace", "twinkle", "row", "jingle", "silentnight", "yankee", "susanna", "canon"):
        gen = sounds.ALL[name](RATE, 1024)
        x = np.vstack([next(gen) for _ in range(30)])
        assert x.shape == (30720, 2) and np.isfinite(x).all() and np.abs(x).max() > 0.05, name


def test_amazing_grace_matches_the_hymnwiki_score():
    """35 notes in 3/4 with two quarter-note pick-ups: 14 full bars plus 2 beats."""
    bpm, notes = sounds.MELODIES["grace"]
    toks = [t for t in notes.split() if not t.startswith("R:")]
    total = sum(float(t.split(":")[1]) for t in toks)
    assert bpm == 90 and len(toks) == 35 and total == 44.0 and (total - 2) % 3 == 0
    assert toks[0] == "D4:1" and toks[-1] == "G4:3"


def test_portaudio_device_selection_with_a_fake_backend(monkeypatch):
    from daneq import audio

    class FakeSd:
        default = type("D", (), {"device": (0, 3)})()

        @staticmethod
        def query_devices():
            mk = lambda n, i, o, r=48000: {"name": n, "max_input_channels": i, "max_output_channels": o, "default_samplerate": r}  # noqa: E731
            return [mk("MacBook Pro Microphone", 1, 0), mk("BlackHole 2ch", 2, 2), mk("External Headphones", 0, 2), mk("BlackHole 16ch", 16, 16)]

    monkeypatch.setattr(audio, "_sd", lambda: FakeSd)
    assert audio.pick_loopback()[1] == "BlackHole 2ch"
    assert audio.pick_output()[1] != "BlackHole 16ch"          # default output is virtual, so it must be skipped
    assert audio.pick_output()[1] == "External Headphones"
    assert audio.find_device("headphones", "output")[0] == 2
    assert audio.find_device("1", "input")[1] == "BlackHole 2ch"
    with pytest.raises(audio.AudioError):
        audio.find_device("nothing-like-this", "input")


def test_sdsink_reshapes_bytes_to_stereo(monkeypatch):
    from daneq import audio
    written = []

    class Stream:
        def __init__(self, **kw):
            pass

        def start(self):
            pass

        def write(self, arr):
            written.append(arr)

    fake = type("Sd", (), {"OutputStream": Stream})
    monkeypatch.setattr(audio, "_sd", lambda: fake)
    sink = audio.SdSink(0, 48000, 1024)
    sink.write(np.zeros((16, 2), dtype="<f4").tobytes())
    assert written[0].shape == (16, 2)


def test_setup_cfg_carries_the_metadata():
    import configparser
    cp = configparser.ConfigParser()
    cp.read("setup.cfg")
    assert cp["metadata"]["name"] == "daneq" and "daneq = daneq.cli:main" in cp["options.entry_points"]["console_scripts"]
    assert "sounddevice" in cp["options"]["install_requires"]


def test_nerd_collector_works_without_proc(monkeypatch):
    """macOS has no /proc: collection must fall back to ps instead of raising."""
    real_isdir, real_listdir = nerd.os.path.isdir, nerd.os.listdir
    monkeypatch.setattr(nerd.os.path, "isdir", lambda p: False if str(p) == "/proc" else real_isdir(p))

    def listdir(p="."):
        if str(p).startswith("/proc"):
            raise FileNotFoundError(p)
        return real_listdir(p)

    monkeypatch.setattr(nerd.os, "listdir", listdir)
    col = nerd.Collector()
    col.collect()
    assert any("daneq" in p["tags"] for p in col.data["procs"])
    assert nerd.snd_users() == {}


def test_license_metadata_is_gpl():
    import configparser
    cp = configparser.ConfigParser()
    cp.read("setup.cfg")
    assert cp["metadata"]["license"].startswith("GPL-3.0")
    assert "GNU General Public License v3" in cp["metadata"]["classifiers"]
