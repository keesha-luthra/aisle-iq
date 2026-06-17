from datetime import datetime
from enum import Enum
from uuid import UUID
from pydantic import BaseModel, Field, model_validator, field_validator, RootModel
from typing import List, Dict, Optional, Literal, Any

class EventType(str, Enum):
    ENTRY = "ENTRY"
    EXIT = "EXIT"
    ZONE_ENTER = "ZONE_ENTER"
    ZONE_EXIT = "ZONE_EXIT"
    ZONE_DWELL = "ZONE_DWELL"
    BILLING_QUEUE_JOIN = "BILLING_QUEUE_JOIN"
    BILLING_QUEUE_ABANDON = "BILLING_QUEUE_ABANDON"
    REENTRY = "REENTRY"

class EventMetadata(BaseModel):
    queue_depth: Optional[int] = None
    sku_zone: Optional[str] = None
    session_seq: int = 0
    local_tracker_id: Optional[str] = None
    reid_confidence: Optional[float] = None
    source_camera: Optional[str] = None
    destination_camera: Optional[str] = None

class StoreEvent(BaseModel):
    event_id: UUID
    store_id: str = Field(..., pattern=r"^STORE_[A-Z]{3}_\d{3}$")
    camera_id: str
    visitor_id: str = Field(..., pattern=r"^VIS_[a-f0-9]{6}$")
    event_type: EventType
    timestamp: datetime
    zone_id: Optional[str] = None
    dwell_ms: int = Field(default=0, ge=0)
    is_staff: bool = False
    confidence: float = Field(..., ge=0.0, le=1.0)
    id_token: Optional[str] = None
    track_id: Optional[str] = None
    metadata: EventMetadata = EventMetadata()
    @field_validator("event_id", mode="after")
    @classmethod
    def validate_uuid4(cls, v: UUID) -> UUID:
        if v.version != 4:
            raise ValueError("event_id must be a valid UUIDv4")
        return v

    @field_validator("timestamp", mode="after")
    @classmethod
    def validate_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            raise ValueError("timestamp must be UTC-aware (contain timezone info)")
        return v

    @model_validator(mode="after")
    def validate_event_logic(self) -> "StoreEvent":
        if self.event_type in (EventType.ZONE_ENTER, EventType.ZONE_EXIT, EventType.ZONE_DWELL):
            if self.zone_id is None:
                raise ValueError("zone_id is required for ZONE_ENTER, ZONE_EXIT, or ZONE_DWELL events")
        if self.event_type == EventType.BILLING_QUEUE_JOIN:
            if self.metadata is None or self.metadata.queue_depth is None:
                raise ValueError("queue_depth must be specified in metadata for BILLING_QUEUE_JOIN events")
        return self

class IngestRequest(BaseModel):
    events: List[Dict] = Field(..., max_length=500)

class IngestResponse(BaseModel):
    accepted: int
    rejected: int
    duplicate: int
    errors: List[Dict[str, str]]

class MetricsResponse(BaseModel):
    store_id: str
    window_start: datetime
    window_end: datetime
    unique_visitors: int
    conversion_rate: float = Field(..., ge=0.0, le=1.0)
    avg_dwell_by_zone: Dict[str, float]
    current_queue_depth: int
    abandonment_rate: float

class FunnelStage(BaseModel):
    entry_count: int
    zone_visit_count: int
    billing_queue_count: int
    purchase_count: int
    dropoff_entry_to_zone: float
    dropoff_zone_to_queue: float
    dropoff_queue_to_purchase: float

class FunnelResponse(BaseModel):
    store_id: str
    window_start: datetime
    window_end: datetime
    stages: FunnelStage

class HeatmapZone(BaseModel):
    zone_id: str
    visit_frequency: int
    avg_dwell_seconds: float
    normalised_score: float = Field(..., ge=0.0, le=100.0)
    data_confidence: bool

class HeatmapResponse(BaseModel):
    store_id: str
    zones: List[HeatmapZone]
    generated_at: datetime

class AnomalySeverity(str, Enum):
    INFO = "INFO"
    WARN = "WARN"
    CRITICAL = "CRITICAL"

class AnomalyType(str, Enum):
    BILLING_QUEUE_SPIKE = "BILLING_QUEUE_SPIKE"
    CONVERSION_DROP = "CONVERSION_DROP"
    DEAD_ZONE = "DEAD_ZONE"
    STALE_FEED = "STALE_FEED"
    HIGH_ABANDONMENT = "HIGH_ABANDONMENT"

class Anomaly(BaseModel):
    anomaly_id: UUID
    store_id: str
    anomaly_type: AnomalyType
    severity: AnomalySeverity
    description: str
    suggested_action: str
    detected_at: datetime
    zone_id: Optional[str] = None
    metric_value: Optional[float] = None
    threshold: Optional[float] = None

class AnomalyResponse(BaseModel):
    store_id: str
    anomalies: List[Anomaly]
    checked_at: datetime

class StoreHealth(BaseModel):
    store_id: str
    status: Literal["OK", "DEGRADED", "STALE"]
    last_event_at: Optional[datetime] = None
    lag_seconds: Optional[float] = None
    warning: Optional[str] = None

    @model_validator(mode="after")
    def populate_warning(self) -> "StoreHealth":
        if self.lag_seconds is not None and self.lag_seconds > 600:
            self.warning = "STALE_FEED"
        return self

from typing import Any

class StoreLayoutResponse(RootModel[Dict[str, Any]]):
    root: Dict[str, Any]

# Live metrics response can reuse the existing MetricsResponse structure.
# If additional live‑only fields are needed, extend this class.
class LiveMetricsResponse(MetricsResponse):
    pass

class HealthResponse(BaseModel):
    api_version: str
    checked_at: datetime
    stores: List[StoreHealth]
