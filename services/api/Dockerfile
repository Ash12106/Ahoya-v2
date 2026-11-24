FROM ghcr.io/astral-sh/uv:0.13.9 AS uv

FROM python:3.15.1-slim-bookworm AS dependencies

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY --from=uv /uv /uvx /bin/
COPY services/api/pyproject.toml services/api/uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY services/api/app ./app

FROM dependencies AS development
RUN uv sync --locked --group dev --no-install-project
EXPOSE 8000
CMD ["/app/.venv/bin/uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--reload"]

FROM python:3.15.1-slim-bookworm AS runtime

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
RUN groupadd --system --gid 10001 ahoya && useradd --system --uid 10001 --gid ahoya --no-create-home ahoya
COPY --from=dependencies --chown=ahoya:ahoya /app/.venv /app/.venv
COPY --from=dependencies --chown=ahoya:ahoya /app/app /app/app
USER ahoya
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:create_app --factory --host 0.0.0.0 --port ${PORT:-8000}"]
