from datetime import datetime
from typing import Optional
import uuid
from pydantic import BaseModel, Field


class ProcessingWarningResponse(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    question_id: Optional[uuid.UUID] = None
    warning_type: str
    message: str
    severity: str # 'info' | 'warning' | 'critical'
    created_at: datetime

    model_config = {
        "from_attributes": True
    }
