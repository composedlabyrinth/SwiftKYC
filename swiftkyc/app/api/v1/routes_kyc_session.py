from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import re

from app.db.session import get_db
from app.models.customer import Customer
from app.models.kyc_session import KycSession, KycStep, KycStatus
from app.schemas.kyc_session import KycSessionCreateRequest, KycSessionResponse

from app.schemas.kyc_document import (
    DocumentSelectRequest,
    DocumentSelectResponse,
    DocumentUploadResponse,
    DocumentNumberRequest,
    DocumentNumberResponse, 
)
from app.models.kyc_document import KycDocument, DocumentType
from app.utils.normalization import normalize_pan, normalize_aadhaar



router = APIRouter(
    prefix="/kyc",
    tags=["KYC"],
)


@router.post(
    "/session",
    response_model=KycSessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new KYC session for a customer (name + mobile)",
)
async def create_kyc_session(
    payload: KycSessionCreateRequest,
    db: AsyncSession = Depends(get_db),
) -> KycSessionResponse:
    """
    Create or reuse a Customer based on mobile number.
    Store/update both name and mobile.
    Then create a new KYC session.
    """

    # 1. Look up customer by mobile
    result = await db.execute(
        select(Customer).where(Customer.mobile == payload.mobile)
    )
    customer = result.scalar_one_or_none()

    if customer is None:
        # Create a new customer with name + mobile
        customer = Customer(
            mobile=payload.mobile,
            name=payload.name or ""  # ensures NOT NULL
        )
        db.add(customer)
        await db.flush()

    else:
        # Update the customer name if empty or different
        if payload.name and customer.name != payload.name:
            customer.name = payload.name

    # 2. Create KYC session
    kyc_session = KycSession(
        customer_id=customer.id,
    )
    db.add(kyc_session)

    await db.commit()
    await db.refresh(kyc_session)

    return KycSessionResponse(
        session_id=kyc_session.id,
        customer_id=customer.id,
        status=kyc_session.status.value,
        current_step=kyc_session.current_step.value,
        created_at=kyc_session.created_at,
    )



from uuid import UUID
from app.schemas.kyc_session import KycSessionDetailResponse


@router.get(
    "/session/{session_id}",
    response_model=KycSessionDetailResponse,
    summary="Get the current KYC session status"
)
async def get_kyc_session(
    session_id: UUID,
    db: AsyncSession = Depends(get_db)
) -> KycSessionDetailResponse:
    """
    Fetch the KYC session by ID.
    Used by the frontend to poll status and track progress.
    """
    result = await db.execute(
        select(KycSession).where(KycSession.id == session_id)
    )
    kyc_session = result.scalar_one_or_none()

    if not kyc_session:
        raise HTTPException(
            status_code=404,
            detail="KYC session not found",
        )

    
    return KycSessionDetailResponse(
        session_id=kyc_session.id,
        customer_id=kyc_session.customer_id,
        status=kyc_session.status.value,
        current_step=kyc_session.current_step.value,
        retries_select=kyc_session.retries_select,
        retries_scan=kyc_session.retries_scan,
        retries_upload=kyc_session.retries_upload,
        retries_selfie=kyc_session.retries_selfie,
        failure_reason=kyc_session.failure_reason,
        created_at=kyc_session.created_at,
        updated_at=kyc_session.updated_at,
    )


@router.post(
    "/session/{session_id}/select-document",
    response_model=DocumentSelectResponse,
    summary="Select KYC document type"
)
async def select_document_type(
    session_id: UUID,
    payload: DocumentSelectRequest,
    db: AsyncSession = Depends(get_db)
) -> DocumentSelectResponse:

    # 1. Validate session exists
    result = await db.execute(
        select(KycSession).where(KycSession.id == session_id)
    )
    session = result.scalar_one_or_none()

    if not session:
        raise HTTPException(
            status_code=404,
            detail="KYC session not found"
        )

    # 2. Ensure correct current step
    if session.current_step != KycStep.SELECT_DOC:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot select document at step {session.current_step.value}"
        )

    # 3. Validate document type
    try:
        doc_type_enum = DocumentType(payload.doc_type.upper())
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Invalid document type. Allowed: AADHAAR, PAN, PASSPORT, VOTER_ID"
        )

    # 4. Create document record
    doc = KycDocument(
        session_id=session.id,
        doc_type=doc_type_enum
    )

    db.add(doc)

    # 5. Move session to next step
    session.current_step = KycStep.SCAN_DOC

    await db.commit()
    await db.refresh(doc)
    await db.refresh(session)

    return DocumentSelectResponse(
        session_id=session.id,
        document_id=doc.id,
        doc_type=doc.doc_type.value,
        next_step=session.current_step.value
    )

