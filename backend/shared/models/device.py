import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger, Boolean, DateTime, Float, ForeignKey,
    Integer, JSON, String, Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, INET, MACADDR, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.core.database import Base
from backend.shared.models.base import UUIDMixin, TimestampMixin, TenantMixin


class DeviceType(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "device_types"

    vendor: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    os_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    snmp_oids: Mapped[dict] = mapped_column(JSON, default=dict)
    driver_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)


class Device(Base, UUIDMixin, TimestampMixin, TenantMixin):
    __tablename__ = "devices"

    device_type_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("device_types.id"), nullable=True
    )
    hostname: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    display_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    ip_address: Mapped[str] = mapped_column(String(45), nullable=False, index=True)
    management_ip: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    mac_address: Mapped[Optional[str]] = mapped_column(String(17), nullable=True)
    serial_number: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    asset_tag: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    location: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    site_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    rack_unit: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    vendor: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    model: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    # Status: online | offline | degraded | maintenance | unknown
    status: Mapped[str] = mapped_column(String(50), default="unknown", index=True)
    snmp_version: Mapped[str] = mapped_column(String(10), default="v2c")
    snmp_community: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    snmp_config: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    ssh_config: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    api_config: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    os_version: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    firmware_version: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    uptime_seconds: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    last_seen: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_poll: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    discovery_method: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    custom_fields: Mapped[dict] = mapped_column(JSON, default=dict)
    is_managed: Mapped[bool] = mapped_column(Boolean, default=True)

    # AI-enriched fields
    ai_health_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_cpu_util: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    last_mem_util: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    last_temperature: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Relationships
    device_type: Mapped[Optional["DeviceType"]] = relationship("DeviceType")
    interfaces: Mapped[list["DeviceInterface"]] = relationship(
        "DeviceInterface", back_populates="device", cascade="all, delete-orphan"
    )
    configs: Mapped[list["DeviceConfig"]] = relationship(
        "DeviceConfig", back_populates="device", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Device {self.hostname} ({self.ip_address})>"


class DeviceInterface(Base, UUIDMixin):
    __tablename__ = "device_interfaces"

    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    if_index: Mapped[int] = mapped_column(Integer, nullable=False)
    if_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    if_alias: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    if_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    speed_bps: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    mac_address: Mapped[Optional[str]] = mapped_column(String(17), nullable=True)
    ip_addresses: Mapped[list] = mapped_column(JSON, default=list)
    admin_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    oper_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    mtu: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    in_octets: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    out_octets: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    in_errors: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    out_errors: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    last_updated: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    device: Mapped["Device"] = relationship("Device", back_populates="interfaces")


class DeviceConfig(Base, UUIDMixin):
    __tablename__ = "device_configs"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    config_type: Mapped[str] = mapped_column(String(50), default="running")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_baseline: Mapped[bool] = mapped_column(Boolean, default=False)
    backup_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    backed_up_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    storage_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    diff_from_prev: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    device: Mapped["Device"] = relationship("Device", back_populates="configs")


class DeviceNeighbor(Base, UUIDMixin):
    __tablename__ = "device_neighbors"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    local_device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )
    local_port: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    remote_device_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id"), nullable=True
    )
    remote_port: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    remote_hostname: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    remote_ip: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    protocol: Mapped[str] = mapped_column(String(20), default="lldp")
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
