FROM python:3.12-slim

# arcade serves files and runs nothing: every game runs in the player's own
# tab. Standard library only - there is nothing to pip install.
WORKDIR /app
COPY src/ ./src/

RUN useradd --system --no-create-home arcade \
    && mkdir -p /data /config && chown arcade /data

USER arcade

ENV PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1 \
    ARCADE_HOST=0.0.0.0 \
    ARCADE_PORT=8080 \
    ARCADE_DATA=/data \
    ARCADE_REGISTRY=/config/games.yaml

# /data holds every uploaded version (back it up); /config/games.yaml is the
# registry, mounted read-only from the gateway repository.
VOLUME ["/data"]
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python3", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz')"]

CMD ["python3", "-m", "arcade", "serve"]
