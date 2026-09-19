from datetime import datetime
from typing import List, Optional
import uuid
from pydantic import BaseModel, Field


class DocumentBase(BaseModel):
    id: uuid.UUID
    original_filename: str
    file_type: str
    file_size_bytes: int
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class DocumentCreateResponse(DocumentBase):
    pass


class DocumentStatusResponse(BaseModel):
    id: uuid.UUID
    status: str
    current_stage: Optional[str] = None
    total_pages: int = 0
    pages_processed: int = 0
    error_message: Optional[str] = None

    model_config = {"from_attributes": True}


class DocumentResponse(DocumentBase):
    current_stage: Optional[str] = None
    total_pages: int = 0
    pages_processed: int = 0
    group_id: Optional[uuid.UUID] = None
    error_message: Optional[str] = None
    updated_at: datetime

    model_config = {"from_attributes": True}


class DocumentListResponse(BaseModel):
    total: int
    items: List[DocumentResponse]
