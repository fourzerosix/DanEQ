# DanEQ

---

A btop-style terminal equalizer and spectrum visualizer for Linux. It does not just draw
pretty bars: it sits in the audio path, so the faders you move change what you hear.


*Other tools online only visualize*. DanEQ equalizes, and it checks itself: `daneq --selftest`
pushes real sine tones through the filters and compares the measured gain to the response curve
shown in the UI (worst error is 0.000 dB across 4, 6, 8 and 10 band layouts).

---

![DanEQ](https://github.com/fourzerosix/DanEQ/blob/main/daneq/daneq-logo-full.jpg)

---

## Features

**Equalizer**
- 4, 6, 8 or 10 band EQ (`--bands`), +/-12 dB per band, preamp, bypass (A/B), mute, presets, auto headroom
- RBJ biquad filters running in real time with NumPy/SciPy; the response curve shows the exact filters in use,
  with boost and cut areas shaded
- Export your curve as Equalizer APO / EasyEffects text (`e` or `daneq --export`)

**Effects rack (`f`)**: compressor (with gain reduction readout), overdrive, bitcrusher, megaphone,
phaser, flanger, chorus, tremolo/auto-pan, echo, reverb, stereo widener. Every effect has braille rotary
knobs you can drive with keys, mouse wheel or click. Start with some on: `daneq --fx reverb,echo`.

**Visuals (`v` / `V`, `--view`)**: spectrum (6 bar styles on `g`), waterfall, scope, vectorscope, radial,
spinning vinyl record, reel-to-reel tape deck, fire, starfield, ripples, matrix rain.
20 color themes (`c`), 60 fps with smooth physics, multi-resolution FFT.

**Nerd mode (`n`)**: btop-style view of audio processes (servers, clients, ALSA users) with CPU, memory and
sparklines, plus streams, devices, server info and a DSP load graph.

**Layout**: resize panels with `(` `)` `{` `}` or by dragging panel borders with the mouse.

**Plumbing**: PulseAudio and PipeWire (via pipewire-pulse), no kernel modules, no root. Plays files too
(WAV natively; anything else through ffmpeg or the optional soundfile package).

## Test signals and easter eggs

All synthesized from scratch, so there are no licensing questions. They are cartoon-style approximations
and not recordings, but they have real spectral content, which is what makes them good EQ and FX test material.

```
daneq --bear | --lion | --cat | --dog | --wolf | --cow | --sheep | --duck | --bird | --frog
daneq --owl | --rooster | --horse | --elephant | --pig | --whale | --cricket | --zoo
daneq --cartoon        slide whistle, boing, bonk, xylophone, sad trombone, ta-da, record scratch
daneq --loudspeaker    speech-like babble through a bullhorn (try it with the Megaphone effect)
daneq --binaural --beat alpha --carrier 220     headphones recommended
daneq --dialup | --dtmf | --siren | --morse
daneq --tetris | --ode | --elise | --birthday   chiptune melodies (all public domain compositions)
daneq --pink | --white | --brown | --sweep | --music
daneq --list-demos
```

Binaural beats: the left and right ears get tones `beat` Hz apart. `--beat` takes a number or delta (2),
theta (6), alpha (10), beta (20), gamma (40) or schumann (7.83). The vectorscope shows the phase drifting.
This is a test signal, not a medical device.

### Public domain recordings

`daneq --list-clips` lists the built-in library, which downloads on first use into `~/.cache/daneq/clips`
(nothing is bundled in this repo):

```
daneq --clip moon       Apollo 11 "one small step" (NASA)
daneq --clip infamy     FDR, "a date which will live in infamy"
daneq --clip fdr        FDR, full 8 Dec 1941 address
daneq --clip jfk        JFK inaugural address
daneq --clip cuba       JFK Cuban Missile Crisis address
daneq --clip https://example.org/some.ogg      any URL
daneq --clip ~/Music/thing.flac                any file
```

These are works of the US government (public domain under 17 USC 105) hosted on Wikimedia Commons.
Add your own named clips in `~/.config/daneq/clips.json`:

```
{"mything": {"url": "https://.../file.ogg", "about": "what it is and why it is free to use"}}
```

Ogg and other compressed formats need ffmpeg, or `pip install "daneq[audio]"` on hosts without it.

## Install

You need Python 3.9+ and, for live audio, `pactl`, `parec` and `pacat`
(package `pulseaudio-utils`; on PipeWire systems install `pipewire-pulse`).

```
pipx install daneq                                  # from PyPI
pipx install git+https://github.com/fourzerosix/DanEQ   # from GitHub
docker run -it --rm ghcr.io/fourzerosix/daneq --demo --no-output   # Docker, no audio
```

From a clone: `scripts/install.sh` installs the audio tools and DanEQ in one go.

Rocky / RHEL 9: `sudo dnf install pulseaudio-utils python3-pip`, then `pip install --user daneq`.
Debian / Ubuntu: `sudo apt install pulseaudio-utils pipx`.

Docker with real audio (PulseAudio socket passthrough):

```
docker run -it --rm -v $XDG_RUNTIME_DIR/pulse:/run/pulse \
  -e PULSE_SERVER=unix:/run/pulse/native ghcr.io/fourzerosix/daneq
```

## Usage

```
daneq                      equalize everything playing on the system
daneq song.flac            play a file through the EQ
daneq --demo               built-in groove, plays through your default output
daneq --demo pink          pink noise: the clearest way to see the EQ working
daneq --demo sweep         20 Hz to 20 kHz sweep: watch the peak follow your curve
daneq --demo --no-output   visualize and EQ only, no audio device needed
daneq --bands 4            4 band layout
daneq --preset Rock --theme synthwave
daneq --export > daneq.apo.txt   save your curve as Equalizer APO text
daneq --list               list output sinks
daneq --restore            clean up after a crash (see below)
```

### How system mode works

```
apps -> [daneq null sink] -> monitor -> DanEQ (EQ + analyzer) -> your real output
```

DanEQ creates a virtual sink named `daneq`, makes it the default output, moves running
streams onto it, equalizes its monitor and plays the result to your original sink. Everything is
undone on exit (including SIGTERM and SIGHUP). If it is ever killed hard, run `daneq --restore`.
Volume keys keep working because they control the virtual sink.

Latency is roughly 2x `--latency` plus one block (about 80 ms by default), so lip sync on video
may need `--latency 15`.

## Keys

| Key | Action |
| --- | --- |
| Left / Right, h / l | select band |
| Up / Down, k / j | gain +/- 0.5 dB |
| PgUp / PgDn, K / J | gain +/- 3 dB |
| 0 | zero selected band |
| r | reset all bands and preamp |
| b | bypass (A/B compare) |
| p / P | next / previous preset |
| [ / ] | preamp -/+ 0.5 dB |
| m | mute |
| t | toggle spectrum tilt (3 dB/oct) |
| , / . | spectrum sensitivity |
| a | auto headroom |
| v | cycle view (spectrum, waterfall, scope) |
| c | cycle color theme |
| e | export Equalizer APO text |
| ? | help |
| f | FX rack (Tab or 1-9 pick effect, o toggles, arrows adjust knobs, b bypasses the rack) |
| v / V | next / previous view |
| g | spectrum bar style |
| c / C | next / previous theme |
| n | nerd mode |
| ( ) / { } | resize panels |
| s | save settings |
| q | quit (settings are saved automatically) |

Settings live in `~/.config/daneq/config.json`.

## ThinLinc demo

Inside a ThinLinc session, use a 256 color terminal and a UTF-8 locale, then:

```
export TERM=xterm-256color LANG=en_US.UTF-8
daneq --demo pink --no-output     # works even if the node has no audio path
daneq --demo                      # plays through the session's ThinLinc audio sink
daneq                             # equalizes everything in the session
```

Sound over ThinLinc needs audio enabled in the client. Terminal size should be at least 80x24;
bigger is better. Boost band 6 (1k) on `--demo pink` and watch the spectrum and response curve move together.

See `PUBLISHING.md` for the GitHub, PyPI and GHCR steps, and `scripts/demo.sh` for a quick tour.

## Development

```
pip install -e ".[dev]"
pytest
daneq --selftest
```

Releases: push a `vX.Y.Z` tag. The workflow publishes to PyPI (trusted publishing) and to
`ghcr.io/fourzerosix/daneq`.

## Troubleshooting

- Boxes or braille look wrong: use a UTF-8 locale and a font with braille glyphs.
- Colors are flat: set `TERM=xterm-256color`.
- "pactl not found": install `pulseaudio-utils`.
- No sound after a crash: `daneq --restore`.
- Small clicks when you drag a fader fast: filter coefficients change between blocks; this is expected.

## License

MIT

---

```text

██████╗  █████╗ ███╗   ██╗███████╗ ██████╗          ________________________
██╔══██╗██╔══██╗████╗  ██║██╔════╝██╔═══██╗         | ██ ██ ██ ██ ██ ██ |2||
██║  ██║███████║██╔██╗ ██║█████╗  ██║   ██║         | ██ ██ ██ ██ ██ ██ |0||
██║  ██║██╔══██║██║╚██╗██║██╔══╝  ██║   ██║         | ██ ██ R.I.P ██ ██ |2||
██████╔╝██║  ██║██║ ╚████║███████╗╚██████╔╝         | ██ ██ D.J.E ██ ██ |6||
╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═══╝╚══════╝ ╚═══██╗          | ██ ██ ██ ██ ██ ██ |J||
  |                |                  ╚═══╝         | ██ ██ ██ ██ ██ ██ |B||
╭─┤Spectrum post-EQ├────────────────────────────────┤band 6/10: 1kHz +6.0dB├─╮
│ -10  braille spectrum, 2 bars per cell, peak-hold caps, dB scale             │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─┤Equalizer 10-band├──╮╭─┤Response├──────────────────────┤preamp +0.0dB├─╮
│ faders (mouse + keys) ││ exact filter curve, drawn in braille            │
│                       │╭─┤Levels├───────────────────────────────┤dBFS├────╮
╰───────────────────────╯╰────────────────────────────────────────────────────╯
```
