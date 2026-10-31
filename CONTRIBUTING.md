# Contributing to DanEQ

Thanks for helping. The short version:

```bash
git clone https://github.com/fourzerosix/DanEQ.git && cd DanEQ
make dev          # editable install with test and audio extras
make check        # tests, DSP self-test, smoke tests
daneq --demo pink --no-output     # eyeball your change
```

- Keep changes small and add a test in `tests/` when behavior changes.
- DSP changes must keep `daneq --selftest` passing (the audio must match the displayed curve).
- New test signals go in `daneq/sounds.py` and must be synthesized or public domain. Say why in the PR if it is a tune.
- Add a line under the next version in `CHANGELOG.md`.
- Bug reports: include `daneq --version`, your OS, terminal, and on macOS the output of `daneq --list-devices`.

Releases are described in `RELEASING.md`.
