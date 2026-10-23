"""DanEQ command line entry point."""
from __future__ import annotations

import argparse
import locale
import os
import signal
import sys

import numpy as np

from . import __version__, audio, config, synth
from .dsp import LAYOUTS, PRESET_ORDER, Equalizer, preset_gains, to_apo

BLOCK = 1024


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="daneq",
        description="DanEQ: a btop-style terminal equalizer and spectrum visualizer.",
        epilog="With no FILE or --demo, DanEQ equalizes all system audio via a virtual sink.")
    p.add_argument("file", nargs="?", help="audio file to play through the EQ (WAV, or anything ffmpeg reads)")
    p.add_argument("--demo", nargs="?", const="music", choices=sorted(synth.GENERATORS),
                   help="built-in test signal: music (default), pink, sweep")
    p.add_argument("--no-output", action="store_true", help="do not play audio, just process and visualize")
    p.add_argument("--sink", metavar="NAME", help="output sink (default: current default sink)")
    p.add_argument("--capture", metavar="SOURCE", help="capture from this source instead of the virtual sink")
    p.add_argument("--bands", type=int, choices=sorted(LAYOUTS), help="number of EQ bands (default 10)")
    p.add_argument("--rate", type=int, default=48000, help="sample rate (default 48000)")
    p.add_argument("--latency", type=int, default=30, metavar="MS", help="stream latency in ms (default 30)")
    p.add_argument("--loop", action="store_true", help="loop FILE")
    p.add_argument("--no-mouse", action="store_true", help="disable mouse support")
    p.add_argument("--preset", choices=PRESET_ORDER, help="start with this preset")
    p.add_argument("--theme", choices=["classic", "ice", "fire", "synthwave", "mono"], help="color theme")
    p.add_argument("--export", action="store_true", help="print saved settings as Equalizer APO text and exit")
    p.add_argument("--list-presets", action="store_true", help="list presets and exit")
    p.add_argument("--list", action="store_true", help="list output sinks and exit")
    p.add_argument("--restore", action="store_true", help="remove a leftover virtual sink and fix the default sink")
    p.add_argument("--selftest", action="store_true", help="verify the DSP against its analytic response and exit")
    p.add_argument("--version", action="version", version=f"daneq {__version__}")
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
    vsink = source = sink = None
    live = not (args.file or args.demo)

    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, lambda *_: sys.exit(0))

    try:
        if args.file:
            mode = os.path.basename(args.file)
            source, rate = audio.open_file(args.file, rate, BLOCK, args.loop)
        elif args.demo:
            mode = f"demo:{args.demo}"
            source = audio.GenSource(synth.GENERATORS[args.demo](rate, BLOCK))
        eq = Equalizer(nb, rate, 2)
        saved = cfg.get("gains", {}).get(str(nb))
        if saved:
            eq.set_gains(saved)
        eq.set_preamp(float(cfg.get("preamp", 0.0)))
        if args.preset:
            eq.set_gains(preset_gains(args.preset, eq.freqs))
        if args.theme:
            cfg["theme"] = args.theme

        if args.no_output:
            if live:
                return _die("--no-output needs FILE or --demo")
            sink, dst = audio.NullSink(rate), "(no output)"
        else:
            if not audio.have_pulse_tools():
                return _die("pactl/parec/pacat not found. Install pulseaudio-utils (works with PipeWire too), "
                            "or use --demo --no-output")
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
            src = src if not args.capture else args.capture
            mode = "live"
            info = f"{src} > {dst}  {rate}Hz"
        else:
            info = f"{mode} > {dst}  {rate}Hz"
        lat = (args.latency * 1.5 + BLOCK * 1000.0 / rate) if not args.no_output else 0.0

        from .engine import Engine
        from . import ui
        engine = Engine(eq, source, sink, rate, BLOCK, latency_ms=lat)
        engine.start()
        try:
            state = ui.run(engine, eq, cfg, info, mouse=not args.no_mouse)
        finally:
            engine.stop()
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
