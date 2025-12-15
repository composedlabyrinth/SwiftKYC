from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class KycSessionCreateRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=100, description="Customer full name")
    mobile: str = Field(..., pattern=r"^\d{10}$", description="10-digit mobile number")

class KycSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    session_id: UUID
    customer_id: UUID
    status: str
    current_step: str
    created_at: datetime


class CustomerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    mobile: str
    email: str | None = None
    created_at: datetime

class KycSessionDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    session_id: UUID
    customer_id: UUID
    status: str
    current_step: str
    retries_select: int
    retries_scan: int
    retries_upload: int
    retries_selfie: int
    failure_reason: str | None = None
    created_at: datetime
    updated_at: datetime
