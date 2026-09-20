from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field


class OptionSchema(BaseModel):
    label: str = Field(..., description="Option label, e.g., 'A', 'B', 'C', 'D'")
    text: str = Field(..., description="Option text content")


class AnswerSnippet(BaseModel):
    value: Optional[str] = Field(None, description="Extracted or associated answer value")
    confidence: float = Field(0.0, description="Answer association confidence score")
    match_method: str = Field("unmatched", description="Match method: number_match | content_match | unmatched")


class QuestionResponse(BaseModel):
    id: uuid.UUID
    question_number: Optional[str] = None
    question_text: str
    question_type: str # 'mcq' | 'true_false' | 'short_answer' | 'unknown'
    options: Optional[List[OptionSchema]] = None
    answer: AnswerSnippet = Field(default_factory=lambda: AnswerSnippet(value=None, confidence=0.0, match_method="unmatched"))
    source_document_id: uuid.UUID
    source_pages: List[int]
    confidence: float = Field(..., serialization_alias="confidence", validation_alias="confidence_score")
    status: str # 'extracted' | 'partial' | 'needs_review'
    review_reason: Optional[str] = None

    model_config = {
        "from_attributes": True,
        "populate_by_name": True
    }
