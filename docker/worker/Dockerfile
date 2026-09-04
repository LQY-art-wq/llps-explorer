# syntax=docker/dockerfile:1.7
FROM python:3.12.13-slim-bookworm AS seg-builder
RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY external/seg-source.json ./external/seg-source.json
COPY scripts/setup_seg.py ./scripts/setup_seg.py
RUN python scripts/setup_seg.py --platform linux-x64 --destination /opt/seg

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
    PATH=/opt/venv/bin:$PATH \
    LD_LIBRARY_PATH=/opt/ncbi-blast/lib:/opt/ncbi-blast/lib64 \
    SEG_EXECUTABLE_PATH=/opt/ncbi-blast/bin/segmasker \
    BLAST_USAGE_REPORT=false
RUN apt-get update \
    && apt-get install --yes --no-install-recommends libpq5 libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && python -m venv /opt/venv \
    && groupadd --gid 10001 llps \
    && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /nonexistent llps
COPY --from=seg-builder /opt/seg/ncbi-blast-2.17.0+ /opt/ncbi-blast
COPY --from=wheels /wheels /wheels
COPY backend/requirements.lock.txt /tmp/requirements.lock.txt
RUN python -m pip install --no-cache-dir --no-index --find-links=/wheels \
        -r /tmp/requirements.lock.txt llps-explorer-backend \
    && rm -rf /wheels /tmp/requirements.lock.txt \
    && /opt/ncbi-blast/bin/segmasker -version \
    && printf '>build_probe\nQQQQQQQQQQQQ\n' \
       | /opt/ncbi-blast/bin/segmasker -in - -out - -infmt fasta -outfmt interval \
           -window 12 -locut 2.2 -hicut 2.5 \
       | grep -Eq '^0[[:space:]]*-[[:space:]]*11$'
WORKDIR /app/backend
COPY --chown=10001:10001 backend/alembic.ini ./alembic.ini
COPY --chown=10001:10001 docker/worker/healthcheck.py /opt/llps/worker_healthcheck.py
USER 10001:10001
CMD ["python", "-m", "app.worker"]
