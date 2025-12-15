import os
from pathlib import Path
from uuid import UUID
from fastapi import UploadFile

UPLOAD_ROOT = Path("uploads/documents")


def ensure_session_folder(session_id: UUID) -> str:
    """
    Create folder for storing document images for a session.
    """
    folder = os.path.join(UPLOAD_ROOT, str(session_id))
    os.makedirs(folder, exist_ok=True)
    return folder


def save_uploaded_file(session_id: UUID, file) -> str:
    """
    Saves uploaded file in local storage. Returns relative path.
    """
    folder = ensure_session_folder(session_id)

    filename = file.filename
    file_path = os.path.join(folder, filename)

    # Save the file to disk
    with open(file_path, "wb") as f:
        f.write(file.file.read())

    return file_path

def save_selfie_file(session_id: UUID, file: UploadFile) -> str:
    """
    Save a selfie image under: uploads/selfies/<session_id>/<filename>
    Returns relative path as string.
    """
    session_dir = UPLOAD_ROOT / "selfies" / str(session_id)
    session_dir.mkdir(parents=True, exist_ok=True)

    file_path = session_dir / file.filename

    with file_path.open("wb") as buffer:
        buffer.write(file.file.read())

    # Store relative path, e.g. "uploads/selfies/<session>/file.jpg"
    return str(file_path)