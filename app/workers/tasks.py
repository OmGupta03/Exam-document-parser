import logging
import uuid
from celery import shared_task
from sqlalchemy import delete, select

from app.core.celery_app import celery_app
from app.db.sync_session import get_sync_db
from app.models.document import Document
from app.models.document_page import DocumentPage
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
    Stage 1 & 2 Background Worker Pipeline per PRD §4 & §17 Step 5.
    - Native PyMuPDF text layer extraction for digital PDFs.
    - Tesseract OCR fallback for scanned pages and images (JPG/PNG).
    - Page-level failure isolation per PRD §12.
    - Persists raw text and confidence signals to DocumentPage entity.
    """
    doc_uuid = uuid.UUID(document_id)
    logger.info("[ASYNC WORKER] Starting text extraction for document_id=%s (task_id=%s)", document_id, self.request.id)

    # 1. Update status to PROCESSING / TEXT_EXTRACTION
    with get_sync_db() as db:
        stmt = select(Document).where(Document.id == doc_uuid)
        document = db.execute(stmt).scalar_one_or_none()

        if not document:
            logger.error("[ASYNC WORKER] Document %s not found in database", document_id)
            return {"error": "Document not found", "document_id": document_id}

        document.status = "PROCESSING"
        document.current_stage = "TEXT_EXTRACTION"
        db.commit()

        storage_path = document.storage_path
        file_type = document.file_type

    # 2. Execute Stage 1 & 2 Text Extraction (Native PyMuPDF / Tesseract OCR)
    page_results = extract_document_pages(storage_path=storage_path, file_type=file_type)

    # 3. Persist extracted pages & update document status with failure isolation
    with get_sync_db() as db:
        stmt = select(Document).where(Document.id == doc_uuid)
        document = db.execute(stmt).scalar_one_or_none()

        if not document:
            return {"error": "Document lost during processing", "document_id": document_id}

        # Clear any existing pages if this is an idempotent retry
        db.execute(delete(DocumentPage).where(DocumentPage.document_id == doc_uuid))

        failed_pages = []
        for page_res in page_results:
            new_page = DocumentPage(
                document_id=doc_uuid,
                page_number=page_res.page_number,
                raw_text=page_res.raw_text,
                extraction_method=page_res.extraction_method,
                confidence=page_res.confidence
            )
            db.add(new_page)
            if page_res.extraction_method == "failed":
                failed_pages.append(page_res.page_number)

        document.total_pages = len(page_results)
        document.pages_processed = len(page_results)

        # Status transition handling per PRD §12 (Graceful degradation & per-unit isolation)
        if len(failed_pages) == len(page_results) and len(page_results) > 0:
            document.status = "FAILED"
            document.current_stage = "EXTRACTION_FAILED"
            document.error_message = "All pages failed text extraction."
            logger.error("[ASYNC WORKER] All pages failed for document %s", document_id)
        elif failed_pages:
            document.status = "COMPLETED_WITH_WARNINGS"
            document.current_stage = "EXTRACTION_COMPLETED"
            document.error_message = f"Extraction failed on page(s): {failed_pages}"
            logger.warning("[ASYNC WORKER] Document %s completed with warnings on pages %s", document_id, failed_pages)
        else:
            document.status = "COMPLETED"
            document.current_stage = "EXTRACTION_COMPLETED"
            document.error_message = None
            logger.info(
                "[ASYNC WORKER] Document %s extraction completed successfully (%d page(s))",
                document_id, len(page_results)
            )

        db.commit()

    return {
        "document_id": document_id,
        "total_pages": len(page_results),
        "status": document.status,
        "methods": [p.extraction_method for p in page_results]
    }
