# Build context is the repo root (uv workspace).
FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /srv
COPY . .
RUN uv sync --frozen --no-dev --package taskboard-api
ENV DATA_DIR=/data
CMD ["uv", "run", "--package", "taskboard-api", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
