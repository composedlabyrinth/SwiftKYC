from uuid import UUID
from datetime import datetime

from pydantic import BaseModel, Field, ConfigDict


class DocumentSelectRequest(BaseModel):
    doc_type: str = Field(..., description="AADHAAR, PAN, PASSPORT, VOTER_ID")


class DocumentSelectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    session_id: UUID
    document_id: UUID
    doc_type: str
    next_step: str


class DocumentUploadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    document_id: UUID
    session_id: UUID
    storage_url: str
    next_step: str
    updated_at: datetime


class DocumentNumberRequest(BaseModel):
    """
    Request to save a user-entered PAN/Aadhaar number (before scanning).
    """
    doc_number: str = Field(..., description="User-entered PAN or Aadhaar number")

class DocumentNumberResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    session_id: UUID
    document_id: UUID
    doc_number: str
    next_step: str