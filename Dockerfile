# syntax=docker/dockerfile:1

# ---- frontend build --------------------------------------------------------------------------
# The built JS is the same for every platform, so build it natively instead of under emulation.
FROM --platform=$BUILDPLATFORM node:24-alpine AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- python dependencies ---------------------------------------------------------------------
FROM python:3.14-slim AS backend
COPY --from=ghcr.io/astral-sh/uv:0.12.22 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev --no-install-project

# ---- runtime image ---------------------------------------------------------------------------
FROM python:3.14-slim
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    STATIC_DIR=/app/static
# The app runs from /app/.venv and never needs pip; the base image's pip bundles its own copies
# of urllib3, msgpack and setuptools, which then show up in image scans. Remove it.
RUN python -m pip uninstall --yes --root-user-action=ignore pip \
    && groupadd --system app && useradd --system --gid app --home /app app
WORKDIR /app
COPY --from=backend /app/.venv /app/.venv
COPY backend/alembic.ini ./
COPY backend/alembic ./alembic
COPY backend/app ./app
COPY --from=frontend /frontend/dist ./static
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && chown -R app:app /app
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"
ENTRYPOINT ["/entrypoint.sh"]
