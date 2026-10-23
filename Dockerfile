FROM python:3.12-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends pulseaudio-utils ffmpeg \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY pyproject.toml README.md LICENSE ./
COPY daneq ./daneq
RUN pip install --no-cache-dir .
ENV LANG=C.UTF-8 TERM=xterm-256color
ENTRYPOINT ["daneq"]
