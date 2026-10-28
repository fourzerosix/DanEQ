"""DanEQ command line entry point."""
from __future__ import annotations

import argparse
import locale
import os
import signal
import sys

import numpy as np

from . import __version__, audio, config, sounds
from .dsp import LAYOUTS, PRESET_ORDER, Equalizer, preset_gains, to_apo
from .effects import ORDER, FxRack
from .themes import THEME_ORDER

BLOCK = 1024
SHORTCUTS = sorted(set(sounds.ALL) - {"music"}) + ["music"]
VIEW_NAMES = ["spectrum", "waterfall", "scope", "vectorscope", "radial", "vinyl", "reel-to-reel",
              "fire", "starfield", "ripples", "matrix"]
STYLE_NAMES = ["braille", "line", "mirror", "dots", "blocks", "ascii"]


def parse_beat(text: str) -> float:
    from .synth import BEATS
    t = text.lower()
    return BEATS[t] if t in BEATS else float(t)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="daneq", allow_abbrev=False,
        description="DanEQ: a btop-style terminal equalizer, effects rack and audio visualizer.",
        epilog="With no FILE, --demo or sound shortcut, DanEQ equalizes all system audio via a virtual sink.")
    p.add_argument("file", nargs="?", help="audio file to play through DanEQ (WAV, or anything ffmpeg/soundfile reads)")
    src = p.add_argument_group("test signals and easter eggs")
    src.add_argument("--demo", nargs="?", const="music", choices=sorted(sounds.ALL), metavar="NAME",
                     help="built-in signal (see --list-demos); default: music")
    for name in SHORTCUTS:
        try:
            src.add_argument(f"--{name}", dest="demo", action="store_const", const=name,
                             help=argparse.SUPPRESS)
        except argparse.ArgumentError:
            pass
    src.add_argument("--beat", metavar="HZ|NAME", default="10",
                     help="binaural beat frequency or delta/theta/alpha/beta/gamma/schumann (default 10)")
    src.add_argument("--carrier", type=float, default=220.0, metavar="HZ", help="binaural carrier (default 220)")
    src.add_argument("--clip", metavar="NAME|PATH|URL", help="play a clip from the clip library, a local file or a URL")
    src.add_argument("--list-clips", action="store_true", help="list the clip library and exit")
    src.add_argument("--list-demos", action="store_true", help="list all built-in signals and exit")
    io = p.add_argument_group("audio routing")
    io.add_argument("--backend", choices=["auto", "pulse", "portaudio"], default="auto",
                    help="audio backend: pulse (Linux, default there) or portaudio (macOS default)")
    io.add_argument("--input", metavar="DEVICE", help="portaudio: capture device name or number (default: BlackHole/loopback)")
    io.add_argument("--output", metavar="DEVICE", help="portaudio: output device name or number (default: system output)")
    io.add_argument("--list-devices", action="store_true", help="portaudio: list audio devices and exit")
    io.add_argument("--no-output", action="store_true", help="do not play audio, just process and visualize")
    io.add_argument("--sink", metavar="NAME", help="output sink (default: current default sink)")
    io.add_argument("--capture", metavar="SOURCE", help="capture from this source instead of the virtual sink")
    io.add_argument("--rate", type=int, default=48000, help="sample rate (default 48000)")
    io.add_argument("--latency", type=int, default=30, metavar="MS", help="stream latency in ms (default 30)")
    io.add_argument("--loop", action="store_true", help="loop FILE")
    ui = p.add_argument_group("interface")
    ui.add_argument("--bands", type=int, choices=sorted(LAYOUTS), help="number of EQ bands (default 10)")
    ui.add_argument("--preset", choices=PRESET_ORDER, help="start with this EQ preset")
    ui.add_argument("--theme", choices=THEME_ORDER, help="color theme")
    ui.add_argument("--view", choices=VIEW_NAMES, help="start in this view")
    ui.add_argument("--style", choices=STYLE_NAMES, help="spectrum bar style")
    ui.add_argument("--fx", metavar="LIST", help="enable effects at start, e.g. reverb,echo,comp")
    ui.add_argument("--fps", type=int, metavar="N", help="target frame rate (default 60)")
    ui.add_argument("--nerd", action="store_true", help="start in nerd mode (audio processes and streams)")
    ui.add_argument("--no-mouse", action="store_true", help="disable mouse support")
    misc = p.add_argument_group("maintenance")
    misc.add_argument("--list", action="store_true", help="list output sinks and exit")
    misc.add_argument("--export", action="store_true", help="print saved settings as Equalizer APO text and exit")
    misc.add_argument("--list-presets", action="store_true", help="list EQ presets and exit")
    misc.add_argument("--restore", action="store_true", help="remove a leftover virtual sink and fix the default sink")
    misc.add_argument("--selftest", action="store_true", help="verify the DSP against its analytic response and exit")
    misc.add_argument("--version", action="version", version=f"daneq {__version__}")
    return p


