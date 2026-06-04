import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.database import Base
from backend.shared.models.base import UUIDMixin, TimestampMixin, TenantMixin


class KnowledgeDocument(Base, UUIDMixin, TimestampMixin, TenantMixin):
    __tablename__ = "knowledge_documents"

    title: Mapped[str] = mapped_column(String(500), nullable=False)
    source_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    source_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    file_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # status: pending | processing | indexed | failed
    status: Mapped[str] = mapped_column(String(50), default="pending")
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    embedding_model: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    indexed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    tags: Mapped[list] = mapped_column(__import__("sqlalchemy").JSON, default=list)
    metadata_: Mapped[dict] = mapped_column(__import__("sqlalchemy").JSON, default=dict, name="metadata")
