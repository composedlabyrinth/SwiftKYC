# app/schemas/admin_kyc.py
from uuid import UUID
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class AdminKycSessionItem(BaseModel):
    session_id: UUID
    customer_id: UUID
    status: str
    current_step: str
    created_at: datetime
    updated_at: datetime
    latest_document_type: Optional[str] = None


class AdminKycSessionListResponse(BaseModel):
    items: List[AdminKycSessionItem]
    total: int


class AdminKycSessionDetailDocument(BaseModel):
    document_id: UUID
    doc_type: str
    doc_number: Optional[str] = None
    is_valid: Optional[bool] = None
    storage_url: Optional[str] = None
    created_at: datetime


class AdminKycSessionDetailResponse(BaseModel):
    session_id: UUID
    customer_id: UUID
    status: str
    current_step: str
    failure_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    documents: List[AdminKycSessionDetailDocument]


class AdminRejectRequest(BaseModel):
    reason: Optional[str] = None
