#!/usr/bin/env bash
# Installs DanEQ and its audio tool dependencies. Run from a clone of the repo.
set -euo pipefail
cd "$(dirname "$0")/.."

if command -v dnf >/dev/null 2>&1; then
  sudo dnf install -y pulseaudio-utils python3-pip
elif command -v apt-get >/dev/null 2>&1; then
  sudo apt-get update
  sudo apt-get install -y pulseaudio-utils python3-pip pipx
else
  echo "Unknown package manager: install pactl/parec/pacat (pulseaudio-utils) yourself." >&2
fi

if command -v pipx >/dev/null 2>&1; then
  pipx install --force .
else
  python3 -m pip install --user --upgrade .
fi

echo
echo "Installed. Make sure ~/.local/bin is on your PATH, then try:"
echo "  daneq --selftest"
echo "  daneq --demo pink --no-output"
