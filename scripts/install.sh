#!/usr/bin/env bash
# DanEQ installer for Linux and macOS. Run from a clone of the repo:  scripts/install.sh
# Creates a private virtualenv (no system Python changes), links `daneq` into ~/.local/bin.
#   scripts/install.sh --uninstall     remove it again
#   DANEQ_YES=1 scripts/install.sh     answer yes to optional installs (BlackHole on macOS)
set -euo pipefail
cd "$(dirname "$0")/.."

OS="$(uname -s)"
VENV="${DANEQ_VENV:-$HOME/.local/share/daneq/venv}"
BIN="$HOME/.local/bin"
say()  { printf '\n==> %s\n' "$*"; }
warn() { printf 'warning: %s\n' "$*" >&2; }
ask()  { # ask "question"  -> returns 0 for yes
  [ "${DANEQ_YES:-0}" = "1" ] && return 0
  [ -t 0 ] || return 1
  read -r -p "$1 [y/N] " a; [[ "$a" =~ ^[Yy] ]]
}

if [ "${1:-}" = "--uninstall" ]; then
  rm -rf "$VENV" "$BIN/daneq"
  echo "Removed $VENV and $BIN/daneq (settings in ~/.config/daneq were kept)."
  exit 0
fi

case "$OS" in
  Linux)
    say "Installing system packages (needs sudo)"
    if command -v dnf >/dev/null 2>&1; then
      sudo dnf install -y pulseaudio-utils python3 python3-pip
    elif command -v apt-get >/dev/null 2>&1; then
      sudo apt-get update
      sudo apt-get install -y pulseaudio-utils python3 python3-pip python3-venv
      ask "Also install ffmpeg (to play mp3/ogg/flac files)?" && sudo apt-get install -y ffmpeg || true
    elif command -v pacman >/dev/null 2>&1; then
      sudo pacman -S --needed --noconfirm libpulse python python-pip
    elif command -v zypper >/dev/null 2>&1; then
      sudo zypper install -y pulseaudio-utils python3 python3-pip
    else
      warn "unknown package manager: install pactl/parec/pacat (pulseaudio-utils) and python3-venv yourself"
    fi
    EXTRA=".[audio]"
    ;;
  Darwin)
    EXTRA=".[mac]"
    if command -v brew >/dev/null 2>&1; then
      say "Installing Python and ffmpeg with Homebrew"
      brew install python ffmpeg || warn "brew install had a problem; continuing"
      export PATH="$(brew --prefix)/bin:$PATH"
      if ask "Install BlackHole 2ch (free loopback driver) and switchaudio-osx for system-wide EQ?"; then
        brew install --cask blackhole-2ch || warn "BlackHole install failed (it may need your password or a reboot)"
        brew install switchaudio-osx || true
      fi
    else
      warn "Homebrew not found (https://brew.sh). Continuing with the system Python; install brew later for BlackHole."
    fi
    ;;
  *)
    warn "unsupported OS '$OS'; trying a generic install"
    EXTRA="."
    ;;
esac

PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 9))' 2>/dev/null; then PY="$c"; break; fi
done
[ -n "$PY" ] || { echo "Python 3.9 or newer is required." >&2; exit 1; }

say "Creating virtualenv in $VENV using $($PY --version)"
mkdir -p "$(dirname "$VENV")" "$BIN"
"$PY" -m venv "$VENV"
"$VENV/bin/python" -m pip install --quiet --upgrade pip setuptools wheel
say "Installing DanEQ ($EXTRA)"
"$VENV/bin/python" -m pip install --upgrade "$EXTRA"
ln -sf "$VENV/bin/daneq" "$BIN/daneq"

case ":$PATH:" in
  *":$BIN:"*) ;;
  *)
    RC="$HOME/.profile"
    case "${SHELL:-}" in */zsh) RC="$HOME/.zshrc" ;; */bash) [ "$OS" = Darwin ] && RC="$HOME/.bash_profile" || RC="$HOME/.bashrc" ;; esac
    if ! grep -qs '\.local/bin' "$RC" 2>/dev/null; then
      printf '\nexport PATH="$HOME/.local/bin:$PATH"\n' >> "$RC"
      echo "Added ~/.local/bin to PATH in $RC (open a new terminal, or run: export PATH=\"\$HOME/.local/bin:\$PATH\")"
    fi
    ;;
esac

say "Self-test"
"$VENV/bin/daneq" --selftest | tail -3

echo
echo "Installed.  Try:"
echo "  daneq --demo pink --no-output      # works anywhere, no audio device needed"
if [ "$OS" = "Darwin" ]; then
  echo "  daneq --list-devices               # see your audio devices"
  echo "  daneq                              # system-wide EQ (needs BlackHole, see README: macOS)"
else
  echo "  daneq                              # equalize everything playing on this machine"
fi
