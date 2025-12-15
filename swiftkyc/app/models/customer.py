import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, List

from sqlalchemy import String, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.kyc_session import KycSession


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    name: Mapped[str | None] = mapped_column(
        String(200),
        nullable=False,
        default="",
    )

    mobile: Mapped[str] = mapped_column(
        String(15),
        unique=True,
        nullable=False,
        index=True,
    )

    email: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    sessions: Mapped[list["KycSession"]] = relationship(
        back_populates="customer"
    )

    def __repr__(self) -> str:
        return f"<Customer id={self.id} mobile={self.mobile}>"