import logging
import re
from typing import Any, Dict, List, Optional, Tuple
import uuid
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class CandidateAnswer(BaseModel):
    key: Optional[str] = None # Question number hint, e.g. "1", "Q1", "4"
    value: str # Answer value, e.g. "B", "True", "O(log n)"
    raw_line: str
    source_document_id: uuid.UUID


class MatchedAnswerResult(BaseModel):
    question_id: uuid.UUID
    answer_text: Optional[str]
    answer_confidence: float
    answer_match_method: str # 'number_match' | 'content_match' | 'unmatched'
    source_document_id: uuid.UUID


def extract_candidate_answers_from_text(raw_text: str, source_doc_id: uuid.UUID) -> List[CandidateAnswer]:
    """
    Parse text to extract candidate question-to-answer mappings.
    Handles formats:
    - 1. B
    - 1. B — Au (from Latin 'aurum')
    - 2. C — Mars
    - Q1: C
    - 1) True
    - Question 2: Stack
    - 1 - A
    - 4. B — False (HTTP is stateless)
    """
    candidates: List[CandidateAnswer] = []
    lines = [l.strip() for l in raw_text.split("\n") if l.strip()]

    # Pattern for numbered keys with option letter and optional explanation (em-dash —, en-dash –, hyphen -, colon :)
    pat_num_opt = re.compile(
        r"^(?:Question\s*|Q\s*)?\(?(\d+[a-zA-Z]?)\)?[\.:\)\-\s]+\s*([A-Ea-e1-4])(?:\b|\s*[\u2014\u2013\-\.:]\s*|\s+)(.*)$",
        re.IGNORECASE
    )

    # Pattern for numbered True/False or full words: e.g. '1. True', '2. Stack'
    pat_general = re.compile(
        r"^(?:Question\s*|Q\s*)?\(?(\d+[a-zA-Z]?)\)?[\.:\)\-\s]+\s*(.+)$",
        re.IGNORECASE
    )

    for line in lines:
        # Skip header lines like "Answer Key", "Solutions", "General Science..."
        if re.match(r"^(?:Answer\s*Key|Solutions|Answers|Exam\s*Solutions|General\s*Science).*$", line, re.IGNORECASE):
            continue

        # Check numbered option first (e.g. "1. B — Au (from Latin 'aurum')" or "1. B")
        m_opt = pat_num_opt.match(line)
        if m_opt:
            q_key = m_opt.group(1).strip()
            val = m_opt.group(2).strip().upper()
            candidates.append(
                CandidateAnswer(
                    key=q_key,
                    value=val,
                    raw_line=line,
                    source_document_id=source_doc_id
                )
            )
            continue

        # Check general numbered pattern (e.g. "1. True" or "Question 2: Stack")
        m_gen = pat_general.match(line)
        if m_gen:
            q_key = m_gen.group(1).strip()
            rest = m_gen.group(2).strip()
            # If rest starts with an option letter like "A" or "B"
            first_token = rest.split()[0].rstrip(".:-—–")
            if len(first_token) == 1 and first_token.isalpha():
                val = first_token.upper()
            else:
                val = rest
            candidates.append(
                CandidateAnswer(
                    key=q_key,
                    value=val,
                    raw_line=line,
                    source_document_id=source_doc_id
                )
            )
            continue

        # Fallback: check if line contains colon-separated answer, e.g. "Binary Search: O(log n)"
        if ":" in line:
            parts = line.split(":", 1)
            candidates.append(
                CandidateAnswer(
                    key=parts[0].strip(),
                    value=parts[1].strip(),
                    raw_line=line,
                    source_document_id=source_doc_id
                )
            )

    return candidates



def match_answers_for_questions(
    questions: List[Any],
    candidate_sources: List[Tuple[uuid.UUID, str]]
) -> List[MatchedAnswerResult]:
    """
    Match extracted questions against candidate answer sources.
    candidate_sources: list of (doc_id, page_raw_text) tuples from same-doc or linked documents.
    """
    # 1. Collect all candidates
    all_candidates: List[CandidateAnswer] = []
    for doc_id, text in candidate_sources:
        all_candidates.extend(extract_candidate_answers_from_text(text, doc_id))

    logger.info("Found %d candidate answer items across candidate sources", len(all_candidates))

    results: List[MatchedAnswerResult] = []

    for q in questions:
        q_num = (q.question_number or "").strip().lower()
        q_text = (q.question_text or "").lower()
        options = q.options or []

        matched: Optional[MatchedAnswerResult] = None

        # Tier 1: Number Match (highest confidence)
        if q_num:
            for cand in all_candidates:
                cand_key = (cand.key or "").strip().lower()
                # Normalize "q1" -> "1"
                norm_q_num = re.sub(r"^q", "", q_num)
                norm_cand_key = re.sub(r"^q", "", cand_key)

                if norm_q_num == norm_cand_key:
                    matched = MatchedAnswerResult(
                        question_id=q.id,
                        answer_text=cand.value,
                        answer_confidence=0.95,
                        answer_match_method="number_match",
                        source_document_id=cand.source_document_id
                    )
                    break

        # Tier 2: Content Match (fallback ONLY where question is unnumbered or numbering is ambiguous)
        if not matched and not q_num and options:
            for cand in all_candidates:
                cand_val_lower = cand.value.lower()
                cand_key_lower = (cand.key or "").lower()

                # Meaningful token overlap (at least 3 characters, not single option letters like 'A', 'B')
                if len(cand_val_lower) >= 3:
                    for opt in options:
                        opt_text = opt.get("text", "").lower()
                        opt_label = opt.get("label", "").upper()
                        if cand_val_lower in opt_text or (len(opt_text) >= 3 and opt_text in cand_val_lower):
                            # Normalize value to the matched option's label for consistent API response
                            matched_val = opt_label if opt_label else cand.value
                            matched = MatchedAnswerResult(
                                question_id=q.id,
                                answer_text=matched_val,
                                answer_confidence=0.70,
                                answer_match_method="content_match",
                                source_document_id=cand.source_document_id
                            )
                            break
                    if matched:
                        break
                elif len(cand_key_lower) >= 4 and cand_key_lower in q_text:
                    matched_val = cand.value
                    for opt in options:
                        if cand_val_lower == opt.get("label", "").lower() or cand_val_lower in opt.get("text", "").lower():
                            matched_val = opt.get("label", "").upper() or cand.value
                            break
                    matched = MatchedAnswerResult(
                        question_id=q.id,
                        answer_text=matched_val,
                        answer_confidence=0.70,
                        answer_match_method="content_match",
                        source_document_id=cand.source_document_id
                    )
                    break

        # Tier 3: Unmatched (Strict Non-Fabrication per PRD §4 Stage 5)
        if not matched:
            matched = MatchedAnswerResult(
                question_id=q.id,
                answer_text=None,
                answer_confidence=0.0,
                answer_match_method="unmatched",
                source_document_id=q.source_document_id
            )

        results.append(matched)

    return results
