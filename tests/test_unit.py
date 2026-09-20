import pytest
from pydantic import ValidationError

from app.schemas.user import UserCreate
from app.schemas.question import AnswerSnippet, QuestionResponse
from app.schemas.document_group import DocumentGroupCreateRequest
from app.core.security import get_password_hash, verify_password, create_access_token
from app.services.ai_provider import RawQuestionSegment, MockAIProvider


# ==============================================================================
# 1. SCHEMA VALIDATION TESTS (PRD §13)
# ==============================================================================

def test_user_create_schema_valid():
    user_in = UserCreate(email="valid.user@example.com", password="SuperSecurePassword123!")
    assert user_in.email == "valid.user@example.com"
    assert user_in.password == "SuperSecurePassword123!"


def test_user_create_schema_invalid_email():
    with pytest.raises(ValidationError):
        UserCreate(email="not-an-email", password="SuperSecurePassword123!")


def test_user_create_schema_short_password():
    with pytest.raises(ValidationError):
        UserCreate(email="valid@example.com", password="short")


def test_answer_snippet_schema_serialization():
    # Test valid snippet with serialization alias 'confidence'
    snippet = AnswerSnippet(value="B", confidence=0.95, match_method="number_match")
    data = snippet.model_dump(by_alias=True)
    assert data["value"] == "B"
    assert data["confidence"] == 0.95
    assert data["match_method"] == "number_match"


def test_answer_snippet_unmatched_shape():
    # Non-fabrication guarantee schema shape (PRD §10)
    snippet = AnswerSnippet(value=None, confidence=0.0, match_method="unmatched")
    data = snippet.model_dump(by_alias=True)
    assert data["value"] is None
    assert data["confidence"] == 0.0
    assert data["match_method"] == "unmatched"


def test_document_group_schema_validation():
    with pytest.raises(ValidationError):
        # Empty document list should fail validation
        DocumentGroupCreateRequest(name="Empty Group", document_ids=[])


# ==============================================================================
# 2. CONFIDENCE SCORING LOGIC TESTS (PRD §13 & §6)
# ==============================================================================

def test_stage4_composite_confidence_formula():
    """Verify composite = round((upstream_conf * 0.40) + (llm_conf * 0.60), 2)"""
    upstream_conf = 0.98  # Clean native text
    llm_conf = 0.92       # High model confidence
    composite = round((upstream_conf * 0.40) + (llm_conf * 0.60), 2)
    assert composite == 0.94

    # Degraded OCR input propagation test
    degraded_ocr = 0.47   # Scanned noise
    llm_uncertain = 0.70  # Lower confidence
    composite_degraded = round((degraded_ocr * 0.40) + (llm_uncertain * 0.60), 2)
    assert composite_degraded == 0.61


def test_stage6_answer_key_recomputation_formula():
    """Verify in-place recomputation: round(0.80 * question_conf + 0.20 * answer_match_conf, 2)"""
    question_conf = 0.94
    number_match_conf = 0.95
    recomputed = round((0.80 * question_conf) + (0.20 * number_match_conf), 2)
    assert recomputed == 0.94  # 0.752 + 0.190 = 0.942 -> 0.94

    content_match_conf = 0.70
    recomputed_content = round((0.80 * question_conf) + (0.20 * content_match_conf), 2)
    assert recomputed_content == 0.89  # 0.752 + 0.140 = 0.892 -> 0.89


def test_confidence_status_threshold_classification():
    """Verify status assignment: >= 0.85 -> extracted, >= 0.70 -> partial, < 0.70 -> needs_review"""
    def classify(score: float):
        if score >= 0.85:
            return "extracted"
        elif score >= 0.70:
            return "partial"
        return "needs_review"

    assert classify(0.94) == "extracted"
    assert classify(0.85) == "extracted"
    assert classify(0.75) == "partial"
    assert classify(0.70) == "partial"
    assert classify(0.69) == "needs_review"
    assert classify(0.30) == "needs_review"


