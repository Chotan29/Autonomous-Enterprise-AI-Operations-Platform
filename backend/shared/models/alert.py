import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.core.database import Base
from backend.shared.models.base import UUIDMixin, TimestampMixin, TenantMixin


class Alert(Base, UUIDMixin, TimestampMixin, TenantMixin):
    __tablename__ = "alerts"

    source: Mapped[str] = mapped_column(String(100), nullable=False)
    source_device_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id"), nullable=True, index=True
    )
    source_host: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    alert_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    # category: noc | soc | server | physec
    category: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    # severity: critical | high | medium | low | info
    severity: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    priority: Mapped[int] = mapped_column(Integer, default=50)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    raw_event: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    enrichment: Mapped[dict] = mapped_column(JSON, default=dict)
    # status: new | acknowledged | in_progress | resolved | suppressed
    status: Mapped[str] = mapped_column(String(50), default="new", index=True)
    assigned_to: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    acknowledged_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ai_rca: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ai_suggestion: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ai_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    is_ai_resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    parent_alert_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("alerts.id"), nullable=True
    )
    correlation_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    tags: Mapped[list] = mapped_column(JSON, default=list)

    source_device: Mapped[Optional["Device"]] = relationship("Device")

    def __repr__(self) -> str:
        return f"<Alert {self.alert_type} severity={self.severity} status={self.status}>"


class Incident(Base, UUIDMixin, TimestampMixin, TenantMixin):
    __tablename__ = "incidents"

    incident_number: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    priority: Mapped[str] = mapped_column(String(20), default="medium")
    # status: open | investigating | mitigated | resolved | closed
    status: Mapped[str] = mapped_column(String(50), default="open", index=True)
    impact: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    assigned_to: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    assigned_team: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    sla_deadline: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    root_cause: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    resolution: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ai_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ai_timeline: Mapped[list] = mapped_column(JSON, default=list)
    mitre_tactics: Mapped[list] = mapped_column(JSON, default=list)
    mitre_techniques: Mapped[list] = mapped_column(JSON, default=list)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    related_alerts: Mapped[list] = mapped_column(JSON, default=list)

    timeline: Mapped[list["IncidentTimeline"]] = relationship(
        "IncidentTimeline", back_populates="incident", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Incident {self.incident_number} severity={self.severity}>"


class IncidentTimeline(Base, UUIDMixin):
    __tablename__ = "incident_timeline"

    incident_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    action_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    incident: Mapped["Incident"] = relationship("Incident", back_populates="timeline")
