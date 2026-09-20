from datetime import datetime
from typing import List
import uuid
from pydantic import BaseModel, Field


class DocumentGroupCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, description="Descriptive label for document group")
    document_ids: List[uuid.UUID] = Field(..., min_length=1, description="List of document IDs to link into group")


class LinkedDocumentSummary(BaseModel):
    id: uuid.UUID
    original_filename: str
    file_type: str
    status: str

    model_config = {
        "from_attributes": True
    }


class DocumentGroupResponse(BaseModel):
    id: uuid.UUID
    owner_user_id: uuid.UUID
    name: str
    documents: List[LinkedDocumentSummary] = []
    created_at: datetime

    model_config = {
        "from_attributes": True
    }
