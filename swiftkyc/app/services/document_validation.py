import os
from typing import Literal

import cv2
import numpy as np


class DocumentQualityResult:
    def __init__(
        self,
        is_valid: bool,
        quality_score: float,
        reason: str | None = None,
    ):
        self.is_valid = is_valid
        self.quality_score = quality_score
        self.reason = reason


def _load_image(path: str):
    # Make sure path is absolute
    if not os.path.isabs(path):
        path = os.path.join(os.getcwd(), path)

    image = cv2.imread(path)

    if image is None:
        raise ValueError(f"Could not read image at {path}")

    return image


def evaluate_document_quality(path: str) -> DocumentQualityResult:
    """
    MVP quality checks:
    - Blur: variance of Laplacian
    - Brightness: mean intensity
    - Glare: proportion of very bright pixels
    - Edges: amount of edges (Canny)
    """

    image = _load_image(path)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # ---- 1. Blur detection ----
    laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
    # Heuristic thresholds; can be tuned:
    BLUR_THRESHOLD = 100.0

    if laplacian_var < BLUR_THRESHOLD:
        return DocumentQualityResult(
            is_valid=False,
            quality_score=float(laplacian_var),
            reason="Image is blurry – please hold the camera steady and re-scan.",
        )

    # ---- 2. Brightness check ----
    mean_intensity = float(np.mean(gray))
    TOO_DARK = 60.0
    TOO_BRIGHT = 200.0

    if mean_intensity < TOO_DARK:
        return DocumentQualityResult(
            is_valid=False,
            quality_score=mean_intensity,
            reason="Image is too dark – please increase lighting and re-scan.",
        )

    if mean_intensity > TOO_BRIGHT:
        return DocumentQualityResult(
            is_valid=False,
            quality_score=mean_intensity,
            reason="Image is too bright – please avoid direct glare and re-scan.",
        )

    # ---- 3. Glare detection ----
    # Count pixels that are almost white
    glare_mask = gray > 240
    glare_ratio = float(np.mean(glare_mask))

    GLARE_MAX_RATIO = 0.12  # 12% of pixels extremely bright

    if glare_ratio > GLARE_MAX_RATIO:
        return DocumentQualityResult(
            is_valid=False,
            quality_score=glare_ratio,
            reason="Too much glare on the document – tilt the document or move away from direct light.",
        )

    # ---- 4. Edge / contrast check ----
    edges = cv2.Canny(gray, 100, 200)
    edge_ratio = float(np.mean(edges > 0))

    MIN_EDGE_RATIO = 0.01  # At least 1% edge pixels

    if edge_ratio < MIN_EDGE_RATIO:
        return DocumentQualityResult(
            is_valid=False,
            quality_score=edge_ratio,
            reason="Document edges not clearly visible – ensure the full document is inside the frame.",
        )

    # If all checks passed, document is acceptable
    # For quality_score we can combine blur + edge info as a simple heuristic:
    quality_score = float(laplacian_var)

    return DocumentQualityResult(
        is_valid=True,
        quality_score=quality_score,
        reason=None,
    )
