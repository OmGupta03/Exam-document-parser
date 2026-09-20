from datetime import datetime
from typing import Optional
import uuid
from pydantic import BaseModel, Field


class AnswerResponse(BaseModel):
    id: uuid.UUID
    question_id: uuid.UUID
    answer_text: Optional[str] = None
    answer_confidence: float = Field(0.0, description="Confidence score of answer match (0.0 to 1.0)")
    answer_match_method: str = Field("unmatched", description="Matching method: number_match | content_match | unmatched | none")
    source_document_id: uuid.UUID
    created_at: datetime

    model_config = {
        "from_attributes": True
    }