@router.post(
    "/session/{session_id}/enter-doc-number",
    response_model=DocumentNumberResponse,
    summary="Enter PAN/Aadhaar number (before scanning)",
)
async def enter_doc_number(
    session_id: UUID,
    payload: DocumentNumberRequest,
    db: AsyncSession = Depends(get_db),
) -> DocumentNumberResponse:
    """
    Save a user-entered PAN/Aadhaar number for the latest document in this session.
    Performs strict normalization + format validation. If format is valid, number is saved
    and user proceeds to scanning (SCAN_DOC). If invalid, returns descriptive error.
    (No duplicate lookup is performed here — that was intentionally removed.)
    """

    # 1. Validate session exists
    result = await db.execute(select(KycSession).where(KycSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail={"error_code": "SESSION_NOT_FOUND", "message": "KYC session not found."})

    # 2. Must be at SCAN_DOC step (we want user to enter number before scanning)
    if session.current_step != KycStep.SCAN_DOC:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "INVALID_STEP", "message": f"Cannot enter document number at step {session.current_step.value}."},
        )

    # 3. Load latest document for this session
    result = await db.execute(
        select(KycDocument)
        .where(KycDocument.session_id == session_id)
        .order_by(KycDocument.created_at.desc())
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=400, detail={"error_code": "NO_DOCUMENT", "message": "No document record found. Select document type first."})

    # 4. Only support PAN/AADHAAR for manual entry in MVP
    if doc.doc_type not in (DocumentType.PAN, DocumentType.AADHAAR):
        raise HTTPException(
            status_code=400,
            detail={"error_code": "UNSUPPORTED_DOC_TYPE", "message": "Manual entry only supported for PAN and AADHAAR in this endpoint."},
        )

    # 5. Normalize and strictly validate number using helpers + extra checks
    raw = payload.doc_number or ""
    raw = raw.strip()

    if doc.doc_type == DocumentType.PAN:
        normalized = normalize_pan(raw)
        # normalize_pan returns the PAN uppercased with spaces removed if looks good,
        # but it may return the raw input if it didn't match pattern — we enforce pattern here.
        pan_pattern = r"^[A-Z]{5}[0-9]{4}[A-Z]$"
        if not re.fullmatch(pan_pattern, normalized):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "error_code": "INVALID_PAN_FORMAT",
                    "message": "PAN format invalid. Expected 10 chars: 5 letters, 4 digits, 1 letter. Example: 'ABCDE1234F'. Please re-enter.",
                },
            )

    else:  # DocumentType.AADHAAR
        normalized = normalize_aadhaar(raw)
        # ensure exactly 12 digits
        if not re.fullmatch(r"^\d{12}$", normalized):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "error_code": "INVALID_AADHAAR_FORMAT",
                    "message": "Aadhaar format invalid. Expected exactly 12 digits (numbers only). Please re-enter without spaces or dashes.",
                },
            )

    # 6. Save normalized number to document record
    doc.doc_number = normalized

    await db.commit()
    await db.refresh(doc)
    await db.refresh(session)

    # 7. Return success (user stays at SCAN_DOC; next step is to upload & validate the document image)
    return DocumentNumberResponse(
        session_id=session.id,
        document_id=doc.id,
        doc_number=doc.doc_number,
        next_step=session.current_step.value,
    )


from fastapi import File, UploadFile, HTTPException, status
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import re
import logging

from app.schemas.kyc_document import DocumentUploadResponse
from app.utils.storage import save_uploaded_file
from app.utils.ocr import (
    extract_pan_and_name_from_image,
    extract_aadhaar_and_name_from_image,
    name_similarity_enhanced,
    normalize_name_for_match,
)
from app.models.kyc_session import KycSession, KycStep
from app.models.kyc_document import KycDocument, DocumentType
from app.models.customer import Customer
from app.db.session import get_db

logger = logging.getLogger(__name__)


