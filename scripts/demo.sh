#!/usr/bin/env bash
# Quick tour for a node with no audio path (for example a ThinLinc session).
export TERM="${TERM:-xterm-256color}" LANG="${LANG:-en_US.UTF-8}"
daneq --selftest || exit 1
echo "Starting demo in 3 seconds. Try: arrows to pick a band, PgUp to boost it, b to A/B, v for views, ? for help."
sleep 3
exec daneq --demo pink --no-output "$@"
