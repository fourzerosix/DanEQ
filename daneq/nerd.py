"""Nerd mode: audio related processes, streams, devices and server info (btop style)."""
from __future__ import annotations

import os
import pwd
import re
import subprocess
import threading
import time
from collections import deque
from typing import Dict, List

import numpy as np

from .braille import bar_rows

CLK = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
PAGE = os.sysconf("SC_PAGE_SIZE") if hasattr(os, "sysconf") else 4096

SERVERS = {"pipewire", "pipewire-pulse", "wireplumber", "pulseaudio", "pipewire-media-session",
           "jackd", "jackdbus", "jackd1", "alsa-sink", "pw-jack"}
TOOLS = {"easyeffects", "pavucontrol", "pasystray", "qjackctl", "carla", "ardour", "audacity",
         "mpd", "pw-top", "pw-cli", "pactl", "parec", "pacat", "helvum", "qpwgraph", "cava"}


# ---- pactl text parsers (pure functions, unit tested) -----------------------------------
def _blocks(text: str, header: str) -> List[List[str]]:
    out, cur = [], None
    for line in text.splitlines():
        if line.startswith(header):
            cur = [line]
            out.append(cur)
        elif cur is not None:
            cur.append(line)
    return out


def _field(lines: List[str], key: str) -> str:
    for ln in lines:
        s = ln.strip()
        if s.startswith(key + ":"):
            return s.split(":", 1)[1].strip()
    return ""


def _prop(lines: List[str], key: str) -> str:
    for ln in lines:
        s = ln.strip()
        if s.startswith(key + " ="):
            return s.split("=", 1)[1].strip().strip('"')
    return ""


def _vol(lines: List[str]) -> int:
    m = re.search(r"(\d+)%", _field(lines, "Volume"))
    return int(m.group(1)) if m else -1


def _usec(s: str) -> float:
    m = re.search(r"([\d.]+)\s*usec", s)
    return float(m.group(1)) / 1000.0 if m else -1.0


def parse_streams(text: str, header: str) -> List[Dict]:
    out = []
    for b in _blocks(text, header):
        pid = _prop(b, "application.process.id")
        out.append({
            "id": b[0].split("#")[-1].strip(),
            "app": _prop(b, "application.name") or _prop(b, "node.name") or "?",
            "media": _prop(b, "media.name"),
            "dev": _field(b, "Sink") or _field(b, "Source"),
            "vol": _vol(b), "mute": _field(b, "Mute") == "yes",
            "spec": _field(b, "Sample Specification"),
            "lat": _usec(_field(b, "Buffer Latency")),
            "corked": _field(b, "Corked") == "yes",
            "pid": int(pid) if pid.isdigit() else 0,
            "driver": _field(b, "Driver"),
        })
    return out


def parse_devices(text: str, header: str) -> List[Dict]:
    out = []
    for b in _blocks(text, header):
        name = _field(b, "Name")
        out.append({
            "id": b[0].split("#")[-1].strip(), "name": name,
            "desc": _field(b, "Description") or name,
            "state": _field(b, "State"), "spec": _field(b, "Sample Specification"),
            "vol": _vol(b), "mute": _field(b, "Mute") == "yes",
            "monitor": name.endswith(".monitor"), "driver": _field(b, "Driver"),
            "lat": _usec(_field(b, "Latency")),
        })
    return out


def parse_info(text: str) -> Dict[str, str]:
    d = {}
    for ln in text.splitlines():
        if ":" in ln:
            k, v = ln.split(":", 1)
            d[k.strip()] = v.strip()
    return d


def parse_alsa_status(text: str) -> Dict[str, str]:
    d = {}
    for ln in text.splitlines():
        if ":" in ln:
            k, v = ln.split(":", 1)
            d[k.strip()] = v.strip()
    return d


# ---- /proc helpers ---------------------------------------------------------------------------
def read_proc(pid: int):
    """(name, state, ticks, threads, rss_mb, uid) or None."""
    try:
        with open(f"/proc/{pid}/stat") as f:
            raw = f.read()
        name = raw[raw.index("(") + 1: raw.rindex(")")]
        rest = raw[raw.rindex(")") + 2:].split()
        ticks = int(rest[11]) + int(rest[12])
        uid = os.stat(f"/proc/{pid}").st_uid
        return name, rest[0], ticks, int(rest[17]), int(rest[21]) * PAGE / 1048576.0, uid
    except (OSError, ValueError, IndexError):
        return None