@router.post(
    "/session/{session_id}/validate-document",
    response_model=DocumentUploadResponse,
    summary="Upload document & perform OCR validation (PAN/AADHAAR) and move to next step if matched",
)
async def validate_document(
    session_id: UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db)
) -> DocumentUploadResponse:

    # 1. Validate file type
    if file.content_type not in ("image/jpeg", "image/png"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only JPEG and PNG images are allowed"
        )

    # 2. Load session
    result = await db.execute(select(KycSession).where(KycSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="KYC session not found")

    # 3. Ensure correct step
    if session.current_step != KycStep.SCAN_DOC:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot validate document during step {session.current_step.value}"
        )

    # 4. Fetch latest document record
    result = await db.execute(
        select(KycDocument)
        .where(KycDocument.session_id == session_id)
        .order_by(KycDocument.created_at.desc())
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No document record found. Select document type first."
        )

    # 5. Save file
    saved_path = save_uploaded_file(session_id, file)
    doc.storage_url = saved_path

    # 6. Run OCR using the document's type ONLY
    try:
        if doc.doc_type == DocumentType.PAN:
            ocr = extract_pan_and_name_from_image(saved_path)
        elif doc.doc_type == DocumentType.AADHAAR:
            ocr = extract_aadhaar_and_name_from_image(saved_path)
        else:
            # Unsupported doc types shouldn't reach here for OCR
            # but provide a safe fallback: read raw text only
            try:
                from app.utils.ocr import _easyocr_read  # type: ignore
                raw_text, _ = _easyocr_read(saved_path)
                ocr = {"document_number": None, "name": None, "raw_text": raw_text, "quality_score": 0.0}
            except Exception:
                ocr = {"document_number": None, "name": None, "raw_text": "", "quality_score": 0.0}
    except Exception as e:
        logger.exception("OCR failure for session %s: %s", session_id, e)
        doc.is_valid = False
        doc.quality_score = None
        session.failure_reason = "OCR_ERROR"
        session.current_step = KycStep.SCAN_DOC
        await db.commit()
        await db.refresh(doc)
        await db.refresh(session)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="OCR processing failed. Please try again later.")

    # 7. Save OCR quality score if available
    try:
        doc.quality_score = float(ocr.get("quality_score")) if ocr.get("quality_score") is not None else None
    except Exception:
        doc.quality_score = None

    # 8. Compare OCR number with the entered number
    entered_number = (doc.doc_number or "").strip()
    ocr_number = (ocr.get("document_number") or "").strip() if ocr.get("document_number") else ""

    number_match = False
    detailed_reasons: list[str] = []

    if entered_number and ocr_number:
        if doc.doc_type == DocumentType.PAN:
            norm_entered = re.sub(r"\s+", "", entered_number).upper()
            norm_ocr = re.sub(r"\s+", "", ocr_number).upper()
            number_match = (norm_entered == norm_ocr)
            if not number_match:
                detailed_reasons.append(f"OCR_NUMBER_MISMATCH_PAN entered='{norm_entered}' ocr='{norm_ocr}'")
        elif doc.doc_type == DocumentType.AADHAAR:
            norm_entered = re.sub(r"\D", "", entered_number)
            norm_ocr = re.sub(r"\D", "", ocr_number)
            if len(norm_entered) == 12 and len(norm_ocr) == 12 and norm_entered == norm_ocr:
                number_match = True
            else:
                # fallback accept last-4 match (less strict)
                if len(norm_entered) >= 4 and len(norm_ocr) >= 4 and norm_entered[-4:] == norm_ocr[-4:]:
                    number_match = True
                else:
                    number_match = False
            if not number_match:
                detailed_reasons.append(f"OCR_NUMBER_MISMATCH_AADHAAR entered='{norm_entered}' ocr='{norm_ocr}'")
        else:
            number_match = entered_number == ocr_number
            if not number_match:
                detailed_reasons.append(f"OCR_NUMBER_MISMATCH entered='{entered_number}' ocr='{ocr_number}'")
    else:
        detailed_reasons.append(f"OCR_NUMBER_MISSING entered_present={'yes' if entered_number else 'no'} ocr_present={'yes' if ocr_number else 'no'}")
        number_match = False

    # 9. Compare OCR name with stored customer name using enhanced matcher
    result = await db.execute(select(Customer).where(Customer.id == session.customer_id))
    customer = result.scalar_one_or_none()
    entered_name_raw = (customer.name if customer else "") or ""
    ocr_name_raw = (ocr.get("name") or "") or ""

    # compute similarity metrics
    full_sim, token_sim, combined_sim = name_similarity_enhanced(entered_name_raw, ocr_name_raw)

    NAME_SIM_THRESHOLD = 0.50
    TOKEN_HIGH_ACCEPT = 0.90

    name_match = False
    if entered_name_raw and ocr_name_raw:
        name_match = (combined_sim >= NAME_SIM_THRESHOLD) or (token_sim >= TOKEN_HIGH_ACCEPT)
    else:
        if not entered_name_raw:
            detailed_reasons.append("OCR_NAME_MISSING_ENTERED_NAME_EMPTY")
        if not ocr_name_raw:
            detailed_reasons.append("OCR_NAME_MISSING_OCR_NAME_EMPTY")
        name_match = False

    if not name_match and entered_name_raw and ocr_name_raw:
        detailed_reasons.append(
            "OCR_NAME_MISMATCH "
            f"entered='{normalize_name_for_match(entered_name_raw)}' "
            f"ocr='{normalize_name_for_match(ocr_name_raw)}' "
            f"full_sim={full_sim:.2f} token_sim={token_sim:.2f} combined={combined_sim:.2f}"
        )

    # 10. Final decision — accept only if both match
    if number_match and name_match:
        doc.is_valid = True
        session.current_step = KycStep.SELFIE
        session.failure_reason = None
    else:
        doc.is_valid = False
        session.current_step = KycStep.SCAN_DOC
        if ocr.get("raw_text"):
            raw_len = len(str(ocr.get("raw_text")))
            detailed_reasons.append(f"OCR_RAW_LEN={raw_len}")
        session.failure_reason = ";".join(detailed_reasons) if detailed_reasons else "OCR_MISMATCH"

    # 11. Persist and return
    await db.commit()
    await db.refresh(doc)
    await db.refresh(session)

    return DocumentUploadResponse(
        document_id=doc.id,
        session_id=session.id,
        storage_url=saved_path,
        next_step=session.current_step.value,
        updated_at=session.updated_at,
    )