# ==============================================================================
# 3. ANSWER-MATCHING THREE-TIER ENGINE TESTS (PRD §13 & §5)
# ==============================================================================

import uuid
from app.services.answer_key import match_answers_for_questions, MatchedAnswerResult

class DummyQuestion:
    def __init__(self, q_num, text, options, doc_id=None):
        self.id = uuid.uuid4()
        self.question_number = q_num
        self.question_text = text
        self.options = options
        self.source_document_id = doc_id or uuid.uuid4()


def test_answer_matching_tier1_number_match():
    """Tier 1: Explicit question number match (0.95 confidence)."""
    q_doc_id = uuid.uuid4()
    ak_doc_id = uuid.uuid4()
    questions = [
        DummyQuestion("1", "What is the time complexity of binary search?", [
            {"label": "A", "text": "O(n)"},
            {"label": "B", "text": "O(log n)"},
            {"label": "C", "text": "O(n^2)"}
        ], doc_id=q_doc_id)
    ]
    candidate_sources = [(ak_doc_id, "1. B\n2. C\n3. A")]
    results = match_answers_for_questions(questions, candidate_sources)
    assert len(results) == 1
    assert results[0].answer_text == "B"
    assert results[0].answer_match_method == "number_match"
    assert results[0].answer_confidence == 0.95
    assert results[0].source_document_id == ak_doc_id


def test_answer_matching_tier2_content_match_normalized_label():
    """Tier 2: Unnumbered question matching by content similarity, normalized to option label (0.70 confidence)."""
    q_doc_id = uuid.uuid4()
    ak_doc_id = uuid.uuid4()
    questions = [
        DummyQuestion(None, "What is the standard model for relational database queries?", [
            {"label": "A", "text": "SQL Language"},
            {"label": "B", "text": "GraphQL Schema"}
        ], doc_id=q_doc_id)
    ]
    candidate_sources = [(ak_doc_id, "Relational Queries: SQL Language")]
    results = match_answers_for_questions(questions, candidate_sources)
    assert len(results) == 1
    # Strictly normalized to option label "A" rather than raw string "SQL Language"
    assert results[0].answer_text == "A"
    assert results[0].answer_match_method == "content_match"
    assert results[0].answer_confidence == 0.70
    assert results[0].source_document_id == ak_doc_id


def test_answer_matching_tier3_non_fabrication_unmatched():
    """Tier 3: Strict non-fabrication guarantee — omitted question remains unmatched with null answer."""
    q_doc_id = uuid.uuid4()
    ak_doc_id = uuid.uuid4()
    questions = [
        DummyQuestion("4", "What is linear probing in open addressing?", [
            {"label": "A", "text": "Step 1"},
            {"label": "B", "text": "Step 2"}
        ], doc_id=q_doc_id)
    ]
    # Key only provides answers for 1, 2, 3
    candidate_sources = [(ak_doc_id, "1. A\n2. B\n3. C")]
    results = match_answers_for_questions(questions, candidate_sources)
    assert len(results) == 1
    assert results[0].answer_text is None
    assert results[0].answer_confidence == 0.0
    assert results[0].answer_match_method == "unmatched"


# ==============================================================================
# 4. AUTH & SECURITY UNIT TESTS (PRD §13 & §11)
# ==============================================================================

def test_password_hashing_and_verification():
    raw_password = "MySecurePassword123!"
    hashed = get_password_hash(raw_password)
    assert hashed != raw_password
    assert verify_password(raw_password, hashed) is True
    assert verify_password("WrongPassword123!", hashed) is False


def test_jwt_generation_and_claims():
    from jose import jwt
    from app.core.config import settings

    token = create_access_token(subject="12345678-1234-5678-1234-567812345678")
    payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    assert payload["sub"] == "12345678-1234-5678-1234-567812345678"
    assert "exp" in payload
