# Changelog

## 0.4.0
- macOS support: PortAudio backend (`sounddevice`) with BlackHole loopback capture, automatic output switching via
  `switchaudio-osx`, `--backend`, `--input`, `--output`, `--list-devices`; nerd mode works without /proc
- Installer rewritten for Linux and macOS (virtualenv, Homebrew, PATH handling, `--uninstall`)
- Packaging moved to `setup.cfg` so old pip/setuptools no longer produce an `UNKNOWN` package
- Esc menu (btop style) with submenus for view, bar style, theme and preset, plus an About page
- New public domain tunes: Amazing Grace (from the public domain HymnWiki score), Twinkle Twinkle, Row Row Row Your
  Boat, Jingle Bells, Silent Night, Yankee Doodle, Oh! Susanna, Pachelbel's Canon
- README rewritten: install per platform, dependencies, many usage examples, effects reference, troubleshooting
- CI runs on Linux and macOS

## 0.3.0
- Fluidity: 60 fps loop with time-based physics (attack/release, gravity peak caps), spatial smoothing,
  multi-resolution FFT (long window for bass, short for treble)
- Bar styles (`g`, `--style`): braille, line, mirror, dots, blocks, ascii
- 20 color themes with 24-step gradients (`c`/`C`, `--theme`); frequency-zoned bar coloring
- Effects rack (`f`): compressor, overdrive, bitcrusher, megaphone, phaser, flanger, chorus, tremolo,
  echo, reverb, stereo widener, with braille rotary knobs, mouse and keyboard control
- Response panel now shades boost and cut areas
- Resizable panels: `(` `)` `{` `}` and mouse drag on panel borders
- New views (`v`/`V`, `--view`): waterfall, scope, vectorscope, radial, vinyl record, reel-to-reel tape deck,
  fire, starfield, ripples, matrix rain
- Nerd mode (`n`, `--nerd`): audio processes (CPU, memory, sparklines), PulseAudio/PipeWire streams,
  devices, ALSA hardware, DSP load graph
- Test signals: animal suite (17 animals + `--zoo`), `--cartoon`, `--loudspeaker`, `--binaural`
  (`--beat`, `--carrier`), `--dialup`, `--dtmf`, `--siren`, `--morse`, chiptune melodies, white/brown noise
- Public domain clip library fetched on demand (`--clip moon|infamy|fdr|jfk|cuba`, or any path or URL)
- Optional `soundfile` decoder (`pip install daneq[audio]`) for hosts without ffmpeg
- Soft knee limiter, FX state saved in the config

## 0.2.0
- Renamed to DanEQ
- Three analyzer views: spectrum, braille waterfall, oscilloscope (`v`)
- Color themes: classic, ice, fire, synthwave, mono (`c`, `--theme`)
- Help overlay (`?`)
- Auto headroom (`a`) sets the preamp so boosts cannot clip
- Export settings as Equalizer APO / EasyEffects style text (`e`, `daneq --export`)
- `--preset NAME`, `--list-presets`
- Soft knee limiter replaces hard clipping

## 0.1.0
- Initial release: 4/6/8/10 band EQ, braille spectrum, response curve, meters, mouse support