from fastapi import File, UploadFile, HTTPException, status
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.utils.storage import save_selfie_file
from app.workers.connection import selfie_queue
from app.models.kyc_document import KycDocument

@router.post(
    "/session/{session_id}/selfie",
    response_model=KycSessionDetailResponse,
    summary="Upload selfie and queue face validation",
)
async def upload_selfie(
    session_id: UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> KycSessionDetailResponse:
    # 1. Validate file type
    if file.content_type not in ["image/jpeg", "image/png"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only JPEG and PNG images are allowed for selfie.",
        )

    # 2. Load session
    result = await db.execute(select(KycSession).where(KycSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="KYC session not found.")

    # 3. Must be at SELFIE step
    if session.current_step != KycStep.SELFIE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot upload selfie during step {session.current_step.value}. Complete document validation first.",
        )

    # 4. Ensure latest document is found and marked valid
    result = await db.execute(
        select(KycDocument)
        .where(KycDocument.session_id == session_id)
        .order_by(KycDocument.created_at.desc())
    )
    latest_doc = result.scalar_one_or_none()
    if not latest_doc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No document found for this session.")
    if latest_doc.is_valid is not True:
        # explicit check (None or False both fail)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Document not validated. Please re-upload or fix your document before uploading selfie.",
        )

    # 5. Save selfie file
    selfie_path = save_selfie_file(session_id, file)
    session.selfie_url = selfie_path
    session.face_match_score = None
    session.failure_reason = None

    # Move to KYC_CHECK (background face match)
    session.current_step = KycStep.KYC_CHECK

    await db.commit()
    await db.refresh(session)

    # 6. Enqueue async face validation job
    selfie_queue.enqueue(
        "app.workers.tasks.validate_selfie_job",
        str(session.id),
    )

    return KycSessionDetailResponse(
        session_id=session.id,
        customer_id=session.customer_id,
        status=session.status.value,
        current_step=session.current_step.value,
        retries_select=session.retries_select,
        retries_scan=session.retries_scan,
        retries_upload=session.retries_upload,
        retries_selfie=session.retries_selfie,
        failure_reason=session.failure_reason,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )
