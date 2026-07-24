from datetime import UTC, datetime, timedelta

import pytest
from app import db
from app.models import Session as AuthSession
from httpx import AsyncClient
from sqlalchemy import update

from tests.conftest import ALICE, PASSWORDS, bearer, login

pytestmark = pytest.mark.anyio


async def test_login_returns_token_and_expiry(client: AsyncClient) -> None:
    resp = await client.post("/api/auth/login", json={"email": ALICE, "password": PASSWORDS[ALICE]})
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body["token"], str) and body["token"]
    assert body["expires_at"].endswith("Z")
    expires = datetime.fromisoformat(body["expires_at"])
    assert expires > datetime.now(UTC)


async def test_login_wrong_password_401(client: AsyncClient) -> None:
    resp = await client.post("/api/auth/login", json={"email": ALICE, "password": "nope"})
    assert resp.status_code == 401


async def test_login_no_user_enumeration(client: AsyncClient) -> None:
    wrong_pass = await client.post("/api/auth/login", json={"email": ALICE, "password": "nope"})
    ghost = await client.post(
        "/api/auth/login", json={"email": "ghost@example.com", "password": "nope"}
    )
    assert wrong_pass.status_code == ghost.status_code == 401
    assert wrong_pass.json() == ghost.json()


async def test_login_missing_fields_422(client: AsyncClient) -> None:
    resp = await client.post("/api/auth/login", json={"email": ALICE})
    assert resp.status_code == 422


async def test_me(client: AsyncClient, alice_headers: dict[str, str]) -> None:
    resp = await client.get("/api/auth/me", headers=alice_headers)
    assert resp.status_code == 200
    assert resp.json() == {"id": 1, "email": ALICE}


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer not-a-uuid"},
        {"Authorization": "Bearer 00000000-0000-0000-0000-000000000000"},
        {"Authorization": "Basic abc"},
    ],
    ids=["missing", "garbage", "unknown", "wrong-scheme"],
)
async def test_me_bad_tokens_401(client: AsyncClient, headers: dict[str, str]) -> None:
    resp = await client.get("/api/auth/me", headers=headers)
    assert resp.status_code == 401
    assert "detail" in resp.json()


async def test_logout_revokes_session(client: AsyncClient) -> None:
    token = await login(client)
    resp = await client.post("/api/auth/logout", headers=bearer(token))
    assert resp.status_code == 204
    # The DB row is gone: the replayed token must 401 everywhere.
    assert (await client.get("/api/auth/me", headers=bearer(token))).status_code == 401
    assert (await client.post("/api/auth/logout", headers=bearer(token))).status_code == 401


async def test_expired_session_401(client: AsyncClient) -> None:
    token = await login(client)
    async with db.session_scope() as session:
        await session.execute(
            update(AuthSession).values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await session.commit()
    assert (await client.get("/api/auth/me", headers=bearer(token))).status_code == 401
    # Expired rows are deleted on first sight; replay stays 401.
    assert (await client.get("/api/auth/me", headers=bearer(token))).status_code == 401


async def test_sessions_are_independent(client: AsyncClient) -> None:
    first = await login(client)
    second = await login(client)
    await client.post("/api/auth/logout", headers=bearer(first))
    assert (await client.get("/api/auth/me", headers=bearer(second))).status_code == 200