def selftest() -> int:
    """Pushes real tones through the filters and checks them against the displayed curve."""
    rate, bad = 48000, 0
    print(f"DanEQ {__version__} DSP self-test ({rate} Hz)")
    for nb in sorted(LAYOUTS):
        eq = Equalizer(nb, rate, 1)
        x = (np.random.default_rng(0).standard_normal((rate, 1)) * 0.1).astype(np.float32)
        flat_ok = float(np.abs(eq.process(x) - x).max()) < 1e-6
        bad += not flat_ok
        print(f"  {nb:2d}-band flat passthrough: {'PASS' if flat_ok else 'FAIL'}")
        for gain in (9.0, -9.0):
            worst = 0.0
            for i, f in enumerate(eq.freqs):
                e = Equalizer(nb, rate, 1)
                e.set_gain(i, gain)
                t = np.arange(rate * 2) / rate
                tone = (0.1 * np.sin(2 * np.pi * f * t)).astype(np.float32)[:, None]
                y = e.process(tone)[rate:]
                meas = 20 * np.log10(y.std() / tone[rate:].std())
                worst = max(worst, abs(meas - float(e.response_db([f])[0])))
            ok = worst < 0.1
            bad += not ok
            print(f"  {nb:2d}-band {gain:+.0f} dB, every band: worst error {worst:.3f} dB: {'PASS' if ok else 'FAIL'}")
    rack = FxRack(rate)
    x = (np.random.default_rng(1).standard_normal((BLOCK * 8, 2)) * 0.1)
    for fx in rack.fx:
        fx.set_enabled(True)
        y = np.vstack([fx.process(x[i:i + BLOCK]) for i in range(0, len(x), BLOCK)])
        ok = bool(np.isfinite(y).all()) and y.shape == x.shape
        bad += not ok
        print(f"  fx {fx.name:<15s} finite and shape-preserving: {'PASS' if ok else 'FAIL'}")
        fx.set_enabled(False)
    print("RESULT:", "all checks passed" if not bad else f"{bad} check(s) failed")
    return 1 if bad else 0


