# app/utils/ocr.py
"""
OCR utilities using EasyOCR for SwiftKYC.

- Option A behaviour (per your choice): extract ONLY document number + name.
- Provides:
    - extract_pan_and_name_from_image(path)
    - extract_aadhaar_and_name_from_image(path)
    - normalize_name_for_match(name)
    - name_similarity_enhanced(a, b)
"""

from typing import List, Tuple, Dict, Optional
import re
from difflib import SequenceMatcher
from statistics import mean
import logging

logger = logging.getLogger(__name__)

try:
    import easyocr
except Exception as e:
    raise RuntimeError(
        "easyocr is required for OCR but is not importable. "
        "Install easyocr and torch in your venv."
    ) from e

# Initialize reader once (CPU mode for portability).
# Use English and Hindi (helps with Aadhaar cards).
_reader = easyocr.Reader(["en", "hi"], gpu=False)


def _clean_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _avg_confidences(confidences: List[float]) -> float:
    if not confidences:
        return 0.0
    try:
        # easyocr returns conf either 0..1 or 0..100 depending on version; normalize
        norm = [c if c <= 1.0 else c / 100.0 for c in confidences]
        return float(mean(norm))
    except Exception:
        return 0.0


def _easyocr_read(image_path: str) -> Tuple[str, List[Tuple[str, float]]]:
    """
    Read image and return (raw_text, segments)
    segments: List of (text, confidence) in reading order.
    """
    results = _reader.readtext(image_path, detail=1)
    texts_and_conf: List[Tuple[str, float]] = []
    for item in results:
        # item: (bbox, text, confidence)
        if len(item) >= 3:
            text = (item[1] or "").strip()
            conf = float(item[2]) if item[2] is not None else 0.0
            if text:
                texts_and_conf.append((text, conf))
    raw_text = "\n".join([t for t, _ in texts_and_conf]) if texts_and_conf else ""
    return raw_text, texts_and_conf


# --- Heuristic lists & patterns ---

# Words / phrases that identify headers and must not be treated as names
HEADER_PATTERNS = [
    # English official headers (and frequent OCR corruptions)
    "govt", "govt of india", "government", "government of india",
    "income tax", "income tax department", "income", "tax", "department",
    "permanent account number", "permanent account number card", "account number card",
    "authority", "income tax department", "minor",

    # Hindi / Devanagari phrases (lowercased when checking)
    "भारत", "सरकार", "आयकर", "आयकर विभाग", "आयकरविभाग", "मेरी पहचान",

    # Common OCR corruptions observed in samples
    "govl of indla", "governyen0", "incone", "incnne", "taydeparil", "taydeparilent",
    "inc0me", "indla", "g0vt", "g0vernment"
]

# Tokens that commonly appear as labels for name in PAN/Aadhaar
NAME_LABELS = {"name", "name:", "name /", "name/", "नाम", "नाम:", "नाम /", "नाम/"}

# Words that if present make the segment obviously non-name
_BAD_NAME_KEYWORDS = {
    "govt", "government", "india", "income", "tax", "authority",
    "unique", "number", "aadhaar", "card", "pan", "male", "female",
    "date", "dob", "scanned", "scanned by", "proof", "identity",
    "permanent", "department", "signature", "qr", "xml", "issued",
    "aadhar", "address", "mobile", "vid", "father", "father's", "father"
}

# Common honorifics to allow/recognize
_HONORIFICS = {"mr", "mrs", "md", "mohd", "mohammed", "mohammad", "md.", "dr", "shri", "smt"}


# --- PAN misread mapping for digits/letters in digit positions ---
_PAN_MISREAD_MAP = {
    "O": "0", "Q": "0", "D": "0",
    "I": "1", "L": "1", "Z": "2",
    "S": "5", "B": "8", "G": "6",
    "T": "7",
}


