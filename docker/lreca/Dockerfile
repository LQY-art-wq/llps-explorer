# syntax=docker/dockerfile:1.7
FROM python:3.10.19-slim-bookworm AS source
RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates git \
    && rm -rf /var/lib/apt/lists/* \
    && git init /opt/lreca \
    && git -C /opt/lreca remote add origin https://github.com/ai-phasepro/LRECA.git \
    && git -C /opt/lreca sparse-checkout init --no-cone \
    && printf '%s\n' \
        '/Demo/code_for_model_testing/RCNN_ECA_personal_test.py' \
        '/Demo/code_for_model_testing/RCNN_ECA_3_human_test.py' \
        '/Demo/code_for_model_testing/RCNN_ECA_saliency/saliency_function/verify/RCNN_ECA_saliency_verify_gradCAM_fortest.py' \
        '/Demo/code_for_model_testing/RCNN_ECA_saliency/LCRs_process/split_LCRs_segment_forsingle.py' \
        '/Data/pos_dataset/pos_word_list_human.txt' \
        '/Data/neg_dataset/neg_word_list_human.txt' \
        > /opt/lreca/.git/info/sparse-checkout \
    && git -C /opt/lreca fetch --depth 1 --filter=blob:none origin 0b4b48ab7870529a34028c6e30dfba42eddbf215 \
    && git -C /opt/lreca checkout --detach FETCH_HEAD \
    && test "$(git -C /opt/lreca rev-parse HEAD)" = "0b4b48ab7870529a34028c6e30dfba42eddbf215" \
    && test -z "$(git -C /opt/lreca status --porcelain=v1 --untracked-files=no)" \
    && git -C /opt/lreca remote remove origin \
    && test -z "$(find /opt/lreca -type f \( -iname '*.pt' -o -iname '*.pth' -o -iname '*.ckpt' -o -iname '*.safetensors' -o -iname '*.onnx' -o -iname '*.h5' -o -iname '*.hdf5' \) -print -quit)" \
    && for model_path in $(git -C /opt/lreca ls-tree -r --name-only HEAD | grep -E '\.(pt|pth|ckpt|safetensors|onnx|h5|hdf5)$'); do \
         model_oid="$(git -C /opt/lreca rev-parse "HEAD:${model_path}")"; \
         if git -C /opt/lreca cat-file -e "${model_oid}" 2>/dev/null; then \
           echo "Model blob unexpectedly present in sanitized LRECA source: ${model_path}" >&2; \
           exit 1; \
         fi; \
       done

FROM python:3.10.19-slim-bookworm AS wheels
WORKDIR /build
COPY backend/requirements-lreca.lock.txt ./requirements-lreca.lock.txt
COPY backend/requirements-lreca-service.lock.txt ./requirements-lreca-service.lock.txt
RUN python -m pip install --no-cache-dir --upgrade "pip==23.0.1" \
    && python -m pip wheel --no-cache-dir --wheel-dir /wheels-service \
        -r requirements-lreca-service.lock.txt \
    && python -m pip wheel --no-cache-dir --wheel-dir /wheels-science \
        -r requirements-lreca.lock.txt

FROM python:3.10.19-slim-bookworm AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH=/opt/service-venv/bin:$PATH \
    LRECA_REPOSITORY=/opt/lreca \
    LRECA_PYTHON=/opt/lreca-venv/bin/python \
    HOME=/tmp \
    XDG_CACHE_HOME=/tmp/cache \
    MPLCONFIGDIR=/tmp/matplotlib
RUN apt-get update \
    && apt-get install --yes --no-install-recommends git libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && python -m venv /opt/service-venv \
    && python -m venv /opt/lreca-venv \
    && groupadd --gid 10001 llps \
    && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /nonexistent llps
COPY --from=wheels /wheels-service /wheels-service
COPY --from=wheels /wheels-science /wheels-science
COPY backend/requirements-lreca.lock.txt /tmp/requirements-lreca.lock.txt
COPY backend/requirements-lreca-service.lock.txt /tmp/requirements-lreca-service.lock.txt
RUN /opt/service-venv/bin/python -m pip install --no-cache-dir --no-index \
        --find-links=/wheels-service \
        -r /tmp/requirements-lreca-service.lock.txt \
    && /opt/lreca-venv/bin/python -m pip install --no-cache-dir --no-index \
        --find-links=/wheels-science \
        -r /tmp/requirements-lreca.lock.txt \
    && rm -rf /wheels-service /wheels-science /tmp/requirements-lreca*.lock.txt
COPY --from=source --chown=10001:10001 /opt/lreca /opt/lreca
WORKDIR /app/backend
COPY --chown=10001:10001 backend/app ./app
COPY --chown=10001:10001 backend/lreca_runtime ./lreca_runtime
COPY --chown=10001:10001 backend/lreca_service ./lreca_service
COPY --chown=10001:10001 external/lreca-source.json /app/external/lreca-source.json
USER 10001:10001
EXPOSE 8001
CMD ["uvicorn", "lreca_service.main:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "1"]
