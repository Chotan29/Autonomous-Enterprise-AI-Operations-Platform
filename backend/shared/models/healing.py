import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.core.database import Base
from backend.shared.models.base import UUIDMixin, TimestampMixin, TenantMixin


class HealingAction(Base, UUIDMixin, TimestampMixin, TenantMixin):
    __tablename__ = "healing_actions"

    alert_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("alerts.id"), nullable=True
    )
    incident_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("incidents.id"), nullable=True
    )
    # action_type: restart_service | clear_disk | rollback_config | reboot_device | block_ip
    action_type: Mapped[str] = mapped_column(String(100), nullable=False)
    # executor_type: ssh | winrm | ansible | snmp | rest | terraform
    executor_type: Mapped[str] = mapped_column(String(50), nullable=False)
    target_device_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id"), nullable=True
    )
    target_server_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    parameters: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    ai_reasoning: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # risk_level: low | medium | high | critical
    risk_level: Mapped[str] = mapped_column(String(20), default="medium")
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=True)
    # status: pending | approved | rejected | running | success | failed | rolled_back
    status: Mapped[str] = mapped_column(String(50), default="pending", index=True)
    approved_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    execution_log: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rollback_plan: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    def __repr__(self) -> str:
        return f"<HealingAction {self.action_type} status={self.status}>"


class Playbook(Base, UUIDMixin, TimestampMixin, TenantMixin):
    __tablename__ = "playbooks"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    trigger_conditions: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    steps: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    is_autonomous: Mapped[bool] = mapped_column(Boolean, default=False)
    risk_level: Mapped[str] = mapped_column(String(20), default="medium")
    estimated_duration_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    success_criteria: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    rollback_steps: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    def __repr__(self) -> str:
        return f"<Playbook {self.name}>"
