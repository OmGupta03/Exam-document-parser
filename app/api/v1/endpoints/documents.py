from typing import Any, List, Optional
import uuid
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.document import Document
from app.models.user import User
from app.schemas.document import (
    DocumentCreateResponse,
    DocumentListResponse,
    DocumentResponse,
    DocumentStatusResponse,
)
from app.services.file_validation import validate_file_content
from app.services.storage import save_upload_file

router = APIRouter()


@router.post(
    "",
    response_model=DocumentCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload Document",
    description="Upload a PDF or image file (max 25MB). Validates content-type via byte-level MIME sniffing and initializes status to PENDING."
)
async def upload_document(
    file: UploadFile = File(..., description="Document file to upload (PDF, JPG, PNG)"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> Any:
    """Upload and validate document, saving it to secure UUID-keyed storage."""
    # Read the initial chunk (up to 2048 bytes) for MIME sniffing
    header_bytes = await file.read(2048)
    filename = file.filename or "unknown"

    # Byte-level MIME sniffing validation
    file_type = validate_file_content(header_bytes, filename)

    # Generate isolated Document UUID
    doc_id = uuid.uuid4()

    # Save to disk with 25MB server-side streaming enforcement
    storage_path, file_size_bytes = await save_upload_file(
        upload_file=file,
        doc_id=doc_id,
        file_type=file_type,
        first_chunk=header_bytes
    )

    # Persist document metadata row in PostgreSQL
    new_doc = Document(
        id=doc_id,
        owner_user_id=current_user.id,
        original_filename=filename,
        storage_path=storage_path,
        file_type=file_type,
        file_size_bytes=file_size_bytes,
        status="PENDING",
        current_stage="UPLOADED",
        total_pages=0,
        pages_processed=0
    )
    db.add(new_doc)
    await db.commit()
    await db.refresh(new_doc)

    # Enqueue async processing task via Celery
    from app.workers.tasks import process_document
    process_document.delay(str(new_doc.id))

    return new_doc


@router.get(
    "/{document_id}/status",
    response_model=DocumentStatusResponse,
    summary="Poll Document Processing Status",
    description="Returns processing status and pipeline stage progress for an owned document."
)
async def get_document_status(
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> Any:
    """Poll document processing status with strict user isolation."""
    stmt = select(Document).where(
        Document.id == document_id,
        Document.owner_user_id == current_user.id
    )
    result = await db.execute(stmt)
    document = result.scalar_one_or_none()

    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found or access denied."
        )

    return document


@router.get(
    "/{document_id}",
    response_model=DocumentResponse,
    summary="Get Document Metadata",
    description="Returns full metadata for an owned document."
)
async def get_document_metadata(
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> Any:
    """Retrieve document metadata with strict user isolation."""
    stmt = select(Document).where(
        Document.id == document_id,
        Document.owner_user_id == current_user.id
    )
    result = await db.execute(stmt)
    document = result.scalar_one_or_none()

    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found or access denied."
        )

    return document


@router.get(
    "",
    response_model=DocumentListResponse,
    summary="List User Documents",
    description="Returns paginated list of documents owned by the authenticated user."
)
async def list_documents(
    skip: int = Query(0, ge=0, description="Offset for pagination"),
    limit: int = Query(20, ge=1, le=100, description="Limit for pagination"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> Any:
    """List documents belonging to the authenticated user."""
    # Count total
    count_stmt = select(func.count(Document.id)).where(Document.owner_user_id == current_user.id)
    total = (await db.execute(count_stmt)).scalar() or 0

    # Query items
    query = (
        select(Document)
        .where(Document.owner_user_id == current_user.id)
        .order_by(desc(Document.created_at))
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(query)
    items = result.scalars().all()

    return {
        "total": total,
        "items": items
    }
