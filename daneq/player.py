"""File playback: decoders, WSOLA time stretching, varispeed resampling, playlist and transport.

Signal flow for one track:

    decoder -> SourceBuffer -> [WSOLA: tempo without pitch] -> [cubic resampler: pitch / screw] -> engine

* tempo (T) and pitch (P = 2**(semitones/12)) are independent: WSOLA stretches by a = T / P and the
  resampler then plays back at rate P, which restores the tempo and shifts the pitch.
* SCREW (S) is plain varispeed, like slowing a record: tempo and pitch move together by the same ratio.
* With everything neutral the audio passes through bit for bit.
"""
from __future__ import annotations

import math
import os
import random
import re
import shutil
import subprocess
import threading
import wave
from pathlib import Path
from typing import List, Optional

import numpy as np
from scipy import signal

AUDIO_EXTS = {".mp3", ".flac", ".wav", ".ogg", ".oga", ".opus", ".m4a", ".aac", ".wma", ".aif", ".aiff",
              ".mp4", ".m4b", ".webm", ".mka", ".mkv"}
PLAYLIST_EXTS = {".m3u", ".m3u8", ".pls"}


class DecodeError(RuntimeError):
    pass


def is_audio(path: str) -> bool:
    return Path(path).suffix.lower() in AUDIO_EXTS


