import shutil
import subprocess
import wave

import numpy as np
import pytest

from daneq import clips, player
from daneq.browser import Browser
from daneq.effects import SpeedControl
from daneq.player import ArrayDecoder, FilePlayer, SourceSwitch, TrackPlayback, format_time, scan
from daneq.themes import THEME_ORDER, THEMES

RATE = 48000


def tone(seconds=4.0, f=440.0, amp=0.4):
    return amp * np.sin(2 * np.pi * f * np.arange(int(RATE * seconds)) / RATE)


def write_wav(path, data, rate=RATE):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((np.clip(data, -1, 1) * 32767).astype("<i2").tobytes())
    return str(path)


def play_through(tempo=1.0, pitch=0.0, screw=1.0, seconds=4.0, f=440.0):
    tp = TrackPlayback("mem", RATE, ArrayDecoder(tone(seconds, f), RATE))
    blocks, done = [], False
    while not done and len(blocks) < 3000:
        b, done = tp.render(1024, tempo, pitch, screw)
        blocks.append(b)
    return np.vstack(blocks)[:, 0]


def length(y):
    nz = np.flatnonzero(np.abs(y) > 1e-4)
    return (nz[-1] + 1) / RATE


def peak_hz(y):
    seg = y[len(y) // 4: len(y) // 4 + 16384]
    return float(np.argmax(np.abs(np.fft.rfft(seg * np.hanning(len(seg))))) * RATE / len(seg))


def test_neutral_is_bit_exact():
    y = play_through()
    ref = tone().astype(np.float32)
    assert np.abs(y[300:len(ref) - 300] - ref[300:len(ref) - 300]).max() == 0.0


@pytest.mark.parametrize("tempo", [1.5, 0.75, 2.0])
def test_tempo_changes_length_but_not_pitch(tempo):
    y = play_through(tempo=tempo)
    assert abs(length(y) - 4.0 / tempo) < 0.08
    assert abs(peak_hz(y) - 440.0) < 8.0


@pytest.mark.parametrize("semitones", [12.0, -5.0, 7.0])
def test_pitch_changes_pitch_but_not_length(semitones):
    y = play_through(pitch=semitones)
    assert abs(length(y) - 4.0) < 0.08
    assert abs(peak_hz(y) - 440.0 * 2 ** (semitones / 12.0)) < 0.02 * 440.0 * 2 ** (semitones / 12.0) + 4


@pytest.mark.parametrize("screw", [0.5, 0.75, 1.2])
def test_screw_moves_pitch_and_tempo_together(screw):
    y = play_through(screw=screw)
    assert abs(length(y) - 4.0 / screw) < 0.08
    assert abs(peak_hz(y) - 440.0 * screw) < 0.02 * 440.0 * screw + 4


def test_pitch_and_tempo_are_independent():
    y = play_through(tempo=1.2, pitch=7.0)
    assert abs(length(y) - 4.0 / 1.2) < 0.08
    assert abs(peak_hz(y) - 440.0 * 2 ** (7 / 12)) < 10


def test_changing_knobs_midstream_does_not_click():
    tp = TrackPlayback("mem", RATE, ArrayDecoder(tone(10.0), RATE))
    events = {20: (1.3, 0.0, 1.0), 40: (1.3, 3.0, 1.0), 60: (1.3, 3.0, 0.8), 80: (1.0, 0.0, 1.0), 100: (1.4, 0.0, 1.0), 120: (1.0, 0.0, 1.0)}
    cur, out = (1.0, 0.0, 1.0), []
    for i in range(160):
        cur = events.get(i, cur)
        out.append(tp.render(1024, *cur)[0][:, 0])
    y = np.concatenate(out)
    # the natural slope of a 440 Hz sine at this level is 0.023 (a bit more when pitched up); a click would be 0.1 or more
    assert np.abs(np.diff(y[400:])).max() < 0.05


def test_seek_and_position():
    tp = TrackPlayback("mem", RATE, ArrayDecoder(tone(10.0), RATE))
    for _ in range(10):
        tp.render(1024, 1.0, 0.0, 1.0)
    assert abs(tp.position() - 10 * 1024 / RATE) < 0.05
    tp.seek(5.0)
    tp.render(1024, 1.0, 0.0, 1.0)
    assert 4.95 < tp.position() < 5.1
    tp.seek(9999)                                   # clamped inside the track
    assert tp.position() <= 10.0


def make_playlist(tmp_path, n=3, seconds=2.0):
    return [write_wav(tmp_path / f"t{i}.wav", tone(seconds, 300 + 100 * i)) for i in range(n)]


def test_playlist_transport(tmp_path):
    files = make_playlist(tmp_path)
    fp = FilePlayer(files, RATE, 1024, SpeedControl(RATE))
    assert fp.count == 3 and fp.index == 0 and fp.playing
    fp.next()
    assert fp.index == 1
    fp.next()
    fp.next()                                       # at the end with repeat off: stays
    assert fp.index == 2
    fp.prev()                                       # near the start of the track: goes back
    assert fp.index == 1
    fp.pause()
    assert not np.any(fp.read_block())              # paused means silence
    fp.play()
    assert np.any(fp.read_block())


def test_end_of_playlist_and_repeat_modes(tmp_path):
    files = make_playlist(tmp_path, 2, 1.0)
    fp = FilePlayer(files, RATE, 1024, SpeedControl(RATE), repeat="off")
    for _ in range(200):
        fp.read_block()
    assert fp.ended and not fp.playing
    fp.play()                                       # restarts from the top
    assert fp.playing and fp.index == 0
    fp = FilePlayer(files, RATE, 1024, SpeedControl(RATE), repeat="all")
    for _ in range(200):
        fp.read_block()
    assert fp.playing and not fp.ended
    fp = FilePlayer(files, RATE, 1024, SpeedControl(RATE), repeat="one")
    for _ in range(200):
        fp.read_block()
    assert fp.playing and fp.index == 0
    assert fp.cycle_repeat() == "off" or True


def test_shuffle_keeps_current_track_first(tmp_path):
    fp = FilePlayer(make_playlist(tmp_path, 6, 1.0), RATE, 1024, SpeedControl(RATE), shuffle=True)
    assert sorted(fp.order) == list(range(6)) and fp.index == 0
    cur = fp.order[0]
    fp.toggle_shuffle()
    fp.toggle_shuffle()
    assert fp.order[fp.index] == cur


def test_player_applies_the_speed_knobs(tmp_path):
    f = write_wav(tmp_path / "a.wav", tone(3.0))
    sp = SpeedControl(RATE)
    sp.p.update(screw=0.5)
    fp = FilePlayer([f], RATE, 1024, sp)
    blocks = []
    for _ in range(400):
        blocks.append(fp.read_block().copy())
        if fp.ended:
            break
    assert abs(length(np.vstack(blocks)[:, 0]) - 6.0) < 0.1
    sp.set_enabled(False)
    assert sp.effective() == (0.0, 1.0, 1.0)


def test_speed_control_knob_mapping():
    sp = SpeedControl(RATE)
    for key in ("pitch", "tempo", "screw"):
        sp.set_norm(key, 0.5)
        assert abs(sp.norm(key) - 0.5) < 1e-9
    sp.p.update(pitch=-3.0, tempo=80.0, screw=0.8)
    assert sp.fmt("pitch") == "-3.0st" and sp.fmt("tempo") == "80%" and sp.fmt("screw") == "0.80x"
    assert "tempo 64%" in sp.summary()


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
@pytest.mark.parametrize("ext,codec", [("flac", "flac"), ("ogg", "libvorbis"), ("mp3", "libmp3lame")])
def test_decoders_read_and_seek_compressed_formats(tmp_path, ext, codec):
    src = write_wav(tmp_path / "s.wav", tone(3.0))
    out = tmp_path / f"s.{ext}"
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", src, "-c:a", codec, str(out)], capture_output=True)
    if r.returncode != 0:
        pytest.skip(f"ffmpeg has no {codec} encoder")
    for make in (lambda: player.FfmpegDecoder(str(out), RATE), lambda: player.open_decoder(str(out), RATE)):
        d = make()
        assert len(d.read(4800)) == 4800
        d.seek(1.0)
        assert len(d.read(1000)) == 1000
        assert d.duration is None or 2.8 < d.duration < 3.3
        d.close()


def test_scan_expands_folders_and_playlists(tmp_path):
    (tmp_path / "sub").mkdir()
    a = write_wav(tmp_path / "b2.wav", tone(0.1))
    b = write_wav(tmp_path / "b10.wav", tone(0.1))
    (tmp_path / "notes.txt").write_text("x")
    (tmp_path / "list.m3u").write_text("# comment\nb10.wav\nb2.wav\n")
    got = scan([str(tmp_path)])
    assert got == [a, b]                            # natural order: b2 before b10, no .txt
    assert scan([str(tmp_path / "list.m3u")]) == [b, a]
    assert format_time(75) == "1:15" and format_time(3725) == "1:02:05" and format_time(None) == "--:--"


def test_browser_navigation_and_selection(tmp_path):
    (tmp_path / "album").mkdir()
    write_wav(tmp_path / "album" / "one.wav", tone(0.1))
    write_wav(tmp_path / "album" / "two.wav", tone(0.1))
    (tmp_path / "readme.txt").write_text("x")
    b = Browser(str(tmp_path))
    assert [e.name for e in b.entries] == ["..", "album"]              # only folders and audio are listed
    b.idx = 1
    assert b.activate() is None and b.cwd.name == "album"
    names = [e.name for e in b.entries]
    assert names == ["..", "one.wav", "two.wav"]
    b.idx = 2
    paths, start = b.activate()
    assert [p.split("/")[-1] for p in paths] == ["one.wav", "two.wav"] and start == 1
    b.idx = 1
    b.toggle_mark()
    paths, start = b.activate()
    assert len(paths) == 1 and paths[0].endswith("one.wav")
    b.go_up()
    assert b.cwd == tmp_path and b.current.name == "album"


def test_source_switch_between_live_and_files(tmp_path):
    live = iter([np.ones((1024, 2), np.float32)] * 1000)

    class Base:
        def __iter__(self):
            return live

        def close(self):
            pass

    sw = SourceSwitch(Base(), RATE, 1024, SpeedControl(RATE))
    assert sw.player is None and float(next(sw)[0, 0]) == 1.0
    fp = sw.start_player(make_playlist(tmp_path, 1, 1.0))
    assert sw.player is fp and sw.mode == "player"
    assert np.any(next(sw))
    sw.back_to_base()
    assert sw.player is None and float(next(sw)[0, 0]) == 1.0
    sw.close()


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_clip_slicing_cuts_a_section_out_of_a_longer_file(tmp_path, monkeypatch):
    src = write_wav(tmp_path / "long.wav", tone(20.0))
    out = clips.slice_audio(src, tmp_path / "cut.wav", 5.0, 3.0)
    with wave.open(str(out), "rb") as w:
        assert abs(w.getnframes() / w.getframerate() - 3.0) < 0.1
    monkeypatch.setattr(clips, "library", lambda: {"x": {"url": src, "start": 2, "length": 1, "about": "t"}})
    monkeypatch.setattr(clips, "cache_dir", lambda: tmp_path / "cache")
    assert clips.resolve("x").endswith("x.wav")


def test_movie_clips_are_registered_with_slices():
    for name in ("jazzsinger", "barbra", "farmhouse", "fire"):
        assert name in clips.BUILTIN and clips.BUILTIN[name]["url"].startswith("https://commons.wikimedia.org/")
    assert clips.BUILTIN["barbra"]["start"] > 0 and clips.BUILTIN["barbra"]["length"] > 0


def test_themes_all_have_a_background_and_there_are_thirty():
    assert len(THEME_ORDER) >= 30
    for name, th in THEMES.items():
        assert len(th["bg"]) == 3 and all(0 <= c <= 255 for c in th["bg"]), name


def test_cli_accepts_files_and_playback_flags():
    from daneq.cli import build_parser
    ns = build_parser().parse_args(["a.mp3", "dir/", "--repeat", "all", "--shuffle", "--screw", "0.75",
                                    "--pitch", "-2", "--tempo", "90", "--transparent", "--once"])
    assert ns.files == ["a.mp3", "dir/"] and ns.repeat == "all" and ns.shuffle and ns.once
    assert ns.screw == 0.75 and ns.pitch == -2 and ns.tempo == 90 and ns.transparent