def _normalize_token(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _is_header_text(text: str) -> bool:
    if not text:
        return False
    tl = text.lower()
    for pat in HEADER_PATTERNS:
        if pat in tl:
            return True
    return False


def _looks_like_name(text: str) -> bool:
    """
    Conservative heuristic to decide if a text segment is likely a personal name.
    - rejects header patterns
    - rejects segments with digits (very strict)
    - requires 2..5 alphabetic tokens of reasonable length
    """
    if not text:
        return False

    # Keep only letters and spaces for token decisions
    alpha_only = re.sub(r"[^A-Za-z\s]", " ", text).strip()
    if not alpha_only:
        return False

    tl = alpha_only.lower()

    # Never treat headers as names
    if _is_header_text(tl):
        return False

    # Reject if contains bad keywords
    for bad in _BAD_NAME_KEYWORDS:
        if bad in tl:
            return False

    # Reject if there are digits in original text (names shouldn't contain digits)
    digit_count = sum(ch.isdigit() for ch in text)
    if digit_count > 0:
        return False

    # Token rules: require 2..5 tokens, each token length >=2 generally
    tokens = [tok for tok in [t.strip() for t in tl.split()] if len(tok) >= 2]
    if len(tokens) < 2:
        return False
    if len(tokens) > 6:
        return False

    # Reject if first token is a known non-name starter (header-like)
    first = tokens[0]
    if first in {
        "income", "inccone", "incnne", "govt", "govl", "government", "bharat", "permanent", "account"
    }:
        return False

    # Looks plausible as a name
    return True


# --- PAN extraction helpers ---


def _attempt_pan_from_compact(compact: str) -> Optional[str]:
    """
    Try to find PAN-like pattern in compact uppercase string.
    1) strict pattern [A-Z]{5}[0-9]{4}[A-Z]
    2) sliding-window with common misread corrections in numeric positions
    """
    if not compact:
        return None
    compact = compact.upper()

    # Strict match
    m = re.search(r"[A-Z]{5}[0-9]{4}[A-Z]", compact)
    if m:
        return m.group(0)

    # Sliding window + targeted fixes for positions 5..8 (digits)
    for i in range(0, max(1, len(compact) - 9)):
        seg = compact[i : i + 10]
        if len(seg) < 10:
            continue
        seg_list = list(seg)
        for pos in range(5, 9):
            ch = seg_list[pos]
            if ch.isalpha() and ch in _PAN_MISREAD_MAP:
                seg_list[pos] = _PAN_MISREAD_MAP[ch]
        candidate = "".join(seg_list)
        if re.match(r"[A-Z]{5}[0-9]{4}[A-Z]", candidate):
            return candidate
    return None


# --- Main extractors ---


def extract_pan_and_name_from_image(image_path: str) -> Dict:
    """
    Returns dict:
    {
      "document_number": <PAN or None>,
      "name": <Name or None>,
      "raw_text": <raw OCR text>,
      "quality_score": <0..1 float>
    }

    Logic:
    - read OCR segments
    - find PAN index (first segment that matches PAN pattern in compacted version)
    - search for name label 'name' or 'नाम' after PAN index; prefer the immediate next valid segment
    - fallback: first plausible name-looking segment after PAN index
    """
    raw_text, segments = _easyocr_read(image_path)
    combined_text = _clean_text(raw_text)
    quality_score = _avg_confidences([c for _, c in segments]) if segments else 0.0

    # document number (PAN)
    pan = _attempt_pan_from_compact(re.sub(r"[^A-Za-z0-9]", "", combined_text).upper())

    # find pan segment index
    pan_index = -1
    for i, (t, _) in enumerate(segments):
        compact = re.sub(r"[^A-Za-z0-9]", "", t).upper()
        if _attempt_pan_from_compact(compact):
            pan_index = i
            break

    # If PAN not found above, leave pan_index as -1 (we'll try searching in raw text later)

    # 1) If there's a Name label after PAN index, pick the next valid segment
    label_norms = {_normalize_token(x) for x in NAME_LABELS}
    if pan_index >= 0:
        for i in range(pan_index + 1, min(len(segments), pan_index + 8)):
            seg_text, _ = segments[i]
            if _normalize_token(seg_text) in label_norms or any(lbl in seg_text.lower() for lbl in NAME_LABELS):
                # pick next plausible segment
                for j in range(i + 1, min(len(segments), i + 6)):
                    cand, _ = segments[j]
                    if _looks_like_name(cand):
                        return {"document_number": pan, "name": _clean_text(cand), "raw_text": combined_text, "quality_score": float(quality_score)}

    # 2) If no explicit label, pick first plausible name segment AFTER pan_index
    if pan_index >= 0:
        for i in range(pan_index + 1, len(segments)):
            cand, _ = segments[i]
            if _looks_like_name(cand):
                return {"document_number": pan, "name": _clean_text(cand), "raw_text": combined_text, "quality_score": float(quality_score)}

    # 3) Fallback: search the whole card for label 'Name' then next plausible
    for i, (t, _) in enumerate(segments):
        if any(lbl in t.lower() for lbl in NAME_LABELS) or _normalize_token(t) in label_norms:
            for j in range(i + 1, min(len(segments), i + 6)):
                cand, _ = segments[j]
                if _looks_like_name(cand):
                    return {"document_number": pan, "name": _clean_text(cand), "raw_text": combined_text, "quality_score": float(quality_score)}

    # 4) Last resort: find ANY plausible name in entire segments (prefer later segments)
    for i, (cand, _) in enumerate(segments):
        if _looks_like_name(cand):
            # ensure not a header, and prefer segment that isn't before a detected PAN if PAN exists
            if pan is not None and pan_index >= 0 and i <= pan_index:
                continue
            return {"document_number": pan, "name": _clean_text(cand), "raw_text": combined_text, "quality_score": float(quality_score)}

    # nothing valid
    return {"document_number": pan, "name": None, "raw_text": combined_text, "quality_score": float(quality_score)}


def extract_aadhaar_and_name_from_image(image_path: str) -> Dict:
    """
    Returns dict similar to PAN extractor.

    Logic:
    - extract 12-digit aadhaar (grouped or contiguous)
    - prefer name label 'नाम/Name' -> next segment
    - otherwise choose first plausible name segment occurring after the header area
    """
    raw_text, segments = _easyocr_read(image_path)
    combined_text = _clean_text(raw_text)
    quality_score = _avg_confidences([c for _, c in segments]) if segments else 0.0

    # Aadhaar number: look for grouped 4-4-4 or contiguous 12 digits
    m = re.search(r"(\d{4}\s*\d{4}\s*\d{4})", combined_text)
    aadhaar = None
    if m:
        aadhaar = re.sub(r"\D", "", m.group(1))
    else:
        m2 = re.search(r"(\d{12})", combined_text)
        if m2:
            aadhaar = m2.group(1)

    # If name label exists, pick next plausible
    label_norms = { _normalize_token(x) for x in NAME_LABELS }
    for i, (t, _) in enumerate(segments):
        if any(lbl in t.lower() for lbl in NAME_LABELS) or _normalize_token(t) in label_norms:
            for j in range(i + 1, min(len(segments), i + 6)):
                cand, _ = segments[j]
                if _looks_like_name(cand):
                    return {"document_number": aadhaar, "name": _clean_text(cand), "raw_text": combined_text, "quality_score": float(quality_score)}

    # Otherwise, skip header region and pick first plausible name occurrence
    # Find last header index (last segment that looks like header)
    last_header_idx = -1
    for i, (t, _) in enumerate(segments):
        if _is_header_text(t.lower()):
            last_header_idx = i

    # Search after last_header_idx
    for i in range(last_header_idx + 1, len(segments)):
        cand, _ = segments[i]
        if _looks_like_name(cand):
            return {"document_number": aadhaar, "name": _clean_text(cand), "raw_text": combined_text, "quality_score": float(quality_score)}

    # Fallback: first plausible anywhere
    for cand, _ in segments:
        if _looks_like_name(cand):
            return {"document_number": aadhaar, "name": _clean_text(cand), "raw_text": combined_text, "quality_score": float(quality_score)}

    return {"document_number": aadhaar, "name": None, "raw_text": combined_text, "quality_score": float(quality_score)}


# --- Name normalization & similarity helpers used by routes_kyc_session.py ---


def normalize_name_for_match(name: Optional[str]) -> str:
    if not name:
        return ""
    s = name.lower()
    s = re.sub(r"[^a-z\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    parts = [p for p in s.split() if p and p not in _HONORIFICS]
    return " ".join(parts)


def _token_overlap(a_tokens: List[str], b_tokens: List[str]) -> float:
    if not a_tokens or not b_tokens:
        return 0.0
    set_a = set(a_tokens)
    set_b = set(b_tokens)
    common = set_a.intersection(set_b)
    denom = min(len(a_tokens), len(b_tokens))
    return len(common) / denom if denom > 0 else 0.0


def name_similarity_enhanced(a: Optional[str], b: Optional[str]) -> Tuple[float, float, float]:
    """
    Returns (full_sim, token_sim, combined) where combined is weighted mix.
    """
    a_norm = normalize_name_for_match(a)
    b_norm = normalize_name_for_match(b)

    if not a_norm or not b_norm:
        return 0.0, 0.0, 0.0

    full_sim = SequenceMatcher(None, a_norm, b_norm).ratio()
    a_tokens = a_norm.split()
    b_tokens = b_norm.split()
    token_sim = _token_overlap(a_tokens, b_tokens)
    combined = (0.6 * full_sim) + (0.4 * token_sim)
    return float(full_sim), float(token_sim), float(combined)
