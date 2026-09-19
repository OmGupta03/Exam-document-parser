import os
from pathlib import Path
from typing import Tuple
import uuid
from fastapi import HTTPException, UploadFile, status

from app.core.config import settings

CHUNK_SIZE = 1024 * 1024 # 1 MB chunks


async def save_upload_file(
    upload_file: UploadFile,
    doc_id: uuid.UUID,
    file_type: str,
    first_chunk: bytes
) -> Tuple[str, int]:
    """
    Saves an uploaded file to secure storage keyed strictly by generated UUIDs.
    Guarantees no user-controlled filenames in the physical path (prevents traversal).
    Enforces the strict 25MB server-side size limit.
    Returns (absolute_storage_path, total_bytes_written).
    """
    doc_dir = Path(settings.STORAGE_DIR) / str(doc_id)
    doc_dir.mkdir(parents=True, exist_ok=True)

    file_uuid = uuid.uuid4()
    dest_path = doc_dir / f"{file_uuid}.{file_type}"

    total_bytes = len(first_chunk)
    if total_bytes > settings.MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds maximum allowed size of {settings.MAX_FILE_SIZE_BYTES // (1024 * 1024)}MB."
        )

    try:
        with open(dest_path, "wb") as out_file:
            out_file.write(first_chunk)

            while True:
                chunk = await upload_file.read(CHUNK_SIZE)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > settings.MAX_FILE_SIZE_BYTES:
                    out_file.close()
                    if dest_path.exists():
                        dest_path.unlink()
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"File exceeds maximum allowed size of {settings.MAX_FILE_SIZE_BYTES // (1024 * 1024)}MB."
                    )
                out_file.write(chunk)

    except HTTPException:
        raise
    except Exception as e:
        if dest_path.exists():
            dest_path.unlink()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while saving the uploaded file."
        )

    return str(dest_path), total_bytes
