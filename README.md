![DanEQ](https://raw.githubusercontent.com/fourzerosix/DanEQ/main/assets/images/daneq-logo-full.jpg)

---

# DanEQ

[![CI](https://github.com/fourzerosix/DanEQ/actions/workflows/ci.yml/badge.svg)](https://github.com/fourzerosix/DanEQ/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/daneq)](https://pypi.org/project/daneq/)
[![Docker](https://img.shields.io/docker/v/fourzerosix/daneq?sort=semver&label=docker)](https://hub.docker.com/r/fourzerosix/daneq)
[![Docs](https://img.shields.io/badge/docs-github%20pages-blue)](https://fourzerosix.github.io/DanEQ/)
[![License: GPL-3.0](https://img.shields.io/badge/license-GPL--3.0-blue)](LICENSE)

A btop-style terminal **equalizer, effects rack and audio visualizer** for Linux and macOS.
It does not just draw pretty bars: it sits in the audio path, so the faders you move change what you hear,
and `daneq --selftest` proves the filters match the curve on screen.

```
╭─┤Spectrum post-EQ├──────────────────────────────────┤braille  band 6/10: 1kHz +6.0dB├─╮
│ -10  braille spectrum, 2 bars per cell, peak-hold caps, gradient colors, dB scale       │
╰─────────────────────────────────────────────────────────────────────────────────────────╯
╭─┤Equalizer 10-band├──╮╭─┤Response├──────────────────────────────────────┤preamp +0.0dB├─╮
│ faders (keys + mouse) ││ exact filter curve with shaded boost/cut areas                  │
│                       │╭─┤Levels├──────────────────────────────────────────────┤dBFS├────╮
╰───────────────────────╯╰─────────────────────────────────────────────────────────────────╯
```

## Contents

Docs site: https://fourzerosix.github.io/DanEQ/

1. [What you get](#what-you-get)
2. [Platform support](#platform-support)
3. [Quick start](#quick-start)
4. [Install](#install) - Linux, macOS, iPhone/iPad, ThinLinc, Docker, dependencies, uninstall
5. [Usage examples](#usage-examples)
6. [Playing files: transport, tempo, pitch and screw](#playing-files-transport-tempo-pitch-and-screw)
7. [Keys, mouse and the Esc menu](#keys-mouse-and-the-esc-menu)
8. [Effects rack](#effects-rack)
9. [Visualizations, bar styles, themes](#visualizations-bar-styles-themes)
10. [Test signals and easter eggs](#test-signals-and-easter-eggs)
11. [Public domain clips](#public-domain-clips)
12. [Nerd mode](#nerd-mode)
13. [Files and settings](#files-and-settings)
14. [How it works](#how-it-works)
15. [Command line reference](#command-line-reference)
16. [Troubleshooting](#troubleshooting)
17. [Development and testing](#development-and-testing)
18. [Publishing](#publishing)
19. [FAQ and roadmap](#faq-and-roadmap)

## What you get

- **Equalizer**: 4, 6, 8 or 10 bands (`--bands`), +/-12 dB per band, preamp, bypass for A/B, mute, 8 presets,
  auto headroom, RBJ biquad filters in real time. Export your curve as Equalizer APO / EasyEffects text.
- **Effects rack**: compressor, overdrive, bitcrusher, megaphone, phaser, flanger, chorus, tremolo, echo,
  reverb and stereo widener, each with braille rotary knobs.
- **15 views**: spectrum (6 bar styles), waterfall, scope, vectorscope, radial, spinning vinyl record,
  reel-to-reel tape deck, fire, starfield, ripples, matrix rain, tunnel, plasma, aurora, analog VU meters.
  30 color themes, with btop-style theme background on/off (transparency). 60 fps.
- **File player**: open files and folders from inside the app (or on the command line), playlists, play/pause,
  previous/next, seek, repeat, shuffle, with every EQ band, effect and visual working on the music.
- **Pitch, tempo and SCREW** knobs for file playback: change tempo without pitch, pitch without tempo, or slow both
  together like a record (the SCREW knob is a styrofoam cup, a nod to DJ Screw).
- **Nerd mode**: btop-style audio process, stream and device monitor.
- **Esc menu** like btop, resizable panels (keys and mouse drag), full mouse support.
- **Test signals**: 17 synthesized animals, cartoon sound effects, a bullhorn loudspeaker, binaural beats,
  dial-up modem, touch tones, morse, noise colors, and 12 public domain tunes including Amazing Grace.
- **Real public domain recordings** (Apollo 11, FDR, JFK) fetched on demand.
- **No root, no kernel modules.** PulseAudio and PipeWire on Linux; PortAudio plus a loopback driver on macOS.

## Platform support

| Platform | Status | Audio path |
| --- | --- | --- |
| Linux (Ubuntu, Kubuntu, Debian, Rocky/RHEL 9, Fedora, Arch) | Tested | PulseAudio or PipeWire via `pactl`, `parec`, `pacat` |
| Linux over ThinLinc | Tested | The session's PulseAudio, forwarded to your client |
| Docker (Linux) | Provided | Pulse socket passthrough, or `--no-output` |
| macOS 12+ (Intel and Apple Silicon) | New, needs testing on a real Mac | PortAudio (`sounddevice`) plus a free loopback driver (BlackHole) |
| Windows | Not supported yet | Would need a WASAPI loopback backend (see roadmap) |
| iPhone / iPad | Not possible natively | See [iPhone and iPad](#iphone-and-ipad) for what does work |

Everything that does not need live system audio (test signals, files, all visuals, effects, `--no-output`)
works on any platform that runs Python 3.9+ with a UTF-8, 256-color terminal at least 80x24.

## Quick start

```bash
git clone https://github.com/fourzerosix/DanEQ.git && cd DanEQ
scripts/install.sh                  # Linux or macOS; creates a private virtualenv and the `daneq` command
daneq --selftest                    # headless proof that the DSP is accurate
daneq --demo pink --no-output       # visual demo, no sound card needed
daneq                               # equalize everything playing on this machine
```

## Install

### Linux

**One command** (Debian/Ubuntu/Kubuntu, Fedora, Rocky/RHEL, Arch, openSUSE): `scripts/install.sh`.
It installs the system tools, builds a virtualenv in `~/.local/share/daneq/venv`, links
`~/.local/bin/daneq` and runs the self-test. Undo with `scripts/install.sh --uninstall`.

**Manual**, per distribution:

| Distribution | System packages | Then |
| --- | --- | --- |
| Debian, Ubuntu, Kubuntu | `sudo apt install pulseaudio-utils python3-venv python3-pip` (optional: `ffmpeg`) | `pipx install .` or the venv steps below |
| Fedora | `sudo dnf install pulseaudio-utils python3-pip` | same |
| Rocky / RHEL / Alma 9 | `sudo dnf install pulseaudio-utils python3-pip` (ffmpeg needs EPEL + RPM Fusion) | same |
| Arch | `sudo pacman -S libpulse python python-pip` | same |

PipeWire systems already provide `pactl`/`parec`/`pacat` through `pipewire-pulse`; the package names above
(`pulseaudio-utils`, `libpulse`) only supply the client tools.

```bash
python3 -m venv ~/.local/share/daneq/venv
~/.local/share/daneq/venv/bin/pip install --upgrade pip
~/.local/share/daneq/venv/bin/pip install ".[audio]"        # or: pip install daneq[audio]  once it is on PyPI
ln -s ~/.local/share/daneq/venv/bin/daneq ~/.local/bin/daneq
```

From other sources:

```bash
pipx install git+https://github.com/fourzerosix/DanEQ     # straight from GitHub
pipx install daneq                                          # from PyPI (after the first release)
docker run -it --rm fourzerosix/daneq                      # Docker Hub: built-in demo, no audio device needed
docker run -it --rm ghcr.io/fourzerosix/daneq --zoo --fx reverb --no-output     # same image from GHCR
```

Docker with real audio, passing the host's PulseAudio/PipeWire socket:

```bash
docker run -it --rm -v "$XDG_RUNTIME_DIR/pulse:/run/pulse" -e PULSE_SERVER=unix:/run/pulse/native \
  fourzerosix/daneq --demo
```

### macOS

macOS has no PulseAudio and, by design, gives apps no way to tap the system mix. System-wide EQ therefore
needs a free virtual loopback device. DanEQ uses **BlackHole**; the rest is automatic.

```
apps  ->  [BlackHole 2ch = system output]  ->  DanEQ (EQ + effects + visuals)  ->  your real speakers/headphones
```

**1. Install** (Terminal.app or iTerm2):

```bash
git clone https://github.com/fourzerosix/DanEQ.git && cd DanEQ
scripts/install.sh            # offers to install Homebrew Python, ffmpeg, BlackHole and switchaudio-osx
```

Or by hand: `brew install python ffmpeg switchaudio-osx && brew install --cask blackhole-2ch`
then `python3 -m venv ~/.local/share/daneq/venv && ~/.local/share/daneq/venv/bin/pip install ".[mac]"`.
Homebrew Python is recommended: the Python that ships with the Xcode command line tools is old (3.9, pip 21)
and its curses handles Unicode poorly.

**2. Allow microphone access.** Capturing BlackHole counts as recording, so the first run triggers a prompt;
approve it, or enable your terminal under System Settings > Privacy & Security > Microphone.

**3. Match sample rates (optional but best).** Open *Audio MIDI Setup* and set BlackHole 2ch and your real
output to the same rate, normally 48000 Hz.

**4. Run it.**

```bash
daneq --list-devices          # shows every device and marks virtual ones
daneq                         # captures BlackHole, plays to your system output
daneq --output "External"     # pick another real output by name fragment
daneq --input "BlackHole 2ch" --output "MacBook Pro Speakers"
```

With `switchaudio-osx` installed DanEQ switches the system output to BlackHole for you and restores it on exit.
Without it, set System Settings > Sound > Output to **BlackHole 2ch** before starting and back afterwards.

Limits on macOS: BlackHole has no volume control, so the keyboard volume keys do nothing while it is the output
(set your speaker volume first, or use per-app volume). Live system audio is new and untested by the author
on a real Mac: run `daneq --list-devices` first and open an issue with its output if something is off.
Files, test signals and all visuals do not need BlackHole at all: `daneq --demo pink`, `daneq song.mp3`.

### iPhone and iPad

DanEQ cannot run natively on iOS or iPadOS: there is no system-wide audio tap for third-party apps, no
curses terminal in the sandbox, and NumPy/SciPy are not available in the common on-device Python apps.
What does work:

- **SSH into a machine that runs DanEQ** (Blink Shell, Termius, Prompt, or any iOS SSH client). Run
  `daneq` inside `tmux` on the remote Mac or Linux box; the interface, mouse and all visuals work over SSH.
  The audio being equalized is the remote machine's, not the phone's.
- **ThinLinc or other remote desktop** into a Linux box and use the terminal there (audio is forwarded by
  ThinLinc if enabled in the client).
- A native iOS version would be a separate Swift project (an AUv3 audio unit or an AVAudioEngine app that
  equalizes its own playback). The DSP here (RBJ biquads) ports directly; it is on the roadmap, not in this repo.

### ThinLinc and other remote sessions

Inside the session, use a 256-color terminal and a UTF-8 locale:

```bash
export TERM=xterm-256color LANG=en_US.UTF-8
daneq --demo pink --no-output       # works even if the node has no audio path
daneq --demo                        # plays through the session's ThinLinc audio sink
daneq                               # equalizes everything playing in the session
```

Audio must be enabled in the ThinLinc client. If the session dies uncleanly, `daneq --restore` removes the
virtual sink and resets the default output.

### Dependencies at a glance

| What | Why | Needed for |
| --- | --- | --- |
| Python 3.9+ | runtime | everything |
| `numpy`, `scipy` | DSP | everything (installed automatically) |
| `pactl`, `parec`, `pacat` (`pulseaudio-utils`, or `pipewire-pulse`) | Linux audio in/out | live audio on Linux |
| `sounddevice` (PortAudio; wheels bundle it on macOS) | macOS audio in/out | live audio on macOS (installed automatically there) |
| BlackHole 2ch | virtual loopback | system-wide EQ on macOS |
| `switchaudio-osx` | automatic output switching | optional, macOS |
| `ffmpeg` | decode mp3, ogg, flac, m4a | optional; `pip install daneq[audio]` (soundfile) covers ogg/flac/wav without it |
| UTF-8 locale, 256-color terminal, 80x24 or larger | braille UI | everything |

### Uninstall

`scripts/install.sh --uninstall`, or `pipx uninstall daneq`. Settings stay in `~/.config/daneq`; delete that
folder to remove them. On macOS also `brew uninstall --cask blackhole-2ch` if you no longer want it.

## Usage examples

```bash
# --- live system audio ---------------------------------------------------------------------------
daneq                                   # all apps through the EQ (Linux: virtual sink; macOS: BlackHole)
daneq --bands 4                         # 4 band layout (also 6, 8, 10)
daneq --preset Rock --theme synthwave   # start with a preset and a theme
daneq --fx reverb,echo --view vinyl     # effects on from the start, begin in the vinyl view
daneq --latency 15                      # lower latency (less buffering) for video
daneq --sink alsa_output.pci-0000_00_1f.3.analog-stereo      # pick the Linux output explicitly
daneq --restore                         # clean up after a crash (Linux)

# --- files ---------------------------------------------------------------------------------------
daneq song.flac                         # play a file through the EQ
daneq --loop loop.wav                   # loop it
daneq --no-output song.mp3              # visualize and EQ without playing (silent preview)

# --- measurement and EQ testing ------------------------------------------------------------------
daneq --selftest                        # prove accuracy: real tones vs the displayed response, all layouts
daneq --pink --no-output                # pink noise: boost a band and watch the spectrum bulge
daneq --sweep                           # 20 Hz to 20 kHz sweep: the moving peak follows your curve
daneq --export > my-curve.apo.txt       # save the curve as Equalizer APO / EasyEffects text
daneq --list-presets                    # Flat, Bass boost, Treble boost, Vocal, Loudness, Rock, ...

# --- fun ------------------------------------------------------------------------------------------
daneq --zoo --fx reverb                 # every animal, with reverb
daneq --lion --theme fire --view fire   # roar, rendered as flames
daneq --binaural --beat alpha --view vectorscope      # headphones: watch the phase drift
daneq --loudspeaker --fx megaphone,echo # bullhorn through a canyon
daneq --grace --view vinyl --theme gold # Amazing Grace on a spinning record
daneq --tetris --view reel-to-reel      # Korobeiniki on tape
daneq --clip moon --view scope          # Apollo 11, one small step
daneq --cartoon --style mirror          # slide whistles with a mirrored spectrum

# --- engineering ---------------------------------------------------------------------------------
daneq --nerd                            # start in nerd mode (audio processes, streams, devices)
daneq --list-devices                    # macOS / PortAudio: list audio devices
daneq --fps 30                          # lighter on slow remote sessions
daneq --no-mouse                        # if your terminal mangles mouse reporting
```

## Playing files: transport, tempo, pitch and screw

Give DanEQ files, folders or playlists, or press `O` inside the app (also in the Esc menu under *Open file...*):

```bash
daneq song.flac                       # one file
daneq ~/Music/Album/                  # a folder (add --recursive for sub-folders)
daneq a.mp3 b.ogg mixtape.m3u         # any mix of files and playlists
daneq --shuffle --repeat all ~/Music  # shuffle the folder forever
daneq --once song.mp3                 # quit when it ends instead of staying open
daneq --screw 0.75 beat.wav           # start slowed to 75 percent, pitch and tempo together
daneq --tempo 120 --pitch -2 song.mp3 # 20 percent faster, two semitones lower
```

A transport bar appears under the header while a file is loaded: `|<  <<  [||]  >>  >|`, a time display, a seek bar,
the track number and the shuffle and repeat switches. Everything is clickable.

| Key | Action |
| --- | --- |
| `O` | open the file browser |
| Space | play / pause |
| `z` / `x` | previous / next track (previous restarts the track if you are more than 3 seconds in) |
| `<` / `>` | seek back / forward 5 seconds |
| `R` | repeat: off, all, one |
| `S` | shuffle on/off |

**File browser**: Up/Down move, Enter opens a folder or plays the file (the whole folder becomes the playlist, starting
at that file), Space marks files to build your own playlist, Backspace or Left goes up, `~` home, `.` shows hidden files,
Esc closes. It remembers the last folder. You can also open a file while a test signal or live audio is running and
return with *Back to live input* in the Esc menu.

**Speed controls**: press `f`, then Shift-Tab (or Tab until the last tab) for the **Speed** page.

| Knob | What it does |
| --- | --- |
| Pitch (-12 to +12 semitones) | changes pitch, keeps tempo |
| Tempo (50 to 200 percent) | changes tempo, keeps pitch |
| SCREW (0.50x to 1.25x) | slows or speeds pitch and tempo together, like a record; the cup fills as you slow it down |

Pitch and tempo use WSOLA time stretching with a cubic resampler; with all three at neutral the audio is bit-exact.
Moving the knobs during playback is click-free. These controls apply to file playback, not to live system audio.

## Keys, mouse and the Esc menu

Press **Esc** for a btop-style menu (view, bar style, theme, EQ preset, FX rack, nerd mode, auto headroom,
bypass, save, export, help, about, quit). Arrow keys or `j`/`k` move, Enter or Right opens, Esc or Left goes back,
the mouse works too. Press `?` for an in-app key list.

| Key | Action |
| --- | --- |
| Left / Right, `h` / `l` | select band (FX mode: knob) |
| Up / Down, `k` / `j` | gain +/- 0.5 dB (FX mode: knob fine) |
| PgUp / PgDn, `K` / `J` | gain +/- 3 dB (FX mode: knob coarse) |
| `0` | zero the band (FX mode: reset the knob) |
| `r` | reset all bands and preamp (FX mode: reset the effect) |
| `b` | bypass the EQ for A/B (FX mode: bypass the whole rack) |
| `p` / `P` | next / previous EQ preset |
| `[` / `]` | preamp -/+ 0.5 dB |
| `a` | auto headroom: preamp so boosts cannot clip |
| `f` | toggle the FX rack |
| Tab, `1`-`9` | FX: next effect / pick effect |
| `o` or Space | FX: effect on/off |
| `v` / `V` | next / previous view |
| `g` | spectrum bar style |
| `c` / `C` | next / previous theme |
| `t`, `,` / `.` | spectrum tilt, sensitivity |
| `(` `)` | bottom panel shorter / taller |
| `{` `}` | fader columns narrower / wider |
| `n` | nerd mode |
| `m` | mute |
| `e` | export Equalizer APO text |
| `B` | theme background true/false (transparent when false) |
| `s` | save settings |
| `?` | help |
| `q` | quit (settings are saved automatically) |

Mouse: click or drag a fader, scroll the wheel over a band or knob, double click a fader to zero it, click FX tabs,
drag the panel borders to resize.

## Effects rack

Press `f`. Effects run in this order after the EQ: compressor, overdrive, bitcrusher, megaphone, phaser,
flanger, chorus, tremolo, echo, reverb, stereo widener. Switch effects on with `o`, turn knobs with the arrows.
Settings are saved with the rest of your config.

| Effect | `--fx` name | What it does | Knobs |
| --- | --- | --- | --- |
| Compressor | `comp` | Feed-forward compressor, linked stereo | Thresh -40..0dB (default -18); Ratio 1..20:1 (default 4); Attack 1..100ms (default 8); Release 20..1000ms (default 150); Makeup 0..24dB (default 3); Mix 0..1 (default 1) |
| Overdrive | `drive` | Tanh saturation with tone control | Drive 0..40dB (default 12); Tone 500..12000Hz (default 4500); Level -24..6dB (default -6); Mix 0..1 (default 1) |
| Bitcrusher | `crush` | Bit depth and sample rate reduction | Bits 3..16 (default 8); Downsmp 1..32x (default 4); Mix 0..1 (default 1) |
| Megaphone | `mega` | Bullhorn / PA loudspeaker with slapback | Drive 0..30dB (default 10); Honk 0..12dB (default 6); Slap 0..1 (default 0.25); Mix 0..1 (default 1) |
| Phaser | `phase` | All-pass notch sweep (feedback is chunk-delayed) | Rate 0.05..5Hz (default 0.4); Depth 0..1 (default 0.7); Feedback 0..0.9 (default 0.4); Stages 2..8 (default 4); Mix 0..1 (default 0.5) |
| Flanger | `flang` | Swept comb filter with feedback | Rate 0.05..5Hz (default 0.25); Depth 0..1 (default 0.7); Delay 0.8..8ms (default 2.5); Feedback -0.9..0.9 (default 0.5); Mix 0..1 (default 0.5) |
| Chorus | `chorus` | Detuned modulated delay, stereo | Rate 0.1..5Hz (default 0.8); Depth 0..1 (default 0.5); Delay 10..40ms (default 20); Mix 0..1 (default 0.45) |
| Tremolo | `trem` | Amplitude LFO; stereo phase turns it into an auto-pan | Rate 0.5..20Hz (default 5); Depth 0..1 (default 0.6); Stereo 0..1 (default 0) |
| Echo | `echo` | Tape-style delay with filtered feedback | Time 60..1000ms (default 350); Feedback 0..0.95 (default 0.4); Tone 500..12000Hz (default 5000); Mix 0..1 (default 0.35) |
| Reverb | `verb` | Freeverb-style room: 8 combs + 4 all-passes per side | Size 0..1 (default 0.6); Damping 0..1 (default 0.5); Width 0..1 (default 1); Mix 0..1 (default 0.25) |
| Stereo Widener | `wide` | Mid/side width: 0 mono, 1 unchanged, 2 extra wide | Width 0..2 (default 1.4) |

Notes: the phaser feedback is applied once per 32-sample chunk (an approximation); the overdrive is not
oversampled, so extreme drive can alias.

## Visualizations, bar styles, themes

**Views** (`v` / `V` or `--view`): spectrum, waterfall, scope, vectorscope, radial, vinyl, reel-to-reel, fire,
starfield, ripples, matrix, tunnel, plasma, aurora, VU meters. The audio-reactive ones respond to bass, mid and treble separately.

**Bar styles** (`g` or `--style`): braille, line, mirror, dots, blocks, ascii.

**Themes** (`c` / `C` or `--theme`): `classic`, `ice`, `fire`, `synthwave`, `mono`, `ocean`, `forest`, `sunset`, `vaporwave`, `matrix`, `gold`, `lava`, `aurora`, `candy`, `nord`, `dracula`, `gruvbox`, `cyberpunk`, `rainbow`, `thermal`, `tokyonight`, `solarized`, `monokai`, `catppuccin`, `everforest`, `rosepine`, `kanagawa`, `sakura`, `toxic`, `bubblegum`.

**Theme background**: like btop's `theme_background`, each theme paints its own background color. Press `B`, use the Esc menu (*Theme background true/false*) or start with `--transparent` to let your terminal's own background or transparency show through. The choice is saved.

**EQ presets**: `Flat`, `Bass boost`, `Treble boost`, `Vocal`, `Loudness`, `Rock`, `Electronic`, `Classical`.

**Layout**: `(` `)` change the bottom panel height, `{` `}` change fader width, or drag the borders. The spectrum
uses a multi-resolution FFT (long window for bass, short for treble); `,` and `.` change sensitivity, `t` toggles tilt.

## Test signals and easter eggs

All of these are synthesized from scratch, so there are no licensing questions. They are cartoon-style
approximations rather than recordings, but they have real spectral content, which is what makes them good for
EQ and effects testing. `daneq --list-demos` prints the same list.

**Animals**

| Flag | What you get |
| --- | --- |
| `--dog` | synthesized dog |
| `--cat` | synthesized cat |
| `--lion` | synthesized lion |
| `--bear` | synthesized bear |
| `--wolf` | synthesized wolf |
| `--cow` | synthesized cow |
| `--sheep` | synthesized sheep |
| `--duck` | synthesized duck |
| `--bird` | synthesized bird |
| `--frog` | synthesized frog |
| `--owl` | synthesized owl |
| `--rooster` | synthesized rooster |
| `--horse` | synthesized horse |
| `--elephant` | synthesized elephant |
| `--pig` | synthesized pig |
| `--whale` | synthesized whale |
| `--cricket` | synthesized cricket |
| `--zoo` | every animal in turn |

**Comedy and nostalgia**

| Flag | What you get |
| --- | --- |
| `--cartoon` | slide whistle, boing, bonk, sad trombone and friends |
| `--loudspeaker` | speech-like babble through a bullhorn |
| `--dialup` | 56k modem handshake (impressionistic) |
| `--dtmf` | touch tones |
| `--siren` | wail and yelp |
| `--morse` | DANEQ in morse code |

**Public domain tunes (chiptune)**

| Flag | What you get |
| --- | --- |
| `--grace` | Amazing Grace (NEW BRITAIN, public domain), chiptune |
| `--twinkle` | Twinkle Twinkle Little Star |
| `--row` | Row, Row, Row Your Boat |
| `--jingle` | Jingle Bells (1857) |
| `--silentnight` | Silent Night (1818) |
| `--yankee` | Yankee Doodle |
| `--susanna` | Oh! Susanna (Foster, 1848) |
| `--canon` | Pachelbel's Canon, main melody |
| `--tetris` | Korobeiniki (public domain folk tune) in chiptune |
| `--ode` | Ode to Joy, chiptune |
| `--elise` | Fur Elise, chiptune |
| `--birthday` | Happy Birthday, chiptune |

**Test and measurement**

| Flag | What you get |
| --- | --- |
| `--pink` | pink noise (best EQ test) |
| `--white` | white noise |
| `--brown` | brown noise |
| `--sweep` | 20 Hz to 20 kHz log sweep |
| `--binaural` | binaural beat (headphones; --beat HZ|alpha|theta..., --carrier HZ) |
| `--music` | built-in groove with drums, bass and arp |

Binaural beats: the left and right ears get tones `--beat` Hz apart around `--carrier`. `--beat` takes a number or
`delta` (2), `theta` (6), `alpha` (10), `beta` (20), `gamma` (40) or `schumann` (7.83). Use headphones; the beat
exists only in your head. This is a test signal, not a medical device.

"You Are My Sunshine" is not included because it is still under copyright in the United States.

## Public domain clips

Nothing is bundled. `daneq --list-clips` shows a small library that downloads on first use into
`~/.cache/daneq/clips`:

```bash
daneq --clip moon       # Apollo 11, one small step (NASA)
daneq --clip infamy     # FDR, "a date which will live in infamy"
daneq --clip fdr        # FDR, the full 8 Dec 1941 address
daneq --clip jfk        # JFK inaugural address
daneq --clip cuba       # JFK Cuban Missile Crisis address
daneq --clip jazzsinger # The Jazz Singer (1927): "You ain't heard nothin' yet" (first talkie line)
daneq --clip barbra     # Night of the Living Dead (1968): "They're coming to get you, Barbra!"
daneq --clip farmhouse  # Night of the Living Dead: "They know we're in here now"
daneq --clip fire       # Night of the Living Dead: "They're afraid of fire"
daneq --clip https://example.org/some.ogg      # any URL
daneq --clip ~/Music/thing.flac                # any local file
```

The speeches are works of the US government (public domain under 17 USC 105). The Jazz Singer (1927) entered the US
public domain in 2023, and Night of the Living Dead (1968) was released without a copyright notice, so both are
public domain in the US. All are hosted on Wikimedia Commons. The Night of the Living Dead clips are cut out of the
full film on your machine with ffmpeg (only that part is downloaded) and cached as a small WAV; they need ffmpeg.
The cut points come from the film's subtitle file on Commons; if one is off by a few seconds, edit `start` in `clips.json`. Add your own
named clips in `~/.config/daneq/clips.json`:

```json
{"mything": {"url": "https://.../file.ogg", "about": "what it is and why it is free to use"}}
```

Ogg and other compressed formats need ffmpeg, or `pip install "daneq[audio]"` where ffmpeg is unavailable.

## Nerd mode

`n` or `--nerd`. Panels: DanEQ engine stats and a DSP load graph, devices (sinks, sources, ALSA hardware that is
running), audio processes with CPU, memory and braille sparklines (servers such as pipewire/pulseaudio/wireplumber,
clients that own streams, anything holding `/dev/snd`), and live PulseAudio/PipeWire streams with volume, format and
latency. `Up`/`Down` select, `o` cycles the sort (cpu, mem, pid, name). On macOS it shows `coreaudiod`, audio
tools and the PortAudio device list. Without `pactl` it still shows processes.

## Files and settings

| Path | What |
| --- | --- |
| `~/.config/daneq/config.json` | EQ gains per layout, preamp, FX knobs, theme, view, style, layout sizes |
| `~/.config/daneq/daneq-10band.apo.txt` | written by the `e` key |
| `~/.config/daneq/clips.json` | your own named clips |
| `~/.cache/daneq/clips/` | downloaded public domain clips |
| `~/.local/share/daneq/venv/` | the virtualenv made by `scripts/install.sh` |

`XDG_CONFIG_HOME` and `XDG_CACHE_HOME` are honored.

## How it works

```
Linux:   apps -> [daneq null sink] -> monitor -> parec -> numpy/scipy EQ + FX -> pacat -> your real output
macOS:   apps -> [BlackHole 2ch]   ------------> PortAudio in -> EQ + FX -> PortAudio out -> real output
files, demos:  decoder or generator -> EQ + FX -> output (or a silent timed sink with --no-output)
                                        |
                                        +-> analyzer tap -> spectrum / visuals / meters
```

On Linux DanEQ creates a virtual sink named `daneq`, makes it the default output, moves running streams onto it,
equalizes its monitor and plays the result to the original sink. Everything is undone on exit, including on
SIGTERM and SIGHUP. Latency is roughly twice `--latency` plus one 1024-frame block (about 80 ms by default).

## Command line reference

```text
usage: daneq [-h] [--demo [NAME]] [--beat HZ|NAME] [--carrier HZ]
             [--clip NAME|PATH|URL] [--list-clips] [--list-demos]
             [--backend {auto,pulse,portaudio}] [--input DEVICE]
             [--output DEVICE] [--list-devices] [--no-output] [--sink NAME]
             [--capture SOURCE] [--rate RATE] [--latency MS] [--loop]
             [--repeat {off,all,one}] [--shuffle] [--once] [--recursive]
             [--pitch ST] [--tempo PCT] [--screw RATIO] [--bands {4,6,8,10}]
             [--preset {Flat,Bass boost,Treble boost,Vocal,Loudness,Rock,Electronic,Classical}]
             [--theme {classic,ice,fire,synthwave,mono,ocean,forest,sunset,vaporwave,matrix,gold,lava,aurora,candy,nord,dracula,gruvbox,cyberpunk,rainbow,thermal,tokyonight,solarized,monokai,catppuccin,everforest,rosepine,kanagawa,sakura,toxic,bubblegum}]
             [--view {spectrum,waterfall,scope,vectorscope,radial,vinyl,reel-to-reel,fire,starfield,ripples,matrix,tunnel,plasma,aurora,vu-meters}]
             [--style {braille,line,mirror,dots,blocks,ascii}] [--fx LIST]
             [--fps N] [--nerd] [--transparent] [--no-mouse] [--list]
             [--export] [--list-presets] [--restore] [--selftest] [--version]
             [FILE ...]

DanEQ: a btop-style terminal equalizer, effects rack and audio visualizer.

positional arguments:
  FILE                  audio files, folders or .m3u playlists to play through
                        DanEQ (WAV, FLAC, OGG, MP3, M4A, ...)

options:
  -h, --help            show this help message and exit

test signals and easter eggs:
  --demo [NAME]         built-in signal (see --list-demos); default: music
  --beat HZ|NAME        binaural beat frequency or
                        delta/theta/alpha/beta/gamma/schumann (default 10)
  --carrier HZ          binaural carrier (default 220)
  --clip NAME|PATH|URL  play a clip from the clip library, a local file or a
                        URL
  --list-clips          list the clip library and exit
  --list-demos          list all built-in signals and exit

audio routing:
  --backend {auto,pulse,portaudio}
                        audio backend: pulse (Linux, default there) or
                        portaudio (macOS default)
  --input DEVICE        portaudio: capture device name or number (default:
                        BlackHole/loopback)
  --output DEVICE       portaudio: output device name or number (default:
                        system output)
  --list-devices        portaudio: list audio devices and exit
  --no-output           do not play audio, just process and visualize
  --sink NAME           output sink (default: current default sink)
  --capture SOURCE      capture from this source instead of the virtual sink
  --rate RATE           sample rate (default 48000)
  --latency MS          stream latency in ms (default 30)
  --loop                same as --repeat all

playback (files and folders):
  --repeat {off,all,one}
                        repeat mode (default off)
  --shuffle             shuffle the playlist
  --once                quit when the playlist ends instead of staying open
  --recursive           include sub-folders when a folder is given
  --pitch ST            pitch shift in semitones, -12 to 12 (tempo unchanged)
  --tempo PCT           tempo in percent, 50 to 200 (pitch unchanged)
  --screw RATIO         screw mode: slow pitch and tempo together like a
                        record, 0.5 to 1.25 (try 0.75)

interface:
  --bands {4,6,8,10}    number of EQ bands (default 10)
  --preset {Flat,Bass boost,Treble boost,Vocal,Loudness,Rock,Electronic,Classical}
                        start with this EQ preset
  --theme {classic,ice,fire,synthwave,mono,ocean,forest,sunset,vaporwave,matrix,gold,lava,aurora,candy,nord,dracula,gruvbox,cyberpunk,rainbow,thermal,tokyonight,solarized,monokai,catppuccin,everforest,rosepine,kanagawa,sakura,toxic,bubblegum}
                        color theme
  --view {spectrum,waterfall,scope,vectorscope,radial,vinyl,reel-to-reel,fire,starfield,ripples,matrix,tunnel,plasma,aurora,vu-meters}
                        start in this view
  --style {braille,line,mirror,dots,blocks,ascii}
                        spectrum bar style
  --fx LIST             enable effects at start, e.g. reverb,echo,comp
  --fps N               target frame rate (default 60)
  --nerd                start in nerd mode (audio processes and streams)
  --transparent         do not paint the theme background (use the terminal's
                        own)
  --no-mouse            disable mouse support

maintenance:
  --list                list output sinks and exit
  --export              print saved settings as Equalizer APO text and exit
  --list-presets        list EQ presets and exit
  --restore             remove a leftover virtual sink and fix the default
                        sink
  --selftest            verify the DSP against its analytic response and exit
  --version             show program's version number and exit

With no FILE, --demo or sound shortcut, DanEQ equalizes all system audio via a
virtual sink.
```

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| Boxes or braille look broken | Use a UTF-8 locale (`LANG=en_US.UTF-8`) and a font with braille glyphs |
| Colors are flat | `export TERM=xterm-256color` |
| "pactl/parec/pacat not found" | Linux: install `pulseaudio-utils` (works with PipeWire) |
| No sound after a crash (Linux) | `daneq --restore` |
| Sound is delayed against video | `--latency 15` |
| Tiny clicks when dragging a fader fast | Expected: coefficients change between blocks |
| macOS: "no loopback capture device found" | Install BlackHole (`brew install --cask blackhole-2ch`), then `daneq --list-devices` |
| macOS: silence | Terminal needs Microphone permission; check System Settings > Privacy & Security |
| macOS: garbled box characters | Use Homebrew Python and iTerm2 or Terminal.app with UTF-8 |
| macOS: output stays on BlackHole after exit | Install `switchaudio-osx`, or switch the output back in System Settings > Sound |
| `pip` says it installed `UNKNOWN` | Old pip/setuptools ignored the metadata: run `scripts/install.sh` (it upgrades pip in a venv) |
| Pitch, tempo and SCREW do nothing | They apply to file playback only; open a file with `O` |
| A file will not play | Install ffmpeg, or `pip install "daneq[audio]"`; the player shows the reason in the transport bar |
| Terminal too small | Needs at least 80x24 (more bands need a little more width) |
| Mouse does odd things | `--no-mouse` |
| ThinLinc: no sound | Enable audio in the client; check `pactl info` inside the session |

## Development and testing

```bash
pip install -e ".[dev,audio]"
pytest -q                     # unit tests: DSP, effects, sounds, visuals, nerd parsers, backends, packaging
daneq --selftest              # accuracy check against the analytic response
daneq --demo pink --no-output # eyeball check
```

Layout: `daneq/dsp.py` (filters, analyzer), `effects.py`, `sounds.py` + `synth.py` (test signals), `visuals.py`,
`ui.py`, `nerd.py`, `audio.py` (Pulse and PortAudio backends), `clips.py`, `themes.py`, `cli.py`.
CI runs the tests on Linux and macOS. Packaging metadata lives in `setup.cfg` so that even old pip/setuptools
(such as the ones Apple ships) install it correctly.

## Publishing

Publishing a GitHub Release updates everything: PyPI, Docker Hub and GHCR (multi-arch), and the documentation
site at https://fourzerosix.github.io/DanEQ/. See `RELEASING.md` for the one-time setup and the per-release steps.

## FAQ and roadmap

**Why not cava?** cava only visualizes. DanEQ changes the sound, then shows you the result.

**Can I use it as a permanent system EQ?** Run it in a terminal multiplexer. A headless daemon mode is on the roadmap.

**Roadmap ideas**: gapless playback and cover art; headless daemon with systemd user unit; Equalizer APO import (AutoEq headphone profiles);
named user presets saved from the menu; per-app routing; recording the processed output to WAV; MIDI/OSC control;
Windows WASAPI loopback; a native iOS app; pitch shifting and convolution reverb.

## License

GPL-3.0 (see `LICENSE`). Public domain tunes and recordings keep their own status as described above.

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

---
