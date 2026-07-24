"""Vendor webhook receiver — Standard-Webhooks-style HMAC-SHA256 verification."""

import base64
import hashlib
import hmac
import json
import os
import time

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy.exc import IntegrityError

from app.db import SessionDep
from app.models import Task, WebhookEvent

MAX_SKEW_SECONDS = 300

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


def webhook_secret() -> str:
    return os.environ.get("VENDOR_WEBHOOK_SECRET", "whsec_test")


def expected_signature(secret: str, webhook_id: str, timestamp: str, body: bytes) -> str:
    signed_content = f"{webhook_id}.{timestamp}.".encode() + body
    digest = hmac.new(secret.encode(), signed_content, hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def _signature_ok(header: str, expected: str) -> bool:
    # The header may carry several space-delimited signatures, each "v1,<base64>".
    for candidate in header.split():
        version, _, signature = candidate.partition(",")
        if version == "v1" and signature and hmac.compare_digest(signature, expected):
            return True
    return False


@router.post(
    "/vendor",
    responses={
        400: {"description": "Missing/invalid webhook headers or timestamp out of tolerance"},
        401: {"description": "Invalid signature"},
    },
)
async def vendor_webhook(request: Request, session: SessionDep) -> dict[str, str]:
    body = await request.body()
    webhook_id = request.headers.get("webhook-id")
    timestamp = request.headers.get("webhook-timestamp")
    signature_header = request.headers.get("webhook-signature")

    if not webhook_id or not timestamp:
        raise HTTPException(status_code=400, detail="Missing webhook headers")
    try:
        ts = int(timestamp)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid webhook-timestamp") from None
    if abs(time.time() - ts) > MAX_SKEW_SECONDS:
        raise HTTPException(status_code=400, detail="webhook-timestamp outside tolerance")

    expected = expected_signature(webhook_secret(), webhook_id, timestamp, body)
    if not signature_header or not _signature_ok(signature_header, expected):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    try:
        payload = json.loads(body)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from None
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    # Dedupe on the vendor event id: the unique insert is the gate, so a
    # duplicate delivery produces exactly zero additional side effects.
    session.add(WebhookEvent(id=webhook_id, payload=body.decode(errors="replace")))
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        return {"status": "ok"}

    task_id = payload.get("task_id")
    if payload.get("event") == "notification.delivered" and isinstance(task_id, int):
        task = await session.get(Task, task_id)
        if task is not None and task.reminder_status == "pending":
            task.reminder_status = "sent"
            session.add(task)
    await session.commit()
    return {"status": "ok"}
