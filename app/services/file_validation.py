from typing import Tuple
from fastapi import HTTPException, status
import magic

# Allowed MIME types mapped to normalized file types per PRD §4 Stage 1
ALLOWED_MIME_TYPES = {
    "application/pdf": "pdf",
    "image/jpeg": "jpg",
    "image/png": "png",
}


def validate_file_content(header_bytes: bytes, filename: str) -> str:
    """
    Validate file content-type via byte-level MIME sniffing (not just file extension).
    Prevents executable or malformed uploads disguised with legitimate extensions.
    Returns the normalized file_type string ('pdf', 'jpg', 'png').
    """
    if not header_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The uploaded file is empty."
        )

    # Sniff MIME type from the raw byte header
    try:
        detected_mime = magic.from_buffer(header_bytes, mime=True)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unable to determine file type: {str(e)}"
        )

    if detected_mime not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unsupported file type '{detected_mime}'. "
                f"Only digital/scanned PDFs and JPEG/PNG images are supported."
            )
        )

    return ALLOWED_MIME_TYPES[detected_mime]