def natural_key(s: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def format_time(seconds: Optional[float]) -> str:
    if seconds is None or seconds != seconds:
        return "--:--"
    s = max(int(seconds), 0)
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def scan(paths, recursive: bool = False) -> List[str]:
    """Expands files, directories and .m3u/.pls playlists into a list of audio file paths."""
    out: List[str] = []
    for raw in paths:
        p = Path(os.path.expanduser(str(raw)))
        if p.is_dir():
            if recursive:
                for root, dirs, files in os.walk(p):
                    dirs.sort(key=natural_key)
                    out += [str(Path(root) / f) for f in sorted(files, key=natural_key) if is_audio(f)]
            else:
                out += [str(p / f) for f in sorted(os.listdir(p), key=natural_key) if is_audio(f) and (p / f).is_file()]
        elif p.suffix.lower() in PLAYLIST_EXTS and p.is_file():
            base = p.parent
            for line in p.read_text(errors="replace").splitlines():
                line = line.strip()
                if line.lower().startswith("file") and "=" in line:      # .pls
                    line = line.split("=", 1)[1].strip()
                if not line or line.startswith("#") or "=" in line[:12]:
                    continue
                q = Path(line)
                out.append(str(q if q.is_absolute() else base / q))
        else:
            out.append(str(p))
    return out


# ---- decoders ---------------------------------------------------------------------------------
class Decoder:
    rate: int = 48000
    duration: Optional[float] = None
    title: str = ""

    def read(self, n: int) -> np.ndarray:  # pragma: no cover - interface
        raise NotImplementedError

    def seek(self, seconds: float) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def close(self) -> None:
        pass


def _stereo(x: np.ndarray) -> np.ndarray:
    if x.ndim == 1:
        x = x[:, None]
    if x.shape[1] == 1:
        x = np.repeat(x, 2, axis=1)
    return np.ascontiguousarray(x[:, :2], dtype=np.float32)


class SoundfileDecoder(Decoder):
    def __init__(self, path: str):
        import soundfile as sf
        self.f = sf.SoundFile(path)
        self.rate = int(self.f.samplerate)
        self.duration = self.f.frames / float(self.rate) if self.f.frames > 0 else None
        try:
            md = self.f.copy_metadata()
            self.title = " - ".join(x for x in (md.get("artist"), md.get("title")) if x)
        except Exception:  # noqa: BLE001
            self.title = ""

    def read(self, n):
        return _stereo(self.f.read(n, dtype="float32", always_2d=True))

    def seek(self, seconds):
        self.f.seek(min(max(int(seconds * self.rate), 0), max(self.f.frames - 1, 0)))

    def close(self):
        self.f.close()


class WavDecoder(Decoder):
    """Stdlib fallback for 16-bit PCM WAV."""

    def __init__(self, path: str):
        self.w = wave.open(path, "rb")
        if self.w.getsampwidth() != 2:
            raise DecodeError("only 16-bit WAV is supported without ffmpeg or soundfile")
        self.rate = self.w.getframerate()
        self.duration = self.w.getnframes() / float(self.rate)
        self.ch = self.w.getnchannels()

    def read(self, n):
        raw = self.w.readframes(n)
        if not raw:
            return np.zeros((0, 2), np.float32)
        x = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
        return _stereo(x.reshape(-1, self.ch))

    def seek(self, seconds):
        self.w.setpos(min(max(int(seconds * self.rate), 0), max(self.w.getnframes() - 1, 0)))

    def close(self):
        self.w.close()


class FfmpegDecoder(Decoder):
    """Streams any format ffmpeg knows, resampled by ffmpeg to the engine rate."""

    def __init__(self, path: str, rate: int):
        if not shutil.which("ffmpeg"):
            raise DecodeError("ffmpeg not found")
        self.path, self.rate, self.proc = path, rate, None
        self.duration = None
        if shutil.which("ffprobe"):
            try:
                r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:format_tags=title,artist",
                                    "-of", "default=nw=1", path], capture_output=True, text=True, timeout=15)
                tags = dict(l.split("=", 1) for l in r.stdout.splitlines() if "=" in l)
                d = tags.get("duration", "")
                self.duration = float(d) if d and d != "N/A" else None
                key = lambda k: next((v for kk, v in tags.items() if kk.lower().endswith(k)), "")  # noqa: E731
                self.title = " - ".join(x for x in (key("artist"), key("title")) if x)
            except (OSError, ValueError, subprocess.TimeoutExpired):
                pass
        self.seek(0.0)
        probe = self.read(1)                       # fail early on files ffmpeg cannot decode
        if len(probe) == 0:
            raise DecodeError(f"ffmpeg could not decode {path}")
        self.seek(0.0)

    def _kill(self):
        if self.proc is not None:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=1.0)
            except Exception:  # noqa: BLE001
                try:
                    self.proc.kill()
                except Exception:  # noqa: BLE001
                    pass
            self.proc = None

    def seek(self, seconds):
        self._kill()
        self.proc = subprocess.Popen(
            ["ffmpeg", "-v", "quiet", "-ss", f"{max(seconds, 0):.3f}", "-i", self.path, "-vn", "-f", "f32le",
             "-ac", "2", "-ar", str(self.rate), "-"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    def read(self, n):
        raw = self.proc.stdout.read(n * 8)
        raw = raw[: len(raw) // 8 * 8]
        return np.frombuffer(raw, dtype="<f4").reshape(-1, 2).copy() if raw else np.zeros((0, 2), np.float32)

    def close(self):
        self._kill()


class ArrayDecoder(Decoder):
    """Decoder over an in-memory (n, 2) array. Used by the self-test and the unit tests."""

    def __init__(self, data: np.ndarray, rate: int, title: str = "array"):
        self.data = _stereo(np.asarray(data, dtype=np.float32))
        self.rate, self.pos, self.title = int(rate), 0, title
        self.duration = len(self.data) / float(rate)

    def read(self, n):
        out = self.data[self.pos:self.pos + n]
        self.pos += len(out)
        return out.copy()

    def seek(self, seconds):
        self.pos = min(max(int(seconds * self.rate), 0), len(self.data))


def open_decoder(path: str, rate: int) -> Decoder:
    errors = []
    try:
        return SoundfileDecoder(path)
    except Exception as exc:  # noqa: BLE001 - missing module, missing libsndfile or unsupported format
        errors.append(str(exc))
    try:
        return FfmpegDecoder(path, rate)
    except DecodeError as exc:
        errors.append(str(exc))
    if path.lower().endswith(".wav"):
        try:
            return WavDecoder(path)
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))
    raise DecodeError(f"cannot decode {os.path.basename(path)} (install ffmpeg or 'pip install daneq[audio]'): {errors[-1]}")


# ---- stream buffer ------------------------------------------------------------------------------
class SourceBuffer:
    """Random access (forward moving window) over a decoder, indexed in source samples."""

    def __init__(self, decoder: Decoder):
        self.dec = decoder
        self.buf = np.zeros((0, 2), np.float32)
        self.start = 0
        self.eof = False

    @property
    def end(self) -> int:
        return self.start + len(self.buf)

    def seek(self, pos: int) -> None:
        pos = max(int(pos), 0)
        self.dec.seek(pos / float(self.dec.rate))
        self.buf = np.zeros((0, 2), np.float32)
        self.start, self.eof = pos, False

    def _fill(self, upto: int) -> None:
        while self.end < upto and not self.eof:
            blk = self.dec.read(max(4096, upto - self.end))
            if len(blk) == 0:
                self.eof = True
                break
            self.buf = np.concatenate((self.buf, blk)) if len(self.buf) else blk

    def get(self, a: int, b: int) -> np.ndarray:
        self._fill(b)
        out = np.zeros((max(b - a, 0), 2), np.float32)
        lo, hi = max(a, self.start), min(b, self.end)
        if hi > lo:
            out[lo - a:hi - a] = self.buf[lo - self.start:hi - self.start]
        return out

    def trim(self, keep_from: int) -> None:
        n = keep_from - self.start
        if n > 8192:
            n = min(n, len(self.buf))
            self.buf = self.buf[n:]
            self.start += n


# ---- time stretch and resample ------------------------------------------------------------------
class Wsola:
    """Waveform similarity overlap-add: changes tempo without changing pitch."""

    N = 2048
    HS = 1024
    DELTA = 384

    def __init__(self):
        n = np.arange(self.N)
        self.win = (0.5 - 0.5 * np.cos(2.0 * np.pi * n / self.N)).astype(np.float32)[:, None]
        self.reset(0)

    def reset(self, pos: float) -> None:
        self.tau = float(pos)
        self.prev: Optional[int] = None
        self.tail = np.zeros((self.HS, 2), np.float32)

    def continue_from(self, sb: "SourceBuffer", pos: int, a: float) -> None:
        """Start stretching at `pos` as if a previous frame had been playing naturally (no dip, no click)."""
        HS = self.HS
        if pos >= HS:
            self.prev = pos - HS
            self.tail = (sb.get(pos, pos + HS) * self.win[HS:]).astype(np.float32)
            self.tau = pos - HS + HS * a
        else:
            self.reset(pos)

    def flush_natural(self, sb: "SourceBuffer"):
        """Leave stretching: returns (block that crossfades into the natural continuation, new raw pointer)."""
        if self.prev is None:
            return None, int(round(self.tau))
        p, HS = self.prev, self.HS
        blk = self.tail + sb.get(p + HS, p + 2 * HS) * self.win[:HS]
        self.prev, self.tail = None, np.zeros((HS, 2), np.float32)
        return blk.astype(np.float32), p + self.N

    def next(self, sb: SourceBuffer, a: float):
        """Produces HS new samples. `a` is the speed factor (2.0 = twice as fast, same pitch)."""
        N, HS, D = self.N, self.HS, self.DELTA
        if self.prev is None:
            p = int(round(self.tau))
        else:
            nat = self.prev + HS
            tmpl = sb.get(nat, nat + HS).mean(axis=1)
            lo = int(round(self.tau)) - D
            seg = sb.get(lo, lo + HS + 2 * D).mean(axis=1)
            corr = signal.correlate(seg, tmpl, mode="valid", method="fft")
            cs = np.concatenate(([0.0], np.cumsum(seg.astype(np.float64) ** 2)))
            energy = cs[HS:HS + 2 * D + 1] - cs[:2 * D + 1]
            score = corr / np.sqrt(energy + 1e-9)
            if lo < 0:
                score[: min(-lo, len(score))] = -np.inf
            p = lo + int(np.argmax(score))
        frame = sb.get(p, p + N) * self.win
        out = self.tail + frame[:HS]
        self.tail = frame[HS:].copy()
        self.prev = p
        self.tau += HS * a
        sb.trim(min(p + HS, int(self.tau) - D) - 64)
        done = sb.eof and self.tau - D >= sb.end
        return out, done


class Resampler:
    """Streaming cubic (Catmull-Rom) resampler with a time-varying ratio."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.buf = np.zeros((1, 2), np.float32)
        self.pos = 1.0

    def process(self, m: int, q: float, pull) -> np.ndarray:
        """m output samples, advancing q input samples per output sample. pull(n) returns n input samples."""
        last = self.pos + (m - 1) * q
        need = int(math.floor(last)) + 3
        if len(self.buf) < need:
            self.buf = np.concatenate((self.buf, pull(need - len(self.buf))))
        idx = self.pos + np.arange(m) * q
        i1 = np.floor(idx).astype(int)
        f = (idx - i1)[:, None].astype(np.float32)
        b = self.buf
        p0, p1, p2, p3 = b[i1 - 1], b[i1], b[i1 + 1], b[i1 + 2]
        out = p1 + 0.5 * f * (p2 - p0 + f * (2 * p0 - 5 * p1 + 4 * p2 - p3 + f * (3 * (p1 - p2) + p3 - p0)))
        self.pos += m * q
        drop = int(math.floor(self.pos)) - 1
        if drop > 0:
            self.buf = self.buf[drop:]
            self.pos -= drop
        return out.astype(np.float32)


class TrackPlayback:
    """Everything needed to play one track with live tempo/pitch/screw."""

    def __init__(self, path: str, rate: int, decoder: Optional[Decoder] = None):
        self.path, self.rate = path, rate
        self.dec = decoder if decoder is not None else open_decoder(path, rate)
        self.sb = SourceBuffer(self.dec)
        self.wsola, self.rs = Wsola(), Resampler()
        self.s1 = np.zeros((0, 2), np.float32)
        self.rp = 0                       # raw read pointer (source samples)
        self.mode_wsola = False
        self.exhausted = False
        self.fade = 256
        self.title = self.dec.title or Path(path).stem
        self.duration = self.dec.duration
        self._resampling = False
        self._last = np.zeros(2, np.float32)
        self._declick = 0

    # position in seconds of the source
    def position(self) -> float:
        ptr = self.wsola.tau if self.mode_wsola else self.rp
        return max(ptr / float(self.dec.rate), 0.0)

    def seek(self, seconds: float) -> None:
        seconds = max(seconds, 0.0)
        if self.duration is not None:
            seconds = min(seconds, max(self.duration - 0.05, 0.0))
        pos = int(seconds * self.dec.rate)
        self.sb.seek(pos)
        self.rp = pos
        self.wsola.reset(pos)
        self.rs.reset()
        self.s1 = np.zeros((0, 2), np.float32)
        self.exhausted = False
        self.fade = 256

    def close(self) -> None:
        self.dec.close()

    def _pull(self, n: int, a: float) -> np.ndarray:
        want_wsola = abs(a - 1.0) >= 1e-3
        if want_wsola != self.mode_wsola:
            if want_wsola:
                self.wsola.continue_from(self.sb, self.rp, a)
            else:
                blk, self.rp = self.wsola.flush_natural(self.sb)
                if blk is not None:
                    self.s1 = np.concatenate((self.s1, blk)) if len(self.s1) else blk
            self.mode_wsola = want_wsola
        while len(self.s1) < n:
            if self.exhausted:
                self.s1 = np.concatenate((self.s1, np.zeros((n - len(self.s1), 2), np.float32)))
                break
            if self.mode_wsola:
                blk, done = self.wsola.next(self.sb, a)
            else:
                blk = self.sb.get(self.rp, self.rp + 1024)
                self.rp += 1024
                self.sb.trim(self.rp - 16384)
                done = self.sb.eof and self.rp >= self.sb.end
            self.s1 = np.concatenate((self.s1, blk)) if len(self.s1) else blk
            if done:
                self.exhausted = True
        out, self.s1 = self.s1[:n], self.s1[n:]
        return out

    def render(self, m: int, tempo: float, pitch_semitones: float, screw: float):
        """Returns (block, finished)."""
        P = 2.0 ** (pitch_semitones / 12.0)
        a = tempo / P
        q = P * screw * self.dec.rate / float(self.rate)
        if abs(q - 1.0) < 1e-6:
            if self._resampling:
                self.rs.reset()
                self._resampling = False
                self._declick = 96
            out = self._pull(m, a)
        else:
            if not self._resampling:
                self._declick = 96
            self._resampling = True
            out = self.rs.process(m, q, lambda n: self._pull(n, a))
        if self._declick > 0 and len(out):
            k = min(self._declick, len(out))
            w = np.linspace(0.0, 1.0, k, dtype=np.float32)[:, None]
            out = out.copy()
            out[:k] = out[:k] * w + self._last[None, :] * (1.0 - w)
            self._declick -= k
        if len(out):
            self._last = out[-1].copy()
        if self.fade > 0:
            k = min(self.fade, len(out))
            out = out.copy()
            out[:k] *= np.linspace(0.0, 1.0, k, dtype=np.float32)[:, None]
            self.fade -= k
        finished = self.exhausted and len(self.s1) == 0
        return out, finished


# ---- playlist and transport -----------------------------------------------------------------------
class Track:
    def __init__(self, path: str):
        self.path = path
        self.title = Path(path).stem
        self.duration: Optional[float] = None
        self.error = ""


class FilePlayer:
    """A playlist with transport controls. read_block() is called by the audio engine thread."""

    REPEAT_MODES = ["off", "all", "one"]

    def __init__(self, paths, rate: int, block: int = 1024, speed=None, repeat: str = "off",
                 shuffle: bool = False, playing: bool = True, start: int = 0):
        self.rate, self.block, self.speed = rate, block, speed
        self.repeat = repeat if repeat in self.REPEAT_MODES else "off"
        self.shuffle = shuffle
        self.playing = playing
        self.ended = False
        self.message = ""
        self.cur: Optional[TrackPlayback] = None
        self.tracks: List[Track] = []
        self.order: List[int] = []
        self.index = 0
        self._lock = threading.Lock()
        self._zero = np.zeros((block, 2), np.float32)
        self._failures = 0
        self.set_playlist(paths, start)

    # ---- queries
    @property
    def count(self) -> int:
        return len(self.tracks)

    @property
    def track(self) -> Optional[Track]:
        return self.tracks[self.order[self.index]] if self.tracks and self.order else None

    @property
    def title(self) -> str:
        return (self.cur.title if self.cur else (self.track.title if self.track else ""))

    def position(self) -> float:
        return self.cur.position() if self.cur else 0.0

    def duration(self) -> Optional[float]:
        return self.cur.duration if self.cur else None

    # ---- playlist
    def _reorder(self, keep_current: bool = True) -> None:
        cur = self.order[self.index] if (keep_current and self.order and self.index < len(self.order)) else 0
        self.order = list(range(len(self.tracks)))
        if self.shuffle and len(self.order) > 1:
            rest = [i for i in self.order if i != cur]
            random.shuffle(rest)
            self.order = [cur] + rest
            self.index = 0
        else:
            self.index = self.order.index(cur) if cur in self.order else 0

    def set_playlist(self, paths, start: int = 0) -> None:
        tracks = [Track(p) for p in paths]
        with self._lock:
            old, self.cur = self.cur, None
            self.tracks = tracks
            self.order = list(range(len(tracks)))
            self.index = min(max(start, 0), max(len(tracks) - 1, 0))
            if self.shuffle and len(tracks) > 1:
                first = self.index
                rest = [i for i in self.order if i != first]
                random.shuffle(rest)
                self.order, self.index = [first] + rest, 0
            self.ended = False
        if old:
            old.close()
        self._failures = 0
        if tracks:
            self._load(self.index)

    def add(self, paths) -> None:
        with self._lock:
            had = bool(self.tracks)
            self.tracks += [Track(p) for p in paths]
            self.order += list(range(len(self.tracks) - len(list(paths)), len(self.tracks)))
        if not had and self.tracks:
            self._load(0)

    def _load(self, index: int) -> bool:
        """Open the track at order position `index` (outside the lock: opening can be slow)."""
        if not self.tracks:
            return False
        tr = self.tracks[self.order[index]]
        try:
            pb = TrackPlayback(tr.path, self.rate)
        except Exception as exc:  # noqa: BLE001 - surfaced in the UI
            tr.error = str(exc)
            self.message = f"{tr.title}: {exc}"
            self._failures += 1
            return False
        tr.title, tr.duration = pb.title, pb.duration
        with self._lock:
            old, self.cur = self.cur, pb
            self.index = index
            self.ended = False
        if old:
            old.close()
        self._failures = 0
        self.message = ""
        return True

    # ---- transport
    def play(self) -> None:
        if self.ended and self.tracks:
            self.restart_playlist()
        self.playing = True

    def pause(self) -> None:
        self.playing = False

    def toggle(self) -> None:
        self.pause() if self.playing else self.play()

    def restart_playlist(self) -> None:
        if self.tracks:
            self._load(0)
            self.playing = True

    def _step(self, direction: int) -> bool:
        n = len(self.order)
        if n == 0:
            return False
        for _ in range(n):
            idx = self.index + direction
            if idx >= n or idx < 0:
                if self.repeat == "all" or direction < 0:
                    idx %= n
                else:
                    return False
            if self._load(idx):
                return True
            self.index = idx
        return False

    def next(self) -> None:
        self._step(1)

    def prev(self) -> None:
        if self.cur and self.cur.position() > 3.0:
            self.seek_abs(0.0)
        else:
            self._step(-1)

    def seek_abs(self, seconds: float) -> None:
        with self._lock:
            if self.cur:
                self.cur.seek(seconds)
                self.ended = False

    def seek_rel(self, delta: float) -> None:
        with self._lock:
            if self.cur:
                self.cur.seek(self.cur.position() + delta)
                self.ended = False

    def cycle_repeat(self) -> str:
        self.repeat = self.REPEAT_MODES[(self.REPEAT_MODES.index(self.repeat) + 1) % 3]
        return self.repeat

    def toggle_shuffle(self) -> bool:
        self.shuffle = not self.shuffle
        with self._lock:
            self._reorder(keep_current=True)
        return self.shuffle

    # ---- audio thread
    def _speed(self):
        s = self.speed
        if s is None:
            return 1.0, 0.0, 1.0
        pitch, tempo, screw = s.effective()
        return tempo, pitch, screw

    def read_block(self) -> np.ndarray:
        if not self.playing or self.cur is None:
            return self._zero
        with self._lock:
            cur = self.cur
            tempo, pitch, screw = self._speed()
            blk, finished = cur.render(self.block, tempo, pitch, screw)
        if finished:
            self._on_track_end()
        return blk

    def _on_track_end(self) -> None:
        if self.repeat == "one":
            self.seek_abs(0.0)
        elif not self._step(1):
            self.playing, self.ended = False, True
        elif self._failures > len(self.tracks):
            self.playing = False


class PlayerSource:
    """Adapts FilePlayer to the engine's iterator-of-blocks contract (silence while paused)."""

    def __init__(self, player: FilePlayer, once: bool = False):
        self.player, self.once = player, once

    def __iter__(self):
        return self

    def __next__(self):
        if self.once and self.player.ended:
            raise StopIteration
        return self.player.read_block()

    def close(self) -> None:
        if self.player.cur:
            self.player.cur.close()


class SourceSwitch:
    """Lets the UI swap between the live/generator source and file playback while the engine keeps running."""

    def __init__(self, base=None, rate: int = 48000, block: int = 1024, speed=None, once: bool = False):
        self.base, self.rate, self.block, self.speed, self.once = base, rate, block, speed, once
        self._base_iter = None
        self.player_source: Optional[PlayerSource] = None
        self.mode = "base" if base is not None else "player"

    @property
    def player(self) -> Optional[FilePlayer]:
        return self.player_source.player if (self.player_source and self.mode == "player") else None

    def start_player(self, paths, start: int = 0, repeat: str = "off", shuffle: bool = False) -> FilePlayer:
        if self.player_source is not None:
            self.player_source.player.set_playlist(paths, start)
            self.player_source.player.playing = True
        else:
            fp = FilePlayer(paths, self.rate, self.block, self.speed, repeat, shuffle, start=start)
            self.player_source = PlayerSource(fp, self.once)
        self.mode = "player"
        return self.player_source.player

    def back_to_base(self) -> None:
        if self.base is not None:
            self.mode = "base"
            if self.player_source:
                self.player_source.player.pause()

    def __iter__(self):
        return self

    def __next__(self):
        if self.mode == "player" and self.player_source is not None:
            return next(self.player_source)
        if self._base_iter is None:
            self._base_iter = iter(self.base)
        return next(self._base_iter)

    def close(self) -> None:
        if self.player_source:
            self.player_source.close()
        if self.base is not None and hasattr(self.base, "close"):
            self.base.close()
