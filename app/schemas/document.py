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


class HumanReadableQuestionOption(BaseModel):
    label: str
    text: str
    is_correct: bool = False


class HumanReadableQuestionItem(BaseModel):
    question_number: str
    question_text: str
    question_type: str
    source_pages: List[int]
    confidence: float
    status: str
    options: Optional[List[HumanReadableQuestionOption]] = None
    verified_answer: Optional[str] = None
    answer_match_method: Optional[str] = None
    answer_confidence: Optional[float] = None
    review_reason: Optional[str] = None


class DocumentExtractionSummary(BaseModel):
    document_name: str
    status: str
    total_pages: int
    extraction_engine: str
    total_questions: int
    verified_questions: int
    needs_review_questions: int
    average_confidence: str


class DocumentExtractionResultResponse(BaseModel):
    document_id: uuid.UUID
    summary: DocumentExtractionSummary
    human_readable_results: str
    questions: List[HumanReadableQuestionItem]

