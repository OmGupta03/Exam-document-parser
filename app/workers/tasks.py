import logging
import uuid
from celery import shared_task
from sqlalchemy import delete, select

from app.core.celery_app import celery_app
from app.db.sync_session import get_sync_db
from app.models.answer import Answer
from app.models.document import Document
from app.models.document_page import DocumentPage
from app.models.processing_warning import ProcessingWarning
from app.models.question import Question
from app.services.ai_provider import get_ai_provider
from app.services.answer_key import match_answers_for_questions
from app.services.segmentation import segment_document_pages
from app.services.text_extraction import extract_document_pages

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="app.workers.tasks.process_document",
    max_retries=3,
    default_retry_delay=5,
    acks_late=True,
)
def process_document(self, document_id: str):
    """
    Multi-stage async document processing pipeline:
    - Stage 1 & 2: Ingest, Normalize & Text Extraction (PyMuPDF fast path / Tesseract OCR)
    - Stage 3: Layout & Question Segmentation (with multi-page context carrying)
    - Stage 4: AI-based Question Structuring (with self-reported confidence & schema validation)
    - Stage 5: Answer-Key Association (same-doc & linked-doc resolution with non-fabrication)
    - Stage 6: Composite Confidence Scoring & Warning Generation
    """
    doc_uuid = uuid.UUID(document_id)
    logger.info("[ASYNC WORKER] Starting processing pipeline for document_id=%s", document_id)

    # 1. Update status to PROCESSING / TEXT_EXTRACTION
    with get_sync_db() as db:
        stmt = select(Document).where(Document.id == doc_uuid)
        document = db.execute(stmt).scalar_one_or_none()

        if not document:
            logger.error("[ASYNC WORKER] Document %s not found in database.", document_id)
            return {"error": "Document not found", "document_id": document_id}

        document.status = "PROCESSING"
        document.current_stage = "TEXT_EXTRACTION"
        document.error_message = None
        db.commit()

        storage_path = document.storage_path
        file_type = document.file_type
        group_id = document.group_id

    # 2. Stage 2: Execute PyMuPDF / Tesseract text extraction
    page_results = extract_document_pages(
        storage_path=storage_path,
        file_type=file_type
    )

    db_pages = []
    failed_pages = []
    warnings_to_create = []

    with get_sync_db() as db:
        # Clear existing pages for idempotency
        db.execute(delete(DocumentPage).where(DocumentPage.document_id == doc_uuid))

        for page_res in page_results:
            new_page = DocumentPage(
                document_id=doc_uuid,
                page_number=page_res.page_number,
                raw_text=page_res.raw_text,
                extraction_method=page_res.extraction_method,
                confidence=page_res.confidence
            )
            db.add(new_page)
            db_pages.append(new_page)
            if page_res.extraction_method == "failed":
                failed_pages.append(page_res.page_number)
                warnings_to_create.append(
                    ProcessingWarning(
                        id=uuid.uuid4(),
                        document_id=doc_uuid,
                        warning_type="extraction_failed",
                        message=f"Page {page_res.page_number} failed text extraction and was marked failed.",
                        severity="warning"
                    )
                )
            elif page_res.confidence < 0.60:
                warnings_to_create.append(
                    ProcessingWarning(
                        id=uuid.uuid4(),
                        document_id=doc_uuid,
                        warning_type="ocr_low_confidence",
                        message=f"Page {page_res.page_number} extraction confidence is low ({page_res.confidence:.2f}).",
                        severity="warning"
                    )
                )

        stmt = select(Document).where(Document.id == doc_uuid)
        document = db.execute(stmt).scalar_one_or_none()
        if document:
            document.total_pages = len(page_results)
            document.pages_processed = len(page_results)
        db.commit()

    # If all pages failed, terminate with FAILED status per PRD §12
    if len(failed_pages) == len(page_results) and len(page_results) > 0:
        with get_sync_db() as db:
            stmt = select(Document).where(Document.id == doc_uuid)
            document = db.execute(stmt).scalar_one_or_none()
            if document:
                document.status = "FAILED"
                document.current_stage = "EXTRACTION_FAILED"
                document.error_message = "All pages failed text extraction."
                db.commit()
        return {"error": "All pages failed extraction", "document_id": document_id}

    # 3. Stage 3: Layout & Question Segmentation
    with get_sync_db() as db:
        stmt = select(Document).where(Document.id == doc_uuid)
        document = db.execute(stmt).scalar_one_or_none()
        if document:
            document.current_stage = "LAYOUT_SEGMENTATION"
            db.commit()

    raw_segments = segment_document_pages(db_pages)

    # 4. Stage 4: AI-based Question Structuring
    with get_sync_db() as db:
        stmt = select(Document).where(Document.id == doc_uuid)
        document = db.execute(stmt).scalar_one_or_none()
        if document:
            document.current_stage = "AI_STRUCTURING"
            db.commit()

    ai_provider = get_ai_provider()
    created_questions = []

    with get_sync_db() as db:
        # Clear existing questions & answers for idempotent execution
        db.execute(delete(Question).where(Question.source_document_id == doc_uuid))
        db.execute(delete(ProcessingWarning).where(ProcessingWarning.document_id == doc_uuid))

        for segment in raw_segments:
            structured = ai_provider.structure_segment(segment)

            # Two-factor extraction confidence
            upstream_conf = segment.extraction_confidence
            llm_conf = structured.llm_confidence
            ext_conf = round((upstream_conf * 0.4) + (llm_conf * 0.6), 2)

            if structured.validation_error:
                status = "needs_review"
                review_reason = structured.validation_error
            elif ext_conf >= 0.75:
                status = "extracted"
                review_reason = None
            elif ext_conf >= 0.40:
                status = "partial"
                review_reason = "Extraction confidence below primary threshold"
            else:
                status = "needs_review"
                review_reason = "Low confidence extraction"

            question = Question(
                id=uuid.uuid4(),
                source_document_id=doc_uuid,
                question_number=structured.question_number,
                question_text=structured.question_text,
                question_type=structured.question_type,
                options=structured.options,
                source_pages=segment.source_pages,
                confidence_score=ext_conf,
                status=status,
                review_reason=review_reason
            )
            db.add(question)
            created_questions.append(question)

        db.commit()

    # 5. Stage 5: Answer-Key Detection & Association
    with get_sync_db() as db:
        stmt = select(Document).where(Document.id == doc_uuid)
        document = db.execute(stmt).scalar_one_or_none()
        if document:
            document.current_stage = "ANSWER_KEY_ASSOCIATION"
            group_id = document.group_id
            db.commit()

    # Gather candidate answer text sources (same document + linked documents in group)
    candidate_sources = []

    with get_sync_db() as db:
        # Same-document pages
        for p in db_pages:
            if p.raw_text:
                candidate_sources.append((doc_uuid, p.raw_text))

        # Linked documents in same group (PRD §6 requirement)
        has_linked_key = False
        if group_id:
            linked_docs_stmt = select(Document).where(
                Document.group_id == group_id,
                Document.id != doc_uuid
            )
            linked_docs = db.execute(linked_docs_stmt).scalars().all()

            for linked_doc in linked_docs:
                pages_stmt = select(DocumentPage).where(DocumentPage.document_id == linked_doc.id)
                linked_pages = db.execute(pages_stmt).scalars().all()
                for lp in linked_pages:
                    if lp.raw_text:
                        candidate_sources.append((linked_doc.id, lp.raw_text))
                        has_linked_key = True

    # Match answers
    answer_results = match_answers_for_questions(created_questions, candidate_sources)

    # 6. Stage 6: Confidence Scoring & Warning Flags
    with get_sync_db() as db:
        stmt = select(Document).where(Document.id == doc_uuid)
        document = db.execute(stmt).scalar_one_or_none()
        if document:
            document.current_stage = "CONFIDENCE_SCORING"
            db.commit()

        # Check if an answer key was actively identified across candidate sources
        key_detected = any(a.answer_match_method != "unmatched" for a in answer_results) or has_linked_key

        for q, ans in zip(created_questions, answer_results):
            # Persist Answer record
            new_ans = Answer(
                id=uuid.uuid4(),
                question_id=q.id,
                answer_text=ans.answer_text,
                answer_confidence=ans.answer_confidence,
                answer_match_method=ans.answer_match_method,
                source_document_id=ans.source_document_id
            )
            db.add(new_ans)

            # Reconciled Final Composite Confidence Formula
            initial_ext_conf = q.confidence_score
            if key_detected:
                # 4-factor composite: 80% extraction quality, 20% answer key matching
                final_conf = round((initial_ext_conf * 0.80) + (ans.answer_confidence * 0.20), 2)
            else:
                # Standalone question document without key: retain extraction confidence
                final_conf = initial_ext_conf

            # Determine final status & review reason
            if q.status == "needs_review" and q.review_reason and "validation" in q.review_reason.lower():
                final_status = "needs_review"
                final_reason = q.review_reason
            elif final_conf >= 0.75:
                final_status = "extracted"
                final_reason = None
            elif final_conf >= 0.40:
                final_status = "partial"
                final_reason = "Confidence below primary threshold (extraction or answer association)"
            else:
                final_status = "needs_review"
                final_reason = "Low confidence score"

            # Log warning if answer unmatched despite answer key presence
            if key_detected and ans.answer_match_method == "unmatched":
                warnings_to_create.append(
                    ProcessingWarning(
                        id=uuid.uuid4(),
                        document_id=doc_uuid,
                        question_id=q.id,
                        warning_type="answer_unmatched",
                        message=f"No answer key match found for Question {q.question_number or 'unknown'}.",
                        severity="info"
                    )
                )

            # Log warning for partial / needs_review question
            if final_status in ["partial", "needs_review"]:
                warnings_to_create.append(
                    ProcessingWarning(
                        id=uuid.uuid4(),
                        document_id=doc_uuid,
                        question_id=q.id,
                        warning_type="low_confidence_question",
                        message=f"Question {q.question_number or 'unknown'} flagged as {final_status}: {final_reason}",
                        severity="warning"
                    )
                )

            # Update question in DB
            db_q = db.execute(select(Question).where(Question.id == q.id)).scalar_one_or_none()
            if db_q:
                db_q.confidence_score = final_conf
                db_q.status = final_status
                db_q.review_reason = final_reason

        # Persist all processing warnings
        for w in warnings_to_create:
            db.add(w)

        # Final Document status transition
        stmt = select(Document).where(Document.id == doc_uuid)
        document = db.execute(stmt).scalar_one_or_none()
        if document:
            if failed_pages or any(w.severity in ["warning", "critical"] for w in warnings_to_create):
                document.status = "COMPLETED_WITH_WARNINGS" if not failed_pages or len(failed_pages) < document.total_pages else "FAILED"
                document.current_stage = "COMPLETED"
                document.error_message = f"Completed with warnings ({len(warnings_to_create)} warning(s) logged)." if document.status != "FAILED" else "Extraction failed"
            else:
                document.status = "COMPLETED"
                document.current_stage = "COMPLETED"
                document.error_message = None

        db.commit()

    logger.info(
        "[ASYNC WORKER] Document %s pipeline complete. Questions: %d, Warnings: %d, Final Status: %s",
        document_id, len(created_questions), len(warnings_to_create), document.status if document else "UNKNOWN"
    )

    return {
        "document_id": document_id,
        "questions_count": len(created_questions),
        "warnings_count": len(warnings_to_create),
        "status": document.status if document else "COMPLETED"
    }
