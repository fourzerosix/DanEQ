"""Real-time engine thread: source -> EQ -> meters/analyzer tap -> sink."""
from __future__ import annotations

import threading
import time

import numpy as np


class Engine(threading.Thread):
    def __init__(self, eq, source, sink, rate: int, block: int = 1024,
                 nfft: int = 4096, latency_ms: float = 0.0):
        super().__init__(name="daneq-engine", daemon=True)
        self.eq = eq
        self.source = source
        self.sink = sink
        self.rate = rate
        self.block = block
        self.nfft = nfft
        self.latency_ms = latency_ms
        self.muted = False
        self.load = 0.0
        self.last_clip = 0.0
        self.error = None
        self.finished = False
        self._stop_evt = threading.Event()
        self._lock = threading.Lock()
        self._ring = np.zeros(nfft, dtype=np.float32)
        self._peak = np.zeros(2)
        self._ssq = np.zeros(2)
        self._cnt = 0

    def stop(self) -> None:
        self._stop_evt.set()

    def run(self) -> None:
        try:
            for blk in self.source:
                if self._stop_evt.is_set():
                    break
                t0 = time.perf_counter()
                y = self.eq.process(blk)
                if self.muted:
                    y = np.zeros_like(y)
                absy = np.abs(y)
                peak = absy.max(axis=0)
                mono = y.mean(axis=1)
                with self._lock:
                    self._peak = np.maximum(self._peak, peak)
                    self._ssq += (y.astype(np.float64) ** 2).sum(axis=0)
                    self._cnt += len(y)
                    if len(mono) >= self.nfft:
                        self._ring = mono[-self.nfft:].copy()
                    else:
                        self._ring = np.concatenate((self._ring[len(mono):], mono))
                if peak.max() > 1.0:
                    self.last_clip = time.time()
                if peak.max() > 0.9:  # soft knee limiter: never exceeds full scale
                    y = np.where(absy > 0.9, np.sign(y) * (0.9 + 0.1 * np.tanh((absy - 0.9) / 0.1)), y)
                busy = time.perf_counter() - t0
                self.load += 0.1 * (busy / (len(blk) / self.rate) - self.load)
                self.sink.write(np.ascontiguousarray(y, dtype="<f4").tobytes())
        except Exception as exc:  # noqa: BLE001 - surfaced to the UI
            if not self._stop_evt.is_set():
                self.error = exc
        finally:
            self.finished = True

    # ---- taps for the UI --------------------------------------------------
    def snapshot(self) -> np.ndarray:
        with self._lock:
            return self._ring.copy()

    def take_meter(self):
        """Peak and RMS (linear, per channel) since the last call."""
        with self._lock:
            peak = self._peak.copy()
            rms = np.sqrt(self._ssq / max(self._cnt, 1))
            self._peak[:] = 0
            self._ssq[:] = 0
            self._cnt = 0
        return peak, rms
