import logging
import re
from typing import List, Optional

from app.models.document_page import DocumentPage
from app.services.ai_provider import RawQuestionSegment

logger = logging.getLogger(__name__)

# Regex pattern as a hint generator for question boundaries per PRD §4 Stage 3
QUESTION_MARKER_REGEX = re.compile(
    r"^(?:(?:Question|Q)\s*)?\(?(\d+[a-zA-Z]?)\)?[\.:\)\s]\s*",
    re.IGNORECASE
)


def segment_document_pages(pages: List[DocumentPage]) -> List[RawQuestionSegment]:
    """
    Stage 3 Layout & Question Segmentation Engine per PRD §4.
    - Uses regex pattern detection as hint generator only.
    - Handles questions spanning multiple pages by carrying context across page boundaries.
    - Accumulates source_pages list for multi-page traceability per PRD §7.
    """
    if not pages:
        return []

    # Sort pages in sequential order
    sorted_pages = sorted(pages, key=lambda p: p.page_number)
    segments: List[RawQuestionSegment] = []

    current_lines: List[str] = []
    current_pages: List[int] = []
    current_hint: Optional[str] = None
    current_confidences: List[float] = []

    for page in sorted_pages:
        page_num = page.page_number
        page_text = page.raw_text.strip()
        if not page_text:
            continue

        page_lines = page_text.split("\n")
        for line in page_lines:
            stripped_line = line.strip()
            if not stripped_line:
                continue

            marker_match = QUESTION_MARKER_REGEX.match(stripped_line)
            # Avoid matching options like 'A. ...' or sub-lists
            is_new_question = bool(marker_match and not re.match(r"^[A-Da-d][\.\)]", stripped_line))

            if is_new_question:
                # Flush existing accumulated question segment
                if current_lines:
                    avg_conf = (sum(current_confidences) / len(current_confidences)) if current_confidences else 0.90
                    segments.append(RawQuestionSegment(
                        raw_text="\n".join(current_lines),
                        source_pages=sorted(list(set(current_pages))),
                        question_hint=current_hint,
                        extraction_confidence=round(avg_conf, 2)
                    ))
                    current_lines = []
                    current_pages = []
                    current_confidences = []

                # Start new question segment
                current_hint = marker_match.group(1)
                current_lines.append(stripped_line)
                current_pages.append(page_num)
                current_confidences.append(page.confidence)

            else:
                # Continuation line (could be part of question prompt, options, or multi-page continuation)
                if current_lines:
                    current_lines.append(stripped_line)
                    if page_num not in current_pages:
                        current_pages.append(page_num)
                        logger.info(
                            "[SEGMENTATION] Question %s carries context across page boundary to page %d",
                            current_hint, page_num
                        )
                    current_confidences.append(page.confidence)
                else:
                    # Leading text before first question marker (header/instructions)
                    pass

    # Flush final question segment
    if current_lines:
        avg_conf = (sum(current_confidences) / len(current_confidences)) if current_confidences else 0.90
        segments.append(RawQuestionSegment(
            raw_text="\n".join(current_lines),
            source_pages=sorted(list(set(current_pages))),
            question_hint=current_hint,
            extraction_confidence=round(avg_conf, 2)
        ))

    # Fallback: if no question markers were detected, treat the entire page sequence as a single segment
    if not segments and sorted_pages:
        full_text = "\n\n".join(p.raw_text.strip() for p in sorted_pages if p.raw_text.strip())
        all_pages = [p.page_number for p in sorted_pages]
        avg_conf = sum(p.confidence for p in sorted_pages) / len(sorted_pages)
        segments.append(RawQuestionSegment(
            raw_text=full_text,
            source_pages=all_pages,
            question_hint=None,
            extraction_confidence=round(avg_conf, 2)
        ))

    logger.info("[SEGMENTATION] Extracted %d question segment(s) across %d page(s)", len(segments), len(sorted_pages))
    return segments
