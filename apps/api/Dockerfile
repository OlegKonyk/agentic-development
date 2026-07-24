# Build context is the repo root (uv workspace).
# The same image serves three compose services:
#   api (default CMD below)
#   worker:    uv run --package taskboard-api taskiq worker app.tkq:broker
#   scheduler: uv run --package taskboard-api taskiq scheduler app.tkq:scheduler
FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /srv
COPY . .
RUN uv sync --frozen --no-dev --package taskboard-api
CMD ["uv", "run", "--frozen", "--no-dev", "--package", "taskboard-api", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
