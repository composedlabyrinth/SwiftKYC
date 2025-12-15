import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import (
    String,
    Enum as SAEnum,
    DateTime,
    Text,
    ForeignKey,
    Integer,
    Float,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.customer import Customer


class KycStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ABANDONED = "ABANDONED"


class KycStep(str, Enum):
    SELECT_DOC = "SELECT_DOC"
    SCAN_DOC = "SCAN_DOC"
    VALIDATE_DOC = "VALIDATE_DOC"
    SELFIE = "SELFIE"
    KYC_CHECK = "KYC_CHECK"
    COMPLETE = "COMPLETE"


class KycSession(Base):
    __tablename__ = "kyc_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    status: Mapped[KycStatus] = mapped_column(
        SAEnum(KycStatus, name="kyc_status"),
        nullable=False,
        default=KycStatus.IN_PROGRESS,
    )

    current_step: Mapped[KycStep] = mapped_column(
        SAEnum(KycStep, name="kyc_step"),
        nullable=False,
        default=KycStep.SELECT_DOC,
    )

    failure_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # Retry counters per stage (we’ll use them later in logic)
    retries_select: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    retries_scan: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    retries_upload: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    retries_selfie: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    selfie_url: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
    )

    face_match_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    customer: Mapped["Customer"] = relationship(
        back_populates="sessions",
    )

    def __repr__(self) -> str:
        return f"<KycSession id={self.id} status={self.status} step={self.current_step}>"

 