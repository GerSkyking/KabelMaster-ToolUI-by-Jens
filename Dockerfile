# ---- Stufe 1: Frontend (React-PWA) bauen ----
FROM node:22-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json* ./
RUN npm ci || npm install
COPY web/ ./
RUN npm run build

# ---- Stufe 2: Server (FastAPI) mit eingebettetem Frontend ----
FROM python:3.12-slim AS app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/srv:/srv/server \
    STATIC_DIR=/srv/static \
    DATA_DIR=/data
WORKDIR /srv

COPY server/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY core/ /srv/core/
COPY server/ /srv/server/
COPY --from=web /web/dist /srv/static

RUN useradd --system --uid 10001 --create-home wt \
    && mkdir -p /data && chown wt:wt /data \
    && sed -i 's/\r$//' /srv/server/entrypoint.sh \
    && chmod +x /srv/server/entrypoint.sh
USER wt
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/health/live',timeout=3)" || exit 1
ENTRYPOINT ["/srv/server/entrypoint.sh"]
