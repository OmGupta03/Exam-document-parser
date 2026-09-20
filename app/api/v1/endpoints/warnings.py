from typing import Any, List
import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_owned_document
from app.core.database import get_db
from app.models.document import Document
from app.models.processing_warning import ProcessingWarning
from app.models.user import User
from app.schemas.processing_warning import ProcessingWarningResponse

router = APIRouter()


@router.get(
    "/documents/{document_id}/warnings",
    response_model=List[ProcessingWarningResponse],
    summary="Get Warnings for Document",
    description="Returns all processing warnings logged for a document and its extracted questions (PRD §9 required endpoint)."
)
async def get_document_warnings(
    document: Document = Depends(get_owned_document),
    db: AsyncSession = Depends(get_db)
) -> Any:
    """Retrieve all warnings for a document with user access scoping via shared dependency (PRD §11)."""
    # Fetch warnings ordered by creation time
    warn_stmt = (
        select(ProcessingWarning)
        .where(ProcessingWarning.document_id == document.id)
        .order_by(ProcessingWarning.created_at.asc())
    )
    warn_res = await db.execute(warn_stmt)
    warnings = warn_res.scalars().all()

    return warnings
