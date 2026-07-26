# syntax=docker/dockerfile:1

# --- stage 1: build the frontend bundle -------------------------------------
# Node exists only here; it never reaches the runtime image.
FROM node:22-alpine AS frontend

WORKDIR /build/frontend

# Dependency layer first, so editing source does not invalidate `npm ci`.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
# The build writes to ../static/js/app.js, so static/ must be in place first.
COPY static/ /build/static/

# Typechecks (tsc --noEmit) before bundling, so a type error fails the image
# build rather than shipping.
RUN npm run build


# --- stage 2: runtime -------------------------------------------------------
FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000 \
    WEB_CONCURRENCY=4

WORKDIR /app

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt gunicorn

COPY backend/ ./backend/
COPY --from=frontend /build/static/ ./static/
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

RUN chmod +x /usr/local/bin/docker-entrypoint.sh \
 && adduser --system --group --no-create-home appuser \
 && chown -R appuser:appuser /app

USER appuser

# app.py imports db/views/schemas as top-level modules, and static_folder is
# "../static", so the process must run from backend/.
WORKDIR /app/backend

EXPOSE 8000

# Liveness only — /healthz deliberately does not touch the database.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8000')+'/healthz')" || exit 1

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["gunicorn", "app:app"]
