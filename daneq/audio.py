"""Audio plumbing built on pactl/parec/pacat (works on PulseAudio and PipeWire-Pulse)."""
from __future__ import annotations

import shutil
import subprocess
import time
import wave
from typing import List, Optional, Tuple

import numpy as np

VSINK = "daneq"


class AudioError(RuntimeError):
    pass


# ---- pactl helpers ---------------------------------------------------------
def have_pulse_tools() -> bool:
    return all(shutil.which(t) for t in ("pactl", "parec", "pacat"))


def pactl(*args: str) -> str:
    try:
        r = subprocess.run(["pactl", *args], capture_output=True, text=True, timeout=10)
    except FileNotFoundError:
        raise AudioError("pactl not found (install pulseaudio-utils / pipewire-pulse)")
    except subprocess.TimeoutExpired:
        raise AudioError("pactl timed out (is the sound server running?)")
    if r.returncode != 0:
        raise AudioError(r.stderr.strip() or f"pactl {' '.join(args)} failed")
    return r.stdout


def default_sink() -> Optional[str]:
    for line in pactl("info").splitlines():
        if line.startswith("Default Sink:"):
            return line.split(":", 1)[1].strip() or None
    return None


def list_sinks() -> List[Tuple[int, str]]:
    out = []
    for line in pactl("list", "short", "sinks").splitlines():
        p = line.split("\t")
        if len(p) >= 2:
            out.append((int(p[0]), p[1]))
    return out


def sink_inputs() -> List[Tuple[int, int]]:
    out = []
    for line in pactl("list", "short", "sink-inputs").splitlines():
        p = line.split("\t")
        if len(p) >= 2 and p[0].isdigit() and p[1].isdigit():
            out.append((int(p[0]), int(p[1])))
    return out


def cleanup_stale() -> None:
    """Unload any leftover DanEQ null sinks (e.g. after a crash)."""
    try:
        for line in pactl("list", "short", "modules").splitlines():
            p = line.split("\t")
            if len(p) >= 3 and p[1] == "module-null-sink" and f"sink_name={VSINK}" in p[2]:
                pactl("unload-module", p[0])
    except AudioError:
        pass


def restore() -> str:
    """Undo a crashed session: drop the virtual sink and fix the default sink."""
    cleanup_stale()
    cur = default_sink()
    if cur is None or cur.startswith(VSINK):
        for _, name in list_sinks():
            if not name.startswith(VSINK):
                pactl("set-default-sink", name)
                return name
        return ""
    return cur


class VirtualSink:
    """Creates the 'daneq' null sink and makes it the default output.

    Apps play into it, DanEQ records its monitor, equalizes, and plays the
    result to the real output. Everything is undone on close().
    """

    def __init__(self, rate: int, target: Optional[str] = None):
        self.rate = rate
        self.target = target
        self.orig: Optional[str] = None
        self.module: Optional[int] = None

    @property
    def monitor(self) -> str:
        return f"{VSINK}.monitor"

    def open(self) -> str:
        cleanup_stale()
        self.orig = default_sink()
        if self.target is None:
            self.target = self.orig
        if not self.target:
            raise AudioError("no output sink found (is a sound server running?)")
        out = pactl("load-module", "module-null-sink", f"sink_name={VSINK}",
                    f"rate={self.rate}", "channels=2",
                    "sink_properties=device.description=DanEQ")
        try:
            self.module = int(out.strip())
        except ValueError:
            raise AudioError(f"unexpected module id: {out!r}")
        idx = dict((n, i) for i, n in list_sinks()).get(VSINK)
        for inp, sink in sink_inputs():
            if sink != idx:
                try:
                    pactl("move-sink-input", str(inp), VSINK)
                except AudioError:
                    pass
        pactl("set-default-sink", VSINK)
        return self.target

    def close(self) -> None:
        if self.module is None:
            return
        try:
            if self.orig and not self.orig.startswith(VSINK):
                pactl("set-default-sink", self.orig)
            idx = dict((n, i) for i, n in list_sinks()).get(VSINK)
            if idx is not None and self.orig:
                for inp, sink in sink_inputs():
                    if sink == idx:
                        try:
                            pactl("move-sink-input", str(inp), self.orig)
                        except AudioError:
                            pass
            pactl("unload-module", str(self.module))
        except AudioError:
            pass
        self.module = None


# ---- sources ---------------------------------------------------------------
class GenSource:
    """Wraps a generator of float32 (n, 2) blocks."""

    def __init__(self, gen):
        self._gen = gen

    def __iter__(self):
        return self._gen

    def close(self) -> None:
        pass


