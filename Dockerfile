FROM python:3.12-slim-bookworm AS base
COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /uvx /bin/
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/app/.venv/bin:$PATH"
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY backend ./backend
COPY scripts ./scripts
COPY alembic.ini ./
RUN uv sync --locked --no-dev
RUN useradd --create-home --uid 10001 app && chown app:app /app
USER app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]

FROM base AS checks
USER root
RUN uv sync --locked --group ml
COPY backend/tests ./backend/tests
USER app
CMD ["pytest", "-m", "not integration"]
