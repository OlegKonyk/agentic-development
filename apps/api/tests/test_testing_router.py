import base64
import hashlib
import hmac
import json
import time

import pytest
from app import db
from app.models import User, WebhookEvent
from httpx import AsyncClient
from sqlmodel import select

from tests.conftest import ALICE, AppFactory, bearer, client_for, login

pytestmark = pytest.mark.anyio


async def test_reset_wipes_state_but_keeps_users(client: AsyncClient) -> None:
    token = await login(client)
    resp = await client.post("/api/tasks", json={"title": "doomed"}, headers=bearer(token))
    assert resp.status_code == 201
    body = json.dumps({"event": "notification.delivered", "task_id": 1}).encode()
    ts = str(int(time.time()))
    mac = hmac.new(b"whsec_test", f"evt-r.{ts}.".encode() + body, hashlib.sha256)
    resp = await client.post(
        "/api/webhooks/vendor",
        content=body,
        headers={
            "webhook-id": "evt-r",
            "webhook-timestamp": ts,
            "webhook-signature": "v1," + base64.b64encode(mac.digest()).decode(),
        },
    )
    assert resp.status_code == 200

    resp = await client.post("/api/testing/reset")
    assert resp.status_code == 204

    # Sessions are wiped: the old token replays as 401.
    assert (await client.get("/api/auth/me", headers=bearer(token))).status_code == 401
    # Users survive: login works again, and the board is empty.
    fresh = await login(client, ALICE)
    assert (await client.get("/api/tasks", headers=bearer(fresh))).json() == []
    async with db.session_scope() as session:
        assert (await session.exec(select(WebhookEvent))).all() == []
        assert len((await session.exec(select(User))).all()) == 2


async def test_testing_routes_not_mounted_outside_test_env(
    db_setup: None, make_app: AppFactory
) -> None:
    async with client_for(make_app(app_env="production")) as client:
        assert (await client.post("/api/testing/reset")).status_code == 404
        assert (await client.post("/api/testing/run-due-reminders")).status_code == 404


async def test_testing_routes_not_mounted_when_env_unset(
    db_setup: None, make_app: AppFactory
) -> None:
    async with client_for(make_app(app_env=None)) as client:
        assert (await client.post("/api/testing/reset")).status_code == 404
        assert (await client.post("/api/testing/run-due-reminders")).status_code == 404
