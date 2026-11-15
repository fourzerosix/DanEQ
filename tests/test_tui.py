"""Drives the real curses interface in a pseudo-terminal and reads the screen with pyte."""
import os
import signal
import sys
import time
import wave

import numpy as np
import pytest

pyte = pytest.importorskip("pyte")
pty = pytest.importorskip("pty")
fcntl = pytest.importorskip("fcntl")
termios = pytest.importorskip("termios")
select = pytest.importorskip("select")
struct = pytest.importorskip("struct")

KEYS = {"RIGHT": b"\x1bOC", "LEFT": b"\x1bOD", "UP": b"\x1bOA", "DOWN": b"\x1bOB", "BTAB": b"\x1b[Z", "ESC": b"\x1b", "ENTER": b"\n"}


class Tui:
    def __init__(self, args, tmp_path, cols=120, rows=36):
        self.screen = pyte.Screen(cols, rows)
        self.stream = pyte.ByteStream(self.screen)
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            os.environ.update(TERM="xterm-256color", LANG="C.UTF-8", LC_ALL="C.UTF-8",
                              XDG_CONFIG_HOME=str(tmp_path / "cfg"), HOME=str(tmp_path / "home"))
            os.makedirs(str(tmp_path / "home"), exist_ok=True)
            os.execvp(sys.executable, [sys.executable, "-m", "daneq"] + args)
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    def pump(self, seconds):
        end = time.time() + seconds
        while time.time() < end:
            r, _, _ = select.select([self.fd], [], [], 0.05)
            if r:
                try:
                    self.stream.feed(os.read(self.fd, 65536))
                except OSError:
                    return

    def text(self):
        return "\n".join(self.screen.display)

    def wait_for(self, needle, timeout=10.0):
        end = time.time() + timeout
        while time.time() < end:
            self.pump(0.2)
            if needle in self.text():
                return True
        return False

    def send(self, *keys):
        for k in keys:
            os.write(self.fd, KEYS.get(k, k.encode() if isinstance(k, str) else k))
            self.pump(0.25)

    def close(self):
        try:
            os.kill(self.pid, signal.SIGKILL)
            os.waitpid(self.pid, 0)
        except OSError:
            pass


@pytest.fixture
def tui(tmp_path):
    made = []

    def start(args):
        t = Tui(args, tmp_path)
        made.append(t)
        return t

    yield start
    for t in made:
        t.close()


def make_wav(path, seconds=8.0):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes((0.3 * np.sin(2 * np.pi * 440 * np.arange(int(48000 * seconds)) / 48000) * 32767).astype("<i2").tobytes())
    return str(path)


def test_main_screen_menu_and_speed_tab(tui):
    t = tui(["--demo", "pink", "--no-output"])
    assert t.wait_for("DanEQ v"), t.text()
    assert "Equalizer 10-band" in t.text() and "Spectrum" in t.text()
    t.send("f", "BTAB")                                     # FX rack, then the last tab: Speed
    assert "SCREW" in t.text() and "Pitch" in t.text() and "Tempo" in t.text()
    t.send("f", "ESC")
    assert "Theme background" in t.text() and "Open file" in t.text()


def test_transport_bar_and_keys_for_file_playback(tui, tmp_path):
    a, b = make_wav(tmp_path / "a-one.wav"), make_wav(tmp_path / "b-two.wav")
    t = tui([a, b, "--no-output"])
    assert t.wait_for("[||]") and "1/2" in t.text() and "a-one" in t.text(), t.text()
    t.send(" ")
    assert "[ > ]" in t.text()                              # paused
    t.send(" ", "x")
    assert "2/2" in t.text() and "b-two" in t.text()
    t.send(">")
    assert "0:0" in t.text()
    t.send("S", "R")
    assert "[S]" in t.text() and "[R:all]" in t.text()


def test_file_browser_plays_the_selected_file(tui, tmp_path):
    folder = tmp_path / "music"
    folder.mkdir()
    make_wav(folder / "first.wav")
    make_wav(folder / "second.wav")
    t = tui([str(folder / "first.wav"), "--no-output"])
    assert t.wait_for("first")
    t.send("O")
    assert "Open file" in t.text() and "second.wav" in t.text()
    t.send("DOWN", "DOWN", "ENTER")                         # .., first.wav, second.wav
    assert t.wait_for("playing 2 track"), t.text()
    assert "second" in t.text()


def test_theme_background_toggle_with_key(tui, tmp_path):
    t = tui(["--demo", "pink", "--no-output"])
    assert t.wait_for("DanEQ v")
    assert t.screen.buffer[5][60].bg != "default"
    t.send("B")
    assert t.screen.buffer[5][60].bg == "default"
    assert "theme background" in t.text()


def test_open_a_file_while_a_test_signal_plays_then_go_back(tui, tmp_path):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    make_wav(home / "song.wav")
    t = tui(["--demo", "pink", "--no-output"])
    assert t.wait_for("DanEQ v")
    assert "[||]" not in t.text()                           # no transport bar for a generator
    t.send("O", "DOWN", "ENTER")                            # .., song.wav
    assert t.wait_for("playing 1 track") and "[||]" in t.text(), t.text()
    t.send("ESC")
    assert "Back to live input" in t.text()
    t.send("DOWN", "DOWN", "DOWN")                          # Resume, Open file, Play/Pause, ...
