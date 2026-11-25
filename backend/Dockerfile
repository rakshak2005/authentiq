FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# WORKDIR must match the path assumptions in backend/app/core/config.py:
#   PROJECT_ROOT = parents[2] of backend/app/core/config.py  -> /srv/backend
#   storage_dir  = PROJECT_ROOT / "storage"                  -> /srv/storage
# docker-compose mounts storage_data at /srv/storage, so persistent
# storage writes land on the named volume.
WORKDIR /srv/backend

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

RUN useradd --create-home --uid 10001 authentiq \
    && mkdir -p /srv/storage/uploads /srv/storage/evidence \
    && chown -R authentiq:authentiq /srv

USER authentiq

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl --fail http://127.0.0.1:8000/api/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
