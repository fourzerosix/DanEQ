# syntax=docker/dockerfile:1
FROM python:3.12-slim AS build
WORKDIR /src
COPY pyproject.toml setup.py setup.cfg README.md LICENSE MANIFEST.in ./
COPY daneq ./daneq
RUN pip install --no-cache-dir --upgrade pip build \
 && python -m build --wheel --outdir /dist

FROM python:3.12-slim
LABEL org.opencontainers.image.title="DanEQ" \
      org.opencontainers.image.description="Terminal equalizer, effects rack and audio visualizer with a btop-style braille UI" \
      org.opencontainers.image.source="https://github.com/fourzerosix/DanEQ" \
      org.opencontainers.image.url="https://fourzerosix.github.io/DanEQ/" \
      org.opencontainers.image.licenses="MIT"
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
