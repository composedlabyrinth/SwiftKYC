import sys
import os

# Add project root to PYTHONPATH dynamically
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.utils.ocr import (
    extract_aadhaar_and_name_from_image,
    extract_pan_and_name_from_image,
)

def test(image_path: str):
    print("=" * 80)
    print("IMAGE:", image_path)

    # Try Aadhaar extraction
    aadhaar = extract_aadhaar_and_name_from_image(image_path)
    print("AADHAAR EXTRACT:", aadhaar)

    # Try PAN extraction
    pan = extract_pan_and_name_from_image(image_path)
    print("PAN EXTRACT:", pan)

    print("=" * 80)
    print()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python tools/test_ocr_inspect.py <image_path>")
        sys.exit(1)

    for img in sys.argv[1:]:
        test(img)
