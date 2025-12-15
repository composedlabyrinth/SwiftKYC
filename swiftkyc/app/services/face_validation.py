from dataclasses import dataclass
from pathlib import Path

from PIL import Image, UnidentifiedImageError

# Size limits (bytes)
MIN_SELFIE_SIZE = 30 * 1024         # 30 KB
MAX_SELFIE_SIZE = 4 * 1024 * 1024    # 4 MB


@dataclass
class FaceValidationResult:
    is_match: bool
    score: float
    reason: str | None = None


def _human_size(num_bytes: int) -> str:
    """Return a human friendly size string (KB/MB)."""
    if num_bytes >= 1024 * 1024:
        return f"{num_bytes / (1024 * 1024):.2f} MB"
    return f"{num_bytes / 1024:.0f} KB"


def assess_selfie_match(
    doc_image_path: str,
    selfie_image_path: str,
) -> FaceValidationResult:
    """
    MVP face match with selfie file-size rejection.

    Behavior:
    - If document or selfie files don't exist -> reject with reason.
    - If selfie file cannot be opened as an image -> reject with reason.
    - If selfie file size is < MIN_SELFIE_SIZE or > MAX_SELFIE_SIZE -> reject with reason.
    - Otherwise, stub face match (always succeed with score 0.9 for MVP).
    """

    doc_path = Path(doc_image_path)
    selfie_path = Path(selfie_image_path)

    if not doc_path.exists() or not selfie_path.exists():
        return FaceValidationResult(
            is_match=False,
            score=0.0,
            reason="Document or selfie image not found on server.",
        )

    # Ensure we can stat the selfie file to get its size
    try:
        selfie_size = selfie_path.stat().st_size
    except OSError as exc:
        return FaceValidationResult(
            is_match=False,
            score=0.0,
            reason=f"Unable to read selfie file size: {exc}",
        )

    # Size-based rejection
    if selfie_size < MIN_SELFIE_SIZE:
        return FaceValidationResult(
            is_match=False,
            score=0.0,
            reason=(
                "Selfie rejected: file too small "
                f"({_human_size(selfie_size)} < {_human_size(MIN_SELFIE_SIZE)})."
            ),
        )

    if selfie_size > MAX_SELFIE_SIZE:
        return FaceValidationResult(
            is_match=False,
            score=0.0,
            reason=(
                "Selfie rejected: file too large "
                f"({_human_size(selfie_size)} > {_human_size(MAX_SELFIE_SIZE)})."
            ),
        )

    # Lightweight Pillow validation: ensure it's a readable image (JPEG/PNG or other)
    try:
        with Image.open(selfie_path) as img:
            # verify() helps detect truncated or invalid images
            img.verify()
    except (UnidentifiedImageError, OSError) as exc:
        return FaceValidationResult(
            is_match=False,
            score=0.0,
            reason=f"Selfie rejected: image file unreadable or invalid ({exc}).",
        )

    # TODO: replace with real face matching logic
    # For MVP, always succeed with 0.9 score:
    return FaceValidationResult(
        is_match=True,
        score=0.9,
        reason=None,
    )
