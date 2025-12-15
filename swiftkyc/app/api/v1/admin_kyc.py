# app/api/v1/admin_kyc.py
from datetime import datetime, timedelta
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.kyc_session import KycSession, KycStatus, KycStep
from app.models.kyc_document import KycDocument, DocumentType

router = APIRouter(prefix="/admin/kyc", tags=["admin_kyc"])


# ----------- Response Models -----------
class KycSessionListItem(BaseModel):
    session_id: UUID
    customer_id: UUID
    status: str
    current_step: str
    created_at: datetime
    updated_at: datetime
    primary_doc_type: Optional[str] = None


class KycSessionDetail(BaseModel):
    session_id: UUID
    customer_id: UUID
    status: str
    current_step: str
    failure_reason: Optional[str] = None
    retries_select: int
    retries_scan: int
    retries_upload: int
    retries_selfie: int
    selfie_url: Optional[str] = None
    face_match_score: Optional[float] = None
    created_at: datetime
    updated_at: datetime
    documents: List[dict]


# ----------- Helpers -----------
def parse_doc_type_or_400(doc_type: Optional[str]) -> Optional[DocumentType]:
    if doc_type is None:
        return None
    try:
        return DocumentType(doc_type.upper())
    except ValueError:
        raise HTTPException(
            400,
            detail=f"Invalid doc_type '{doc_type}'. Allowed: AADHAAR, PAN, PASSPORT, VOTER_ID",
        )


# ----------- LIST SESSIONS -----------
@router.get("/sessions", response_model=List[KycSessionListItem])
async def list_sessions(
    status: Optional[str] = Query(None),
    doc_type: Optional[str] = Query(None),
    created_from: Optional[datetime] = Query(None),
    created_to: Optional[datetime] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    conditions = []
    doc_type_enum = parse_doc_type_or_400(doc_type)

    stmt = select(KycSession).outerjoin(KycDocument)

    # Status filter
    if status:
        try:
            _ = KycStatus(status)
        except ValueError:
            raise HTTPException(400, "Invalid status. Use: IN_PROGRESS, APPROVED, REJECTED, ABANDONED")
        conditions.append(KycSession.status == status)

    # Document type filter
    if doc_type_enum:
        conditions.append(KycDocument.doc_type == doc_type_enum)

    # ----------- DATE FILTER  -----------
    if created_from and created_to:
        # normalize to same-day filter if dates match
        if created_from.date() == created_to.date():
            start = datetime.combine(created_from.date(), datetime.min.time())
            end = datetime.combine(created_from.date(), datetime.max.time())
            conditions.append(KycSession.created_at >= start)
            conditions.append(KycSession.created_at <= end)
        else:
            conditions.append(KycSession.created_at >= created_from)
            conditions.append(KycSession.created_at <= created_to)
    elif created_from:
        conditions.append(KycSession.created_at >= created_from)
    elif created_to:
        conditions.append(KycSession.created_at <= created_to)

    if conditions:
        stmt = stmt.where(and_(*conditions))

    stmt = stmt.order_by(KycSession.created_at.desc()).distinct()

    result = await db.execute(stmt)
    sessions = result.scalars().all()

    out = []
    for s in sessions:
        # Get latest doc for primary_doc_type
        doc_stmt = (
            select(KycDocument.doc_type)
            .where(KycDocument.session_id == s.id)
            .order_by(KycDocument.created_at.desc())
            .limit(1)
        )
        doc_res = await db.execute(doc_stmt)
        doc_row = doc_res.scalar_one_or_none()

        doc_type_value = doc_row.value if hasattr(doc_row, "value") else str(doc_row) if doc_row else None

        out.append(
            KycSessionListItem(
                session_id=s.id,
                customer_id=s.customer_id,
                status=s.status.value,
                current_step=s.current_step.value,
                created_at=s.created_at,
                updated_at=s.updated_at,
                primary_doc_type=doc_type_value,
            )
        )

    return out


# ----------- SESSION DETAIL -----------
@router.get("/sessions/{session_id}", response_model=KycSessionDetail)
async def get_session_detail(session_id: UUID, db: AsyncSession = Depends(get_db)):
    stmt = select(KycSession).where(KycSession.id == session_id)
    res = await db.execute(stmt)
    session = res.scalar_one_or_none()

    if not session:
        raise HTTPException(404, "Session not found")

    doc_stmt = (
        select(KycDocument)
        .where(KycDocument.session_id == session.id)
        .order_by(KycDocument.created_at.desc())
    )
    docs_res = await db.execute(doc_stmt)
    docs = docs_res.scalars().all()

    doc_list = []
    for d in docs:
        doc_list.append(
            {
                "document_id": d.id,
                "doc_type": d.doc_type.value,
                "doc_number": d.doc_number,
                "storage_url": d.storage_url,
                "is_valid": d.is_valid,
                "quality_score": d.quality_score,
                "created_at": d.created_at,
            }
        )

    return KycSessionDetail(
        session_id=session.id,
        customer_id=session.customer_id,
        status=session.status.value,
        current_step=session.current_step.value,
        failure_reason=session.failure_reason,
        retries_select=session.retries_select,
        retries_scan=session.retries_scan,
        retries_upload=session.retries_upload,
        retries_selfie=session.retries_selfie,
        selfie_url=session.selfie_url,
        face_match_score=session.face_match_score,
        created_at=session.created_at,
        updated_at=session.updated_at,
        documents=doc_list,
    )


# ----------- APPROVE SESSION (UPDATED) -----------
@router.post("/sessions/{session_id}/approve")
async def approve_session(session_id: UUID, db: AsyncSession = Depends(get_db)):
    stmt = select(KycSession).where(KycSession.id == session_id)
    res = await db.execute(stmt)
    session = res.scalar_one_or_none()

    if not session:
        raise HTTPException(404, "Session not found")

    session.status = KycStatus.APPROVED
    session.current_step = KycStep.COMPLETE 
    session.failure_reason = None

    await db.commit()
    await db.refresh(session)

    return {"session_id": session.id, "status": session.status.value, "current_step": session.current_step.value}


# ----------- REJECT SESSION -----------
@router.post("/sessions/{session_id}/reject")
async def reject_session(session_id: UUID, db: AsyncSession = Depends(get_db)):
    stmt = select(KycSession).where(KycSession.id == session_id)
    res = await db.execute(stmt)
    session = res.scalar_one_or_none()

    if not session:
        raise HTTPException(404, "Session not found")

    session.status = KycStatus.REJECTED
    session.current_step = KycStep.KYC_CHECK
    if not session.failure_reason:
        session.failure_reason = "Manually rejected by admin"

    await db.commit()
    await db.refresh(session)

    return {"session_id": session.id, "status": session.status.value}
