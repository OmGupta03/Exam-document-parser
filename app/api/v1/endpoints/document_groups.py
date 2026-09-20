from typing import Any, List
import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user, get_owned_document_group
from app.core.database import get_db
from app.models.document import Document
from app.models.document_group import DocumentGroup
from app.models.user import User
from app.schemas.document_group import (
    DocumentGroupCreateRequest,
    DocumentGroupResponse,
    LinkedDocumentSummary,
)

router = APIRouter()


@router.post(
    "",
    response_model=DocumentGroupResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Document Group",
    description="Link two or more owned documents into a group (e.g. question paper + separate answer key). Documents must be owned by the caller."
)
async def create_document_group(
    payload: DocumentGroupCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> Any:
    """Create a new document group linking specified documents."""
    # Verify all document IDs exist and are owned by the authenticated user
    doc_stmt = select(Document).where(
        Document.id.in_(payload.document_ids),
        Document.owner_user_id == current_user.id
    )
    doc_res = await db.execute(doc_stmt)
    docs = doc_res.scalars().all()

    if len(docs) != len(payload.document_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="One or more document IDs were not found or access was denied."
        )

    # Create DocumentGroup
    group_id = uuid.uuid4()
    group = DocumentGroup(
        id=group_id,
        owner_user_id=current_user.id,
        name=payload.name
    )
    db.add(group)

    # Associate each document with the group
    for doc in docs:
        doc.group_id = group_id

    await db.commit()
    await db.refresh(group)

    # Re-queue processing for documents to resolve cross-document answer keys per PRD §6
    from app.workers.tasks import process_document
    for doc in docs:
        process_document.delay(str(doc.id))

    doc_summaries = [
        LinkedDocumentSummary(
            id=d.id,
            original_filename=d.original_filename,
            file_type=d.file_type,
            status=d.status
        )
        for d in docs
    ]

    return DocumentGroupResponse(
        id=group.id,
        owner_user_id=group.owner_user_id,
        name=group.name,
        documents=doc_summaries,
        created_at=group.created_at
    )


@router.get(
    "/{group_id}",
    response_model=DocumentGroupResponse,
    summary="Get Document Group Details",
    description="Returns metadata for a document group and its linked documents."
)
async def get_document_group(
    group: DocumentGroup = Depends(get_owned_document_group)
) -> Any:
    """Retrieve document group details with strict user isolation via shared dependency (PRD §11)."""
    doc_summaries = [
        LinkedDocumentSummary(
            id=d.id,
            original_filename=d.original_filename,
            file_type=d.file_type,
            status=d.status
        )
        for d in (group.documents or [])
    ]

    return DocumentGroupResponse(
        id=group.id,
        owner_user_id=group.owner_user_id,
        name=group.name,
        documents=doc_summaries,
        created_at=group.created_at
    )


@router.get(
    "",
    response_model=List[DocumentGroupResponse],
    summary="List User Document Groups",
    description="Returns all document groups owned by the authenticated user with linked documents."
)
async def list_document_groups(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> Any:
    """Retrieve all document groups owned by the authenticated user."""
    stmt = (
        select(DocumentGroup)
        .where(DocumentGroup.owner_user_id == current_user.id)
        .order_by(DocumentGroup.created_at.desc())
    )
    result = await db.execute(stmt)
    groups = result.scalars().all()

    response = []
    for g in groups:
        docs_stmt = select(Document).where(Document.group_id == g.id)
        docs_res = await db.execute(docs_stmt)
        docs = docs_res.scalars().all()
        doc_summaries = [
            LinkedDocumentSummary(
                id=d.id,
                original_filename=d.original_filename,
                file_type=d.file_type,
                status=d.status
            )
            for d in docs
        ]
        response.append(DocumentGroupResponse(
            id=g.id,
            owner_user_id=g.owner_user_id,
            name=g.name,
            documents=doc_summaries,
            created_at=g.created_at
        ))

    return response

