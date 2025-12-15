import re


def normalize_pan(pan: str) -> str:
    """
    Normalize PAN:
    - Uppercase
    - Remove spaces
    - Validate basic structure (5 letters, 4 digits, 1 letter)
    """
    if not pan:
        return ""

    pan = pan.upper().replace(" ", "")

    # Basic PAN pattern check
    pattern = r"^[A-Z]{5}[0-9]{4}[A-Z]$"
    if not re.match(pattern, pan):
        return pan  # return raw; API can decide to reject if invalid

    return pan


def normalize_aadhaar(aadhaar: str) -> str:
    """
    Normalize Aadhaar:
    - Keep digits only
    - Remove spaces and hyphens
    - Aadhaar must be 12 digits (but strict validation can be added later)
    """
    if not aadhaar:
        return ""

    digits = re.sub(r"\D", "", aadhaar)  # keep only digits

    return digits  # return as-is (API can validate length separately)


def normalize_passport(passport: str) -> str:
    """
    Normalize Passport:
    - Uppercase
    - Remove spaces
    """
    if not passport:
        return ""

    return passport.upper().replace(" ", "")
