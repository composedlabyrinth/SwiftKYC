import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import (
    String,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class DocumentType(str, Enum):
    AADHAAR = "AADHAAR"
    PAN = "PAN"
    PASSPORT = "PASSPORT"
    VOTER_ID = "VOTER_ID"


class KycDocument(Base):
    __tablename__ = "kyc_documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("kyc_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    doc_type: Mapped[DocumentType] = mapped_column(
        SAEnum(DocumentType, name="document_type_enum"),
        nullable=False,
    )

    storage_url: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    doc_number: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    is_valid: Mapped[bool | None] = mapped_column(default=None)

    quality_score: Mapped[float | None] = mapped_column(nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False,
    )

    # Relationship to session
    session = relationship("KycSession", backref="documents")
