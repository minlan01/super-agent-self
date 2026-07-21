# ── Stage 0: Frontend build ─────────────────────────────────────────────────
FROM node:20-alpine AS frontend-build

WORKDIR /frontend

COPY apps/enterprise_admin_web/package.json \
     apps/enterprise_admin_web/package-lock.json ./

RUN npm ci --prefer-offline

COPY apps/enterprise_admin_web/ ./

RUN npx vite build

# ── Stage 1: Builder ────────────────────────────────────────────────────────
FROM python:3.12 AS builder

WORKDIR /build

COPY pyproject.toml packages/ apps/ ./
RUN pip install --no-cache-dir --prefix=/install .

# ── Stage 2: Runtime ────────────────────────────────────────────────────────
FROM python:3.12.7-slim AS runtime

ARG APP_VERSION=3.11.0

LABEL org.opencontainers.image.title="Controlled Agent Platform" \
      org.opencontainers.image.description="Dual-edition controlled self-evolving Agent platform" \
      org.opencontainers.image.version="${APP_VERSION}"

RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid appuser --shell /bin/sh --create-home appuser

WORKDIR /app

COPY --from=builder /install /usr/local

COPY configs/ ./configs/
COPY scripts/ ./scripts/
COPY alembic.ini ./alembic.ini
COPY alembic/ ./alembic/

COPY --from=frontend-build /frontend/dist ./static

RUN mkdir -p /app/data /app/workspace/outputs && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health/ready')"

CMD ["uvicorn", "apps.api_server.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
