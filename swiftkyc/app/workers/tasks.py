import asyncio
from uuid import UUID
from sqlalchemy import select

from app.db.session import async_session_maker
from app.models.kyc_document import KycDocument
from app.models.kyc_session import KycSession, KycStep, KycStatus
from app.models.customer import Customer
from app.services.face_validation import assess_selfie_match


# ---------------------------------------------------------
# Helper to run async functions safely inside RQ 
# ---------------------------------------------------------
def run_async(coro):
    """
    RQ workers run in a non-async thread.
    We must carefully manage event loops.
    """
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    if loop.is_running():
        return asyncio.ensure_future(coro)
    else:
        return loop.run_until_complete(coro)


# ---------------------------------------------------------
# DOCUMENT VALIDATION JOB  (DISABLED — API Now Does OCR)
# ---------------------------------------------------------
def validate_document_job(document_id: str):
    """
    This job is intentionally disabled because:
    - OCR & document validation now happen inside the API endpoint.
    - Worker MUST NOT override doc.is_valid or session.current_step.
    We keep this function only for backward compatibility with RQ queues.
    """
    return run_async(_noop_document_job_async(UUID(document_id)))


async def _noop_document_job_async(document_id: UUID):
    """
    Previously used to validate documents.
    Now does nothing except ensuring the document exists,
    so the RQ queue does not break if it's still enqueued.
    """
    async with async_session_maker() as db:
        # Load document just to verify existence
        result = await db.execute(select(KycDocument).where(KycDocument.id == document_id))
        doc = result.scalar_one_or_none()
        # We do not modify doc or session anymore
        return  # NO-OP


# ---------------------------------------------------------
# SELFIE VALIDATION JOB
# ---------------------------------------------------------
def validate_selfie_job(session_id: str):
    """Entry from RQ"""
    return run_async(_validate_selfie_job_async(UUID(session_id)))


async def _validate_selfie_job_async(session_id: UUID):
    """
    STRICT RULES:

    1. Latest document must be valid (doc.is_valid == True)
    2. Session must be at KYC_CHECK
    3. Selfie must exist

    If any fail → DO NOT APPROVE. DO NOT FACE MATCH.
    """

    async with async_session_maker() as db:

        # Load session
        result = await db.execute(select(KycSession).where(KycSession.id == session_id))
        session = result.scalar_one_or_none()
        if not session:
            return

        # Ensure correct step
        if session.current_step != KycStep.KYC_CHECK:
            session.failure_reason = "INVALID_STATE_FOR_SELFIE_VALIDATION"
            await db.commit()
            return

        if not session.selfie_url:
            session.failure_reason = "SELFIE_NOT_FOUND"
            session.current_step = KycStep.SELFIE
            await db.commit()
            return

        # Load latest document
        result = await db.execute(
            select(KycDocument)
            .where(KycDocument.session_id == session.id)
            .order_by(KycDocument.created_at.desc())
        )
        doc = result.scalar_one_or_none()

        if not doc:
            session.failure_reason = "DOCUMENT_NOT_FOUND"
            session.current_step = KycStep.SELFIE
            await db.commit()
            return

        # ---- ENFORCED GUARD: Document must be valid ----
        if doc.is_valid is not True:
            session.failure_reason = "DOC_NOT_VALID"
            session.current_step = KycStep.SELFIE
            await db.commit()
            return
        # ------------------------------------------------

        # FACE MATCH NOW SAFE TO RUN
        match = assess_selfie_match(
            doc_image_path=doc.storage_url,
            selfie_image_path=session.selfie_url,
        )

        session.face_match_score = match.score

        if not match.is_match:
            session.retries_selfie += 1

            if session.retries_selfie >= 3:
                session.status = KycStatus.REJECTED
                session.failure_reason = (
                    match.reason or "Selfie does not match."
                )
                session.current_step = KycStep.KYC_CHECK
            else:
                session.failure_reason = (
                    match.reason or "Selfie does not match. Please retake."
                )
                session.current_step = KycStep.SELFIE

        else:
            # APPROVE SESSION (document is valid AND face match ok)
            session.status = KycStatus.APPROVED
            session.failure_reason = None
            session.current_step = KycStep.COMPLETE

        await db.commit()
