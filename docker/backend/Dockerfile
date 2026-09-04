# syntax=docker/dockerfile:1.7
FROM python:3.12.13-slim-bookworm AS wheels
WORKDIR /build
COPY backend/requirements.lock.txt ./requirements.lock.txt
RUN python -m pip install --no-cache-dir --upgrade \
        "pip==25.0.1" "setuptools==84.0.0" "wheel==0.48.0" \
    && python -m pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.lock.txt
COPY backend/ ./backend/
RUN python -m pip wheel --no-cache-dir --no-deps --no-build-isolation \
    --wheel-dir /wheels ./backend

FROM python:3.12.13-slim-bookworm AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH=/opt/venv/bin:$PATH
RUN apt-get update \
    && apt-get install --yes --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/* \
    && python -m venv /opt/venv \
    && groupadd --gid 10001 llps \
    && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /nonexistent llps
COPY --from=wheels /wheels /wheels
COPY backend/requirements.lock.txt /tmp/requirements.lock.txt
RUN python -m pip install --no-cache-dir --no-index --find-links=/wheels \
        -r /tmp/requirements.lock.txt llps-explorer-backend \
    && rm -rf /wheels /tmp/requirements.lock.txt
WORKDIR /app/backend
COPY --chown=10001:10001 backend/alembic.ini ./alembic.ini
COPY --chown=10001:10001 backend/app ./app
USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
