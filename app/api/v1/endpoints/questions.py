from typing import Any, List
import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user, get_owned_document, get_owned_question
from app.core.database import get_db
from app.models.answer import Answer
from app.models.document import Document
from app.models.question import Question
from app.models.user import User
from app.schemas.answer import AnswerResponse
from app.schemas.question import AnswerSnippet, QuestionResponse

router = APIRouter()


@router.get(
    "/documents/{document_id}/questions",
    response_model=List[QuestionResponse],
    summary="Get All Extracted Questions for Document",
    description="Returns all structured questions extracted from the document, with options, source pages, confidence, and associated answer."
)
async def get_document_questions(
    document: Document = Depends(get_owned_document),
    db: AsyncSession = Depends(get_db)
) -> Any:
    """Retrieve all questions extracted from an owned document via shared dependency (PRD §11)."""
    # Fetch all questions for this document with loaded answer relationship
    q_stmt = (
        select(Question)
        .options(selectinload(Question.answer))
        .where(Question.source_document_id == document.id)
        .order_by(Question.created_at.asc())
    )
    q_result = await db.execute(q_stmt)
    questions = q_result.scalars().all()

    # Format response matching PRD §10 schema
    formatted = []
    for q in questions:
        ans_snippet = AnswerSnippet(value=None, confidence=0.0, match_method="unmatched")
        if q.answer:
            ans_snippet = AnswerSnippet(
                value=q.answer.answer_text,
                confidence=q.answer.answer_confidence,
                match_method=q.answer.answer_match_method
            )

        formatted.append(QuestionResponse(
            id=q.id,
            question_number=q.question_number,
            question_text=q.question_text,
            question_type=q.question_type,
            options=q.options,
            answer=ans_snippet,
            source_document_id=q.source_document_id,
            source_pages=q.source_pages,
            confidence_score=q.confidence_score,
            status=q.status,
            review_reason=q.review_reason
        ))

    return formatted


@router.get(
    "/questions/{question_id}",
    response_model=QuestionResponse,
    summary="Get Question Details",
    description="Returns details for a single extracted question with its associated answer."
)
async def get_question(
    question: Question = Depends(get_owned_question)
) -> Any:
    """Retrieve a single question by ID with strict user scoping via shared dependency (PRD §11)."""
    ans_snippet = AnswerSnippet(value=None, confidence=0.0, match_method="unmatched")
    if question.answer:
        ans_snippet = AnswerSnippet(
            value=question.answer.answer_text,
            confidence=question.answer.answer_confidence,
            match_method=question.answer.answer_match_method
        )

    return QuestionResponse(
        id=question.id,
        question_number=question.question_number,
        question_text=question.question_text,
        question_type=question.question_type,
        options=question.options,
        answer=ans_snippet,
        source_document_id=question.source_document_id,
        source_pages=question.source_pages,
        confidence_score=question.confidence_score,
        status=question.status,
        review_reason=question.review_reason
    )


@router.get(
    "/questions/{question_id}/answer",
    response_model=AnswerResponse,
    summary="Get Answer for Question",
    description="Returns answer entity details for a question (PRD §9 required endpoint)."
)
async def get_question_answer(
    question: Question = Depends(get_owned_question)
) -> Any:
    """Retrieve answer details for a question with strict user scoping via shared dependency (PRD §11)."""
    if not question.answer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Answer record not found or access denied."
        )

    return question.answer