def snd_users() -> Dict[int, str]:
    """pid -> 'ALSA' for processes holding /dev/snd/* open (only those we may inspect)."""
    out = {}
    for ent in os.listdir("/proc"):
        if not ent.isdigit():
            continue
        try:
            for fd in os.listdir(f"/proc/{ent}/fd"):
                try:
                    if os.readlink(f"/proc/{ent}/fd/{fd}").startswith("/dev/snd/"):
                        out[int(ent)] = "ALSA"
                        break
                except OSError:
                    continue
        except OSError:
            continue
    return out


def alsa_cards() -> List[str]:
    try:
        with open("/proc/asound/cards") as f:
            return [ln.rstrip() for ln in f if ln.strip() and ln[:2].strip().isdigit()]
    except OSError:
        return []


def alsa_running() -> List[Dict[str, str]]:
    out = []
    base = "/proc/asound"
    try:
        for card in sorted(os.listdir(base)):
            if not card.startswith("card"):
                continue
            for pcm in sorted(os.listdir(f"{base}/{card}")):
                if not pcm.startswith("pcm"):
                    continue
                for sub in sorted(os.listdir(f"{base}/{card}/{pcm}")):
                    if not sub.startswith("sub"):
                        continue
                    try:
                        with open(f"{base}/{card}/{pcm}/{sub}/status") as f:
                            st = parse_alsa_status(f.read())
                    except OSError:
                        continue
                    if st.get("state") == "RUNNING":
                        st["where"] = f"{card}/{pcm}"
                        out.append(st)
    except OSError:
        pass
    return out


def run(*args: str) -> str:
    try:
        r = subprocess.run(list(args), capture_output=True, text=True, timeout=4)
        return r.stdout if r.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


# ---- collector thread -----------------------------------------------------------------------
class Collector(threading.Thread):
    def __init__(self, interval: float = 1.5):
        super().__init__(name="daneq-nerd", daemon=True)
        self.interval = interval
        self.data = {"procs": [], "sinks": [], "sources": [], "inputs": [], "outputs": [],
                     "info": {}, "cards": [], "alsa": [], "have_pactl": True, "t": 0.0}
        self.active = threading.Event()
        self._prev, self._hist = {}, {}
        self._stop_evt = threading.Event()
        self._snd, self._snd_t = {}, 0.0

    def stop(self):
        self._stop_evt.set()
        self.active.set()

    def run(self):
        while not self._stop_evt.is_set():
            self.active.wait()
            if self._stop_evt.is_set():
                return
            try:
                self.collect()
            except Exception:  # noqa: BLE001 - never kill the thread
                pass
            self._stop_evt.wait(self.interval)

    def collect(self):
        t = time.time()
        info_txt = run("pactl", "info")
        have = bool(info_txt)
        inputs = parse_streams(run("pactl", "list", "sink-inputs"), "Sink Input #") if have else []
        outputs = parse_streams(run("pactl", "list", "source-outputs"), "Source Output #") if have else []
        sinks = parse_devices(run("pactl", "list", "sinks"), "Sink #") if have else []
        sources = parse_devices(run("pactl", "list", "sources"), "Source #") if have else []
        if t - self._snd_t > 3.0:
            self._snd, self._snd_t = snd_users(), t
        names = {x["id"]: x["name"] for x in sinks + sources}
        for st in inputs + outputs:
            st["dev"] = names.get(st["dev"], st["dev"])
        pids = {s["pid"]: "stream" for s in inputs + outputs if s["pid"]}
        mine = os.getpid()
        procs, seen = [], set()
        for ent in os.listdir("/proc"):
            if not ent.isdigit():
                continue
            pid = int(ent)
            info = read_proc(pid)
            if info is None:
                continue
            name, state, ticks, thr, rss, uid = info
            tags = []
            if name in SERVERS:
                tags.append("server")
            if name in TOOLS:
                tags.append("tool")
            if pid in pids:
                tags.append("stream")
            if pid in self._snd:
                tags.append("alsa")
            if pid == mine or name in ("parec", "pacat"):
                tags.append("daneq" if pid == mine else "daneq-io")
            if not tags:
                continue
            seen.add(pid)
            prev = self._prev.get(pid)
            cpu = 0.0
            if prev and t > prev[1]:
                cpu = max(0.0, (ticks - prev[0]) / CLK / (t - prev[1]) * 100.0)
            self._prev[pid] = (ticks, t)
            h = self._hist.setdefault(pid, deque(maxlen=16))
            h.append(cpu)
            try:
                user = pwd.getpwuid(uid).pw_name
            except KeyError:
                user = str(uid)
            procs.append({"pid": pid, "name": name, "user": user, "state": state, "cpu": cpu, "rss": rss,
                          "threads": thr, "tags": ",".join(tags), "hist": list(h)})
        for pid in list(self._prev):
            if pid not in seen:
                self._prev.pop(pid, None)
                self._hist.pop(pid, None)
        self.data = {"procs": procs, "sinks": sinks, "sources": sources, "inputs": inputs, "outputs": outputs,
                     "info": parse_info(info_txt), "cards": alsa_cards(), "alsa": alsa_running(),
                     "have_pactl": have, "t": t}


