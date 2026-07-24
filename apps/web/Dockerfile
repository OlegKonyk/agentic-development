# Build from the repo root: docker build -f apps/web/Dockerfile .
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

COPY . .
RUN uv sync --frozen --package taskboard-web --no-dev

EXPOSE 8001
CMD ["uv", "run", "--package", "taskboard-web", "uvicorn", "web.main:app", "--host", "0.0.0.0", "--port", "8001"]
