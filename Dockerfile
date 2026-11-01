# syntax=docker/dockerfile:1
# DanEQ image: multi-arch friendly (amd64, arm64), non-root, ~250 MB.
#
#   docker build -t daneq .
#   docker run -it --rm daneq                         # built-in demo, no audio device needed
#   docker run -it --rm daneq --zoo --fx reverb --no-output
#   docker run -it --rm -v "$XDG_RUNTIME_DIR/pulse:/run/pulse" -e PULSE_SERVER=unix:/run/pulse/native \
#       daneq --demo                                  # real audio through the host's PulseAudio/PipeWire
#
# Live system-wide EQ (just `daneq`) needs the host audio server and is best run natively.

FROM python:3.15-slim AS build
WORKDIR /src
COPY pyproject.toml setup.py setup.cfg README.md LICENSE MANIFEST.in ./
COPY daneq ./daneq
RUN pip install --no-cache-dir --upgrade pip build \
 && python -m build --wheel --outdir /dist

FROM python:3.15-slim
LABEL org.opencontainers.image.title="DanEQ" \
      org.opencontainers.image.description="Terminal equalizer, effects rack and audio visualizer with a btop-style braille UI" \
      org.opencontainers.image.source="https://github.com/fourzerosix/DanEQ" \
      org.opencontainers.image.url="https://fourzerosix.github.io/DanEQ/" \
      org.opencontainers.image.licenses="GPL-3.0-only"

RUN apt-get update \
 && apt-get install -y --no-install-recommends pulseaudio-utils \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 1000 daneq

COPY --from=build /dist/*.whl /tmp/
RUN pip install --no-cache-dir "$(ls /tmp/*.whl)[audio]" && rm -f /tmp/*.whl

USER daneq
ENV LANG=C.UTF-8 TERM=xterm-256color
ENTRYPOINT ["daneq"]
CMD ["--demo", "--no-output"]
