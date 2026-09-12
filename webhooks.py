"""Webhook-driven vulnerability alerts — the proactive half of the product.

POST /webhooks/vulnerability  <- scanners, UpGuard, or your SOC platform
  1. verify HMAC signature
  2. normalize + persist to PostgreSQL (idempotent on external_id)
  3. publish to Redis pub/sub
  4. if severity == critical -> trigger outbound Vapi call to the on-call number
"""
import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

from app.config import settings
from app.db import get_db
from app.models import Alert
from app.redis_client import publish_critical_alert

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
log = logging.getLogger(__name__)


def _verify(payload: bytes, signature: str | None) -> None:
    secret = (settings.vapi_webhook_secret or "").encode()
    if not secret:
        return  # dev mode
    expected = hmac.new(secret, payload, hashlib.sha256).hexdigest()
    if not signature or not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="bad webhook signature")


@router.post("/vulnerability")
async def vulnerability_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    payload = await request.body()
    _verify(payload, request.headers.get("X-Signature-256"))
    data = json.loads(payload)

    alert = Alert(
        external_id=str(data.get("id") or hashlib.sha256(payload).hexdigest()[:16]),
        title=data.get("title", "Untitled alert"),
        severity=data.get("severity", "medium").lower(),
        detail=data.get("detail"),
        source=data.get("source", "unknown"),
        status="active",
        raw=data,
    )

    existing = await db.scalar(select(Alert).where(Alert.external_id == alert.external_id))
    if existing:
        return {"status": "duplicate", "id": alert.external_id}

    db.add(alert)
    await db.commit()
    await publish_critical_alert({"id": alert.external_id, "severity": alert.severity,
                                  "title": alert.title})

    if alert.severity == "critical":
        await _place_outbound_call(alert)

    return {"status": "accepted", "id": alert.external_id,
            "notified": alert.severity == "critical"}


async def _place_outbound_call(alert: Alert) -> None:
    """Call the on-call engineer and have the assistant brief them."""
    if not (settings.vapi_api_key and settings.vapi_assistant_id):
        log.warning("critical alert %s — Vapi not configured, skipping outbound call",
                    alert.external_id)
        return
    async with httpx.AsyncClient(timeout=10) as http:
        resp = await http.post(
            "https://api.vapi.ai/call",
            headers={"Authorization": f"Bearer {settings.vapi_api_key}"},
            json={
                "phoneNumberId": settings.vapi_phone_number_id,
                "assistantId": settings.vapi_assistant_id,
                "customer": {"number": settings.oncall_number},
                "assistantOverrides": {
                    "firstMessage": (
                        f"Critical security alert: {alert.title}. "
                        f"Details: {alert.detail or 'see dashboard'}. "
                        f"Say 'summary' for current risk context."
                    )
                },
            },
        )
        resp.raise_for_status()
        log.info("outbound call placed for alert %s", alert.external_id)
