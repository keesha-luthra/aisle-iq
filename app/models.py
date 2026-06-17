import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import (
    String, Integer, Boolean, Float, DateTime, Numeric,
    Index, UniqueConstraint, func, JSON, UUID
)
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base

class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        Index("idx_events_store_timestamp", "store_id", "timestamp"),
        Index("idx_events_visitor_id", "visitor_id"),
        Index("idx_events_event_type", "event_type"),
        Index("idx_events_is_staff", "is_staff"),
        UniqueConstraint("event_id", name="uq_events_event_id"),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    store_id: Mapped[str] = mapped_column(String(50), nullable=False)
    camera_id: Mapped[str] = mapped_column(String(50), nullable=False)
    visitor_id: Mapped[str] = mapped_column(String(50), nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    zone_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    dwell_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_staff: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    event_metadata: Mapped[Optional[dict]] = mapped_column("metadata", JSON, nullable=True)
    id_token: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    track_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    def __getattribute__(self, name):
        if name == "metadata":
            return object.__getattribute__(self, "event_metadata")
        return object.__getattribute__(self, name)

    def __setattr__(self, name, value):
        if name == "metadata":
            object.__setattr__(self, "event_metadata", value)
        else:
            object.__setattr__(self, name, value)

class VisitorSession(Base):
    __tablename__ = "visitor_sessions"

    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    visitor_id: Mapped[str] = mapped_column(String(50), nullable=False)
    store_id: Mapped[str] = mapped_column(String(50), nullable=False)
    entry_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    exit_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    is_converted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    total_events: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_staff: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

class POSTransaction(Base):
    __tablename__ = "pos_transactions"

    transaction_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    store_id: Mapped[str] = mapped_column(String(50), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    basket_value_inr: Mapped[float] = mapped_column(Numeric(precision=10, scale=2), nullable=False)
    matched_visitor_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    matched_session_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

class GlobalVisitorMatch(Base):
    __tablename__ = "global_visitor_matches"

    match_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    global_person_id: Mapped[str] = mapped_column(String(50), nullable=False)
    local_tracker_id: Mapped[str] = mapped_column(String(100), nullable=False)
    camera_id: Mapped[str] = mapped_column(String(50), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    source_camera: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    destination_camera: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    matched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