class ParecSource:
    """Live capture through parec (raw float32 stereo on stdout)."""

    def __init__(self, device: str, rate: int, block: int, latency_ms: int = 20):
        self.block = block
        self.proc = subprocess.Popen(
            ["parec", f"--device={device}", f"--rate={rate}", "--channels=2",
             "--format=float32le", f"--latency-msec={latency_ms}",
             "--client-name=DanEQ", "--stream-name=capture"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    def __iter__(self):
        n = self.block * 8
        while True:
            buf = self.proc.stdout.read(n)
            if len(buf) < n:
                raise AudioError("capture stream ended (sound server went away?)")
            yield np.frombuffer(buf, dtype="<f4").reshape(-1, 2).copy()

    def close(self) -> None:
        _kill(self.proc)


class FfmpegSource:
    def __init__(self, path: str, rate: int, block: int, loop: bool = False):
        self.path, self.rate, self.block, self.loop = path, rate, block, loop
        self.proc = None

    def __iter__(self):
        n = self.block * 8
        while True:
            self.proc = subprocess.Popen(
                ["ffmpeg", "-v", "quiet", "-i", self.path, "-vn", "-f", "f32le",
                 "-ac", "2", "-ar", str(self.rate), "-"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            got = 0
            while True:
                buf = self.proc.stdout.read(n)
                if not buf:
                    break
                buf = buf[: len(buf) // 8 * 8]
                got += len(buf)
                if buf:
                    yield np.frombuffer(buf, dtype="<f4").reshape(-1, 2).copy()
            _kill(self.proc)
            if not self.loop or got == 0:
                return

    def close(self) -> None:
        if self.proc:
            _kill(self.proc)


class WavSource:
    """Stdlib-only fallback for 16-bit PCM WAV when ffmpeg is missing."""

    def __init__(self, path: str, block: int, loop: bool = False):
        self.path, self.block, self.loop = path, block, loop
        with wave.open(path, "rb") as w:
            self.rate = w.getframerate()
            if w.getsampwidth() != 2:
                raise AudioError("only 16-bit WAV is supported without ffmpeg")

    def __iter__(self):
        while True:
            with wave.open(self.path, "rb") as w:
                ch = w.getnchannels()
                while True:
                    raw = w.readframes(self.block)
                    if not raw:
                        break
                    x = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
                    x = x.reshape(-1, ch)
                    x = np.repeat(x, 2, axis=1) if ch == 1 else x[:, :2]
                    yield np.ascontiguousarray(x)
            if not self.loop:
                return

    def close(self) -> None:
        pass


def open_file(path: str, rate: int, block: int, loop: bool = False):
    """Returns (source, rate). Prefers ffmpeg, falls back to stdlib WAV."""
    if shutil.which("ffmpeg"):
        return FfmpegSource(path, rate, block, loop), rate
    if path.lower().endswith(".wav"):
        src = WavSource(path, block, loop)
        return src, src.rate
    raise AudioError("ffmpeg is required to decode this file type (WAV works without it)")


# ---- sinks -----------------------------------------------------------------
class PacatSink:
    def __init__(self, device: Optional[str], rate: int, latency_ms: int = 30):
        cmd = ["pacat", "--playback", f"--rate={rate}", "--channels=2",
               "--format=float32le", f"--latency-msec={latency_ms}",
               "--client-name=DanEQ", "--stream-name=output"]
        if device:
            cmd.append(f"--device={device}")
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)

    def write(self, data: bytes) -> None:
        try:
            self.proc.stdin.write(data)
            self.proc.stdin.flush()
        except (BrokenPipeError, ValueError):
            raise AudioError("playback stream closed (sound server went away?)")

    def close(self) -> None:
        _kill(self.proc)


class NullSink:
    """Discards audio but paces the engine in real time (for --no-output)."""

    def __init__(self, rate: int):
        self.rate = rate
        self._next = None

    def write(self, data: bytes) -> None:
        frames = len(data) // 8
        now = time.perf_counter()
        if self._next is None:
            self._next = now
        self._next += frames / self.rate
        delay = self._next - now
        if delay > 0:
            time.sleep(delay)
        elif delay < -1.0:
            self._next = now

    def close(self) -> None:
        pass


def _kill(proc: subprocess.Popen) -> None:
    try:
        proc.terminate()
        proc.wait(timeout=1.0)
    except Exception:  # noqa: BLE001
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass
