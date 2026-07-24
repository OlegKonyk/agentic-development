from collections.abc import AsyncIterator, Callable
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

AppFactory = Callable[..., FastAPI]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def make_app(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> AppFactory:
    def _make(app_env: str | None = "test") -> FastAPI:
        if app_env is None:
            monkeypatch.delenv("APP_ENV", raising=False)
        else:
            monkeypatch.setenv("APP_ENV", app_env)
        # Env is patched before the app module is imported / the app is built.
        from app.main import create_app

        return create_app()

    return _make


def client_for(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")


@pytest.fixture
async def client(make_app: AppFactory) -> AsyncIterator[AsyncClient]:
    async with client_for(make_app()) as c:
        yield c
