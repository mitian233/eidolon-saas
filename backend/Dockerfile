FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev

# On the PATH so that the admin can run `docker compose exec backend eidolon ...`.
ENV PATH=/app/.venv/bin:$PATH \
    EIDOLON_DATABASE_PATH=/data/eidolon.db
EXPOSE 8000
CMD ["eidolon"]
