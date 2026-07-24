import base64
import hashlib
import hmac
import json
import time
from datetime import UTC, datetime, timedelta

import pytest
from app import db
from app.models import Task, WebhookEvent
from httpx import AsyncClient
from sqlalchemy import update
from sqlmodel import select

pytestmark = pytest.mark.anyio

SECRET = "whsec_test"
URL = "/api/webhooks/vendor"


def sign(body: bytes, wid: str, ts: str, secret: str = SECRET) -> str:
    mac = hmac.new(secret.encode(), f"{wid}.{ts}.".encode() + body, hashlib.sha256)
    return "v1," + base64.b64encode(mac.digest()).decode()


def signed_headers(
    body: bytes,
    wid: str = "evt-1",
    ts: int | None = None,
    secret: str = SECRET,
    signature: str | None = None,
) -> dict[str, str]:
    stamp = str(int(time.time()) if ts is None else ts)
    return {
        "webhook-id": wid,
        "webhook-timestamp": stamp,
        "webhook-signature": signature if signature is not None else sign(body, wid, stamp, secret),
        "content-type": "application/json",
    }


def delivered_body(task_id: int) -> bytes:
    return json.dumps(
        {"event": "notification.delivered", "notification_id": "n-1", "task_id": task_id}
    ).encode()


async def make_pending_task(client: AsyncClient, headers: dict[str, str]) -> int:
    due = (datetime.now(UTC) + timedelta(minutes=2)).isoformat().replace("+00:00", "Z")
    resp = await client.post(
        "/api/tasks", json={"title": "remind me", "due_at": due}, headers=headers
    )
    assert resp.status_code == 201
    task_id: int = resp.json()["id"]
    await set_reminder_status(task_id, "pending")
    return task_id


async def set_reminder_status(task_id: int, value: str) -> None:
    async with db.session_scope() as session:
        await session.execute(
            update(Task).where(Task.id == task_id).values(reminder_status=value)  # type: ignore[arg-type]
        )
        await session.commit()


async def reminder_status(client: AsyncClient, headers: dict[str, str], task_id: int) -> str:
    resp = await client.get(f"/api/tasks/{task_id}", headers=headers)
    assert resp.status_code == 200
    status: str = resp.json()["reminder_status"]
    return status


async def event_count() -> int:
    async with db.session_scope() as session:
        return len((await session.exec(select(WebhookEvent))).all())


async def test_valid_delivery_flips_pending_to_sent(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    task_id = await make_pending_task(client, alice_headers)
    body = delivered_body(task_id)
    resp = await client.post(URL, content=body, headers=signed_headers(body))
    assert resp.status_code == 200
    assert await reminder_status(client, alice_headers, task_id) == "sent"
    assert await event_count() == 1


async def test_tampered_body_401(client: AsyncClient, alice_headers: dict[str, str]) -> None:
    task_id = await make_pending_task(client, alice_headers)
    body = delivered_body(task_id)
    headers = signed_headers(body)
    tampered = body.replace(b"delivered", b"exploited")
    resp = await client.post(URL, content=tampered, headers=headers)
    assert resp.status_code == 401
    assert await reminder_status(client, alice_headers, task_id) == "pending"
    assert await event_count() == 0


@pytest.mark.parametrize("offset", [-400, 400], ids=["stale", "future"])
async def test_timestamp_out_of_tolerance_400(
    client: AsyncClient, alice_headers: dict[str, str], offset: int
) -> None:
    task_id = await make_pending_task(client, alice_headers)
    body = delivered_body(task_id)
    headers = signed_headers(body, ts=int(time.time()) + offset)
    resp = await client.post(URL, content=body, headers=headers)
    assert resp.status_code == 400
    assert await reminder_status(client, alice_headers, task_id) == "pending"


async def test_wrong_secret_401(client: AsyncClient, alice_headers: dict[str, str]) -> None:
    task_id = await make_pending_task(client, alice_headers)
    body = delivered_body(task_id)
    resp = await client.post(URL, content=body, headers=signed_headers(body, secret="whsec_other"))
    assert resp.status_code == 401


@pytest.mark.parametrize("signature", ["", "garbage", "v2,AAAA", "v1,AAAA"])
async def test_bad_signature_header_401(
    client: AsyncClient, alice_headers: dict[str, str], signature: str
) -> None:
    task_id = await make_pending_task(client, alice_headers)
    body = delivered_body(task_id)
    resp = await client.post(URL, content=body, headers=signed_headers(body, signature=signature))
    assert resp.status_code == 401


async def test_missing_id_or_timestamp_400(client: AsyncClient) -> None:
    body = b"{}"
    headers = signed_headers(body)
    for drop in ("webhook-id", "webhook-timestamp"):
        partial = {k: v for k, v in headers.items() if k != drop}
        resp = await client.post(URL, content=body, headers=partial)
        assert resp.status_code == 400


async def test_non_integer_timestamp_400(client: AsyncClient) -> None:
    body = b"{}"
    headers = signed_headers(body)
    headers["webhook-timestamp"] = "yesterday"
    resp = await client.post(URL, content=body, headers=headers)
    assert resp.status_code == 400


async def test_invalid_json_400(client: AsyncClient) -> None:
    body = b"not json"
    resp = await client.post(URL, content=body, headers=signed_headers(body))
    assert resp.status_code == 400


async def test_duplicate_id_single_side_effect(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    task_id = await make_pending_task(client, alice_headers)
    body = delivered_body(task_id)
    headers = signed_headers(body, wid="evt-dup")

    first = await client.post(URL, content=body, headers=headers)
    assert first.status_code == 200
    assert await reminder_status(client, alice_headers, task_id) == "sent"

    # Rewind the state: a second delivery of the SAME id must be a no-op.
    await set_reminder_status(task_id, "pending")
    second = await client.post(URL, content=body, headers=headers)
    assert second.status_code == 200
    assert await reminder_status(client, alice_headers, task_id) == "pending"
    assert await event_count() == 1


async def test_delivery_for_non_pending_task_is_noop(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    task_id = await make_pending_task(client, alice_headers)
    await set_reminder_status(task_id, "none")
    body = delivered_body(task_id)
    resp = await client.post(URL, content=body, headers=signed_headers(body))
    assert resp.status_code == 200
    assert await reminder_status(client, alice_headers, task_id) == "none"


async def test_unknown_event_and_task_are_accepted(client: AsyncClient) -> None:
    body = json.dumps({"event": "notification.bounced", "task_id": 9999}).encode()
    resp = await client.post(URL, content=body, headers=signed_headers(body, wid="evt-odd"))
    assert resp.status_code == 200
    assert await event_count() == 1