def _die(msg: str) -> int:
    print(f"daneq: {msg}", file=sys.stderr)
    return 1


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.selftest:
        return selftest()
    if args.list_presets:
        print("\n".join(PRESET_ORDER))
        return 0
    if args.list_demos:
        for name in sorted(sounds.ALL):
            print(f"{name:12s} {sounds.DESCRIPTIONS.get(name, '')}")
        return 0
    if args.list_clips:
        from . import clips
        print(clips.describe())
        return 0
    if args.export:
        cfg = config.load()
        nb = args.bands or int(cfg.get("bands", 10))
        eq = Equalizer(nb if nb in LAYOUTS else 10, args.rate, 2)
        if cfg.get("gains", {}).get(str(eq.nbands)):
            eq.set_gains(cfg["gains"][str(eq.nbands)])
        eq.set_preamp(float(cfg.get("preamp", 0.0)))
        if args.preset:
            eq.set_gains(preset_gains(args.preset, eq.freqs))
        print(to_apo(eq), end="")
        return 0
    if args.list_devices:
        try:
            for i, name, n_in, n_out, rate, virt in audio.list_devices():
                print(f"{i:3d}  in={n_in} out={n_out}  {rate}Hz  {name}{'  [virtual]' if virt else ''}")
        except audio.AudioError as exc:
            return _die(str(exc))
        return 0
    if args.list or args.restore:
        try:
            if args.restore:
                print("default sink:", audio.restore() or "(none)")
            else:
                for idx, name in audio.list_sinks():
                    print(f"{idx}\t{name}")
        except audio.AudioError as exc:
            return _die(str(exc))
        return 0

    locale.setlocale(locale.LC_ALL, "")
    if "utf" not in (locale.getpreferredencoding(False) or "").lower():
        print("daneq: warning: terminal is not UTF-8; try LANG=en_US.UTF-8", file=sys.stderr)
    if not sys.stdout.isatty():
        return _die("needs an interactive terminal (try --selftest for a headless check)")

    cfg = config.load()
    nb = args.bands or int(cfg.get("bands", 10))
    if nb not in LAYOUTS:
        nb = 10
    rate, mode = args.rate, "system"
    vsink = source = sink = collector = None
    target = args.file
    if args.clip:
        from . import clips
        try:
            target = clips.resolve(args.clip)
        except clips.ClipError as exc:
            return _die(str(exc))
    live = not (target or args.demo)
    backend = args.backend
    if backend == "auto":
        backend = "pulse" if (sys.platform.startswith("linux") and audio.have_pulse_tools()) else \
                  ("portaudio" if audio.have_portaudio() else "pulse")
    mac_in = route = None

    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, lambda *_: sys.exit(0))

    try:
        if target:
            mode = os.path.basename(target)
            source, rate = audio.open_file(target, rate, BLOCK, args.loop)
        elif args.demo:
            mode = f"demo:{args.demo}"
            try:
                opts = {"beat": parse_beat(args.beat), "carrier": args.carrier}
            except (KeyError, ValueError):
                return _die("--beat needs a number or one of delta, theta, alpha, beta, gamma, schumann")
            source = audio.GenSource(sounds.ALL[args.demo](rate, BLOCK, **opts))
            if args.demo == "binaural":
                mode = f"binaural {opts['beat']:g} Hz beat (use headphones)"
        if live and backend == "portaudio" and not args.no_output:
            mac_in = audio.find_device(args.input or args.capture, "input") if (args.input or args.capture) else audio.pick_loopback()
            if mac_in is None:
                return _die("no loopback capture device found.\n" + audio.mac_help())
            rate = mac_in[4]
        eq = Equalizer(nb, rate, 2)
        saved = cfg.get("gains", {}).get(str(nb))
        if saved:
            eq.set_gains(saved)
        eq.set_preamp(float(cfg.get("preamp", 0.0)))
        if args.preset:
            eq.set_gains(preset_gains(args.preset, eq.freqs))
        fx = FxRack(rate)
        if isinstance(cfg.get("fx"), dict):
            fx.load(cfg["fx"])
        if args.fx:
            for name in args.fx.split(","):
                f = fx.by_short(name.strip())
                if f is None:
                    return _die(f"unknown effect '{name}'. Choose from: " + ", ".join(c.short.lower() for c in ORDER))
                f.set_enabled(True)
        for key, val in (("theme", args.theme), ("view", args.view), ("style", args.style), ("fps", args.fps)):
            if val:
                cfg[key] = val
        if args.nerd:
            cfg["nerd_start"] = True

        dst = "(no output)"
        src = ""
        if args.no_output:
            if live:
                return _die("--no-output needs FILE, --demo or a sound shortcut")
            sink = audio.NullSink(rate)
        elif backend == "portaudio":
            if not audio.have_portaudio():
                return _die("the portaudio backend needs: pip install sounddevice\n" + (audio.mac_help() if sys.platform == "darwin" else ""))
            out = audio.find_device(args.output, "output") if args.output else audio.pick_output()
            if out is None:
                return _die("no real output device found (try --list-devices and --output NAME)")
            if live:
                source = audio.SdSource(mac_in[0], rate, BLOCK)
                src = f"capture '{mac_in[1]}'"
                if sys.platform == "darwin":
                    route = audio.MacRoute(mac_in[1])
                    if not route.open():
                        src += f" (set Sound Output to '{mac_in[1]}')"
            dst = out[1]
            sink = audio.SdSink(out[0], rate, BLOCK)
        else:
            if not audio.have_pulse_tools():
                return _die("pactl/parec/pacat not found. Install pulseaudio-utils (works with PipeWire too), "
                            "or use --demo --no-output" + (("\n" + audio.mac_help()) if sys.platform == "darwin" else ""))
            if live and not args.capture:
                vsink = audio.VirtualSink(rate, args.sink)
                dst = vsink.open()
                source = audio.ParecSource(vsink.monitor, rate, BLOCK, max(10, args.latency // 2))
                src = f"all apps via sink '{audio.VSINK}'"
            else:
                dst = args.sink or audio.default_sink() or "default"
                if live:
                    source = audio.ParecSource(args.capture, rate, BLOCK, max(10, args.latency // 2))
            sink = audio.PacatSink(args.sink if args.sink else (vsink.target if vsink else None), rate, args.latency)
        if live:
            info = f"{args.capture or src} > {dst}  {rate}Hz"
        else:
            info = f"{mode} > {dst}  {rate}Hz"
        lat = (args.latency * 1.5 + BLOCK * 1000.0 / rate) if not args.no_output else 0.0

        from .engine import Engine
        from .nerd import Collector
        from . import ui
        collector = Collector()
        collector.start()
        engine = Engine(eq, source, sink, rate, BLOCK, latency_ms=lat, fx=fx)
        engine.start()
        try:
            state = ui.run(engine, eq, fx, cfg, info, mouse=not args.no_mouse, collector=collector)
        finally:
            engine.stop()
            collector.stop()
        if state:
            config.save(state)
        if engine.error:
            return _die(str(engine.error))
        return 0
    except audio.AudioError as exc:
        return _die(str(exc))
    except KeyboardInterrupt:
        return 0
    finally:
        for obj in (source, sink):
            if obj is not None:
                try:
                    obj.close()
                except Exception:  # noqa: BLE001
                    pass
        if vsink is not None:
            vsink.close()
        if route is not None:
            route.close()
