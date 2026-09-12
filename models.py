"""ORM models — every webhook and tool call lands here for audit."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.db import Base


def _uuid():
    return str(uuid.uuid4())


def _now():
    return datetime.now(timezone.utc)


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    external_id = Column(String(128), unique=True, index=True)  # vendor's ID
    title = Column(String(512), nullable=False)
    severity = Column(String(32), nullable=False, index=True)   # critical|high|medium|low
    detail = Column(Text)
    source = Column(String(128))
    status = Column(String(32), default="active", index=True)
    raw = Column(JSONB)                                          # original payload
    created_at = Column(DateTime(timezone=True), default=_now)


class CallLog(Base):
    __tablename__ = "call_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vapi_call_id = Column(String(128), unique=True, index=True)
    caller_number = Column(String(64))
    direction = Column(String(16), default="inbound")            # inbound|outbound
    tools_called = Column(JSONB, default=list)
    created_at = Column(DateTime(timezone=True), default=_now)
