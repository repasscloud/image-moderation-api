FROM python:3.12-slim-bookworm AS dependencies
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update && apt-get install -y --no-install-recommends build-essential ca-certificates libgomp1 && rm -rf /var/lib/apt/lists/*
WORKDIR /build
COPY requirements.txt ./
RUN pip install --prefix=/install --index-url https://pypi.org/simple --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt

FROM python:3.12-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    MODEL_CACHE=/app/model-cache HF_HOME=/app/model-cache/huggingface \
    HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 \
    OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 \
    HOST=0.0.0.0 PORT=8080
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 ca-certificates && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10001 --create-home appuser
COPY --from=dependencies /install /usr/local
WORKDIR /app
COPY scripts/download_models.py /tmp/download_models.py
RUN MODEL_CACHE=/opt/models HF_HUB_OFFLINE=0 TRANSFORMERS_OFFLINE=0 python /tmp/download_models.py \
    && rm /tmp/download_models.py && mkdir -p /app/model-cache \
    && chown -R appuser:appuser /app/model-cache
COPY app ./app
COPY scripts/entrypoint.sh /usr/local/bin/entrypoint
USER appuser
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=180s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8080')+'/health', timeout=3)"
ENTRYPOINT ["/usr/local/bin/entrypoint"]
