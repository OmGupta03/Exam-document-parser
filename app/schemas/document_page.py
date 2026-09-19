from datetime import datetime
import uuid
from pydantic import BaseModel, Field


class DocumentPageResponse(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    page_number: int
    raw_text: str
    extraction_method: str
    confidence: float
    created_at: datetime

    model_config = {"from_attributes": True}
