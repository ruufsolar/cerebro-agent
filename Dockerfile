FROM ghcr.io/astral-sh/uv:python3.13-trixie-slim AS builder
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app/api
COPY api/pyproject.toml api/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-install-project --no-dev
COPY api/ ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev

FROM python:3.13-slim-trixie
RUN apt-get update && apt-get install -y --no-install-recommends libpq5 curl \
    && rm -rf /var/lib/apt/lists/*
RUN groupadd -r cerebro && useradd -r -g cerebro cerebro
WORKDIR /app
COPY --from=builder /app/api /app/api
COPY knowledge/ /app/knowledge/
ENV PATH="/app/api/.venv/bin:$PATH" \
    CEREBRO_KNOWLEDGE_DIR=/app/knowledge
USER cerebro
EXPOSE 8000
CMD ["python", "-m", "cerebro.web"]
