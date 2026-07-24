"""Standard-Webhooks-style signing for the vendor webhook contract.

Signature: HMAC-SHA256 over ``{webhook-id}.{webhook-timestamp}.{raw body}``
keyed with the raw ``VENDOR_WEBHOOK_SECRET`` string, header value ``v1,<base64>``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid
from typing import Any

import httpx


def _raw_body(payload: Any) -> str:
    if isinstance(payload, bytes):
        return payload.decode()
    if isinstance(payload, str):
        return payload
    return json.dumps(payload, separators=(",", ":"))


def sign(
    payload: Any,
    secret: str,
    ts: int | None = None,
    webhook_id: str | None = None,
) -> dict[str, str]:
    """Headers (`webhook-id`, `webhook-timestamp`, `webhook-signature`) for a payload."""
    body = _raw_body(payload)
    ts = int(time.time()) if ts is None else int(ts)
    webhook_id = webhook_id or f"msg_{uuid.uuid4().hex}"
    to_sign = f"{webhook_id}.{ts}.{body}".encode()
    digest = hmac.new(secret.encode(), to_sign, hashlib.sha256).digest()
    return {
        "webhook-id": webhook_id,
        "webhook-timestamp": str(ts),
        "webhook-signature": f"v1,{base64.b64encode(digest).decode()}",
    }


def deliver(api_url: str, payload: Any, secret: str, **overrides: Any) -> httpx.Response:
    """Sign `payload` and POST it to ``{api_url}/api/webhooks/vendor``.

    Overrides: ``ts=``/``webhook_id=`` are forwarded to sign(); ``body=`` sends
    that raw body instead of the signed payload (tampering); ``headers=`` is
    merged last (header-level tampering); ``timeout=`` for the HTTP call.
    """
    ts = overrides.pop("ts", None)
    webhook_id = overrides.pop("webhook_id", None)
    body_override = overrides.pop("body", None)
    extra_headers = overrides.pop("headers", None)
    timeout = overrides.pop("timeout", 10.0)
    if overrides:
        raise TypeError(f"unknown overrides: {sorted(overrides)}")

    signed_body = _raw_body(payload)
    headers = {"content-type": "application/json"}
    headers.update(sign(signed_body, secret, ts=ts, webhook_id=webhook_id))
    if extra_headers:
        headers.update(extra_headers)
    sent = _raw_body(body_override) if body_override is not None else signed_body
    return httpx.post(
        f"{api_url.rstrip('/')}/api/webhooks/vendor",
        content=sent,
        headers=headers,
        timeout=timeout,
    )