def spark(values, cells: int, vmax: float = 100.0) -> str:
    """Braille sparkline, two samples per cell."""
    v = list(values)[-cells * 2:]
    v = [0.0] * (cells * 2 - len(v)) + v
    lv = np.clip((np.asarray(v) / max(vmax, 1e-9) * 4).round().astype(int), 0, 4)
    return bar_rows(lv, np.full(len(lv), -1), 1)[0]


SORTS = ["cpu", "mem", "pid", "name"]


def sort_procs(procs, key):
    if key == "mem":
        return sorted(procs, key=lambda p: -p["rss"])
    if key == "pid":
        return sorted(procs, key=lambda p: p["pid"])
    if key == "name":
        return sorted(procs, key=lambda p: (p["name"], p["pid"]))
    return sorted(procs, key=lambda p: (-p["cpu"], p["pid"]))


class NerdView:
    """Drawing + local state for nerd mode."""

    def __init__(self, collector: Collector):
        self.col = collector
        self.sel = 0
        self.sort = 0
        self.load_hist = deque(maxlen=120)
        self.lat_hist = deque(maxlen=120)
        self._t = 0.0

    def on_key(self, k, curses) -> bool:
        if k in (curses.KEY_DOWN, ord("j")):
            self.sel += 1
        elif k in (curses.KEY_UP, ord("k")):
            self.sel = max(self.sel - 1, 0)
        elif k == curses.KEY_NPAGE:
            self.sel += 8
        elif k == curses.KEY_PPAGE:
            self.sel = max(self.sel - 8, 0)
        elif k == ord("o"):
            self.sort = (self.sort + 1) % len(SORTS)
        else:
            return False
        return True

    def draw(self, app, y, x, h, w):
        c = app.c
        d = self.col.data
        now = time.time()
        if now - self._t > 0.25:
            self._t = now
            self.load_hist.append(app.engine.load * 100.0)
        eng = app.engine
        top_h = min(11, max(8, h // 3))
        left_w = w // 3
        # --- server / engine ---
        app.box(y, x, top_h, left_w, "DanEQ engine")
        info = d["info"]
        lines = [
            ("rate", f"{eng.rate}Hz blk {eng.block} ({eng.block * 1000 / eng.rate:.0f}ms)"),
            ("dsp", f"{eng.load * 100:.1f}%  lat ~{eng.latency_ms:.0f}ms"),
            ("eq", f"{app.eq.nbands}-band {'BYPASS' if app.eq.bypass else 'on'}  preamp {app.eq.preamp:+.1f} dB"),
            ("fx", ", ".join(f.short for f in app.fx.fx if f.enabled) or "none"),
            ("server", info.get("Server Name", "n/a" if d["have_pactl"] else "pactl missing")),
            ("version", info.get("Server Version", "")),
            ("default", info.get("Default Sink", "")),
            ("source", info.get("Default Source", "")),
        ]
        for i, (k, v) in enumerate(lines[: top_h - 2]):
            app.put(y + 1 + i, x + 2, f"{k:8s}", c.dim)
            app.put(y + 1 + i, x + 11, v[: left_w - 13], c.text)
        # --- dsp graph ---
        mid_w = w // 3
        app.box(y, x + left_w, top_h, mid_w, "DSP load", f"{eng.load * 100:.0f}%")
        gw, gh = mid_w - 2, top_h - 2
        from .braille import Canvas, blit
        cv = Canvas(gw, gh)
        vals = list(self.load_hist)[-gw * 2:]
        top = max(30.0, max(vals) if vals else 30.0)
        prev = None
        for i, v in enumerate(vals):
            xx, yy = gw * 2 - len(vals) + i, (1 - min(v / top, 1)) * (gh * 4 - 1)
            if prev:
                cv.line(prev[0], prev[1], xx, yy)
            prev = (xx, yy)
        blit(app.put, y + 1, x + left_w + 1, [(cv, c.curve)])
        # --- devices ---
        dev_w = w - left_w - mid_w
        app.box(y, x + left_w + mid_w, top_h, dev_w, "Devices")
        rows = []
        dflt = info.get("Default Sink", "")
        for s in d["sinks"]:
            rows.append((f"{'*' if s['name'] == dflt else ' '}out {s['state'][:4]:4s} {s['vol']:>3d}%{'M' if s['mute'] else ' '}", s["desc"]))
        for s in d["sources"]:
            if not s["monitor"]:
                rows.append((f" in  {s['state'][:4]:4s} {s['vol']:>3d}%{'M' if s['mute'] else ' '}", s["desc"]))
        for a in d["alsa"]:
            rows.append((" hw  RUN ", f"{a['where']} pid {a.get('owner_pid', '?')}"))
        if not rows:
            rows = [("", "no devices (pactl unavailable)" if not d["have_pactl"] else "none")]
        for i, (a, b) in enumerate(rows[: top_h - 2]):
            app.put(y + 1 + i, x + left_w + mid_w + 2, a, c.dim)
            app.put(y + 1 + i, x + left_w + mid_w + 2 + len(a) + 1, b[: dev_w - 6 - len(a)], c.text)
        # --- streams ---
        st_h = min(9, max(5, h // 4))
        py, ph = y + top_h, h - top_h - st_h
        # --- processes ---
        procs = sort_procs(d["procs"], SORTS[self.sort])
        self.sel = min(self.sel, max(len(procs) - 1, 0))
        app.box(py, x, ph, w, "Audio processes", f"sort: {SORTS[self.sort]} (o)   {len(procs)} found")
        hdr = f"{'PID':>7} {'USER':<10} {'NAME':<18} {'TAGS':<22} {'CPU%':>6} {'MEM':>7} {'THR':>4} S  HISTORY"
        app.put(py + 1, x + 2, hdr[: w - 4], c.title)
        vis = ph - 3
        off = max(0, min(self.sel - vis + 1, len(procs) - vis)) if len(procs) > vis else 0
        for i, p in enumerate(procs[off: off + vis]):
            row = (f"{p['pid']:>7} {p['user'][:10]:<10} {p['name'][:18]:<18} {p['tags'][:22]:<22} "
                   f"{p['cpu']:>6.1f} {p['rss']:>6.0f}M {p['threads']:>4} {p['state']}  ")
            attr = c.accent if off + i == self.sel else (c.text if p["cpu"] > 0.05 else c.dim)
            app.put(py + 2 + i, x + 2, row[: w - 4], attr)
            sx = x + 2 + len(row)
            if sx + 8 < x + w - 1:
                app.put(py + 2 + i, sx, spark(p["hist"], 8, max(20.0, max(p["hist"]))), c.at(min(p["cpu"] / 100.0, 1.0)))
        if not procs:
            app.put(py + 2, x + 2, "no audio processes found", c.dim)
        # --- streams ---
        sy = py + ph
        app.box(sy, x, st_h, w, "Streams", "playback > / < capture")
        srows = [(">", s) for s in d["inputs"]] + [("<", s) for s in d["outputs"]]
        for i, (arrow, s) in enumerate(srows[: st_h - 2]):
            flags = ("corked " if s["corked"] else "") + ("muted" if s["mute"] else "")
            line = (f"{arrow} {s['app'][:16]:<16} {s['media'][:24]:<24} {s['dev'][:26]:<26} "
                    f"{s['vol']:>3d}%  {s['spec']:<22} {s['lat']:>6.1f}ms {flags}")
            app.put(sy + 1 + i, x + 2, line[: w - 4], c.text if not s["corked"] else c.dim)
        if not srows:
            app.put(sy + 1, x + 2, "no active streams" if d["have_pactl"] else "pactl not found: install pulseaudio-utils for stream info", c.dim)
