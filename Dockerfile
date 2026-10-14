ARG PULSE_INSTALL=online
FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1 AS base
ENV PYTHONUNBUFFERED=1 UV_CACHE_DIR=/tmp/uv-cache DATA_DIR=/data
WORKDIR /app
FROM base AS online
RUN pip install --no-cache-dir uv==0.12.23
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
FROM base AS offline
COPY --from=wheelhouse / /wheels/
RUN python -m venv /app/.venv && /app/.venv/bin/python -m pip install --no-index --require-hashes --find-links=/wheels -r /wheels/requirements.txt && rm -rf /wheels
FROM ${PULSE_INSTALL} AS final
COPY app ./app
COPY docs/evaluation ./docs/evaluation
RUN useradd --uid 10001 --create-home pulse && chmod -R a+rX /app/app /app/docs && mkdir /data && chown pulse:pulse /data
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD ["/app/.venv/bin/python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)"]
CMD ["/app/.venv/bin/python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
