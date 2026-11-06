FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DEVKG_DB_PATH=/data/devkg.sqlite3

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY devkg_watcher ./devkg_watcher

# Non-root user; /data is created here so a fresh named volume inherits its ownership.
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin app \
    && mkdir /data && chown app:app /data
USER app
VOLUME ["/data"]

ENTRYPOINT ["python", "-m", "devkg_watcher"]
