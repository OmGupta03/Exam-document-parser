import logging
import time
import uuid
from celery import shared_task
from sqlalchemy import select

from app.core.celery_app import celery_app
from app.db.sync_session import get_sync_db
from app.models.document import Document

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
    Background worker pipeline task.
    Step 4: Proves async plumbing end-to-end with no-op execution:
    PENDING -> PROCESSING -> COMPLETED.
    """
    doc_uuid = uuid.UUID(document_id)
    logger.info("[ASYNC WORKER] Starting processing for document_id=%s (task_id=%s)", document_id, self.request.id)

    with get_sync_db() as db:
        stmt = select(Document).where(Document.id == doc_uuid)
        document = db.execute(stmt).scalar_one_or_none()

        if not document:
            logger.error("[ASYNC WORKER] Document not found: %s", document_id)
            return {"error": "Document not found", "document_id": document_id}

        # 1. Transition PENDING -> PROCESSING
        document.status = "PROCESSING"
        document.current_stage = "NOOP_PROCESSING"
        db.commit()
        logger.info("[ASYNC WORKER] Transitioned document %s to status=PROCESSING, stage=%s", document_id, document.current_stage)

    # Simulate realistic async pipeline execution (1.5s delay)
    time.sleep(1.5)

    # 2. Transition PROCESSING -> COMPLETED
    with get_sync_db() as db:
        stmt = select(Document).where(Document.id == doc_uuid)
        document = db.execute(stmt).scalar_one_or_none()

        if document:
            document.status = "COMPLETED"
            document.current_stage = "COMPLETED"
            document.total_pages = 1
            document.pages_processed = 1
            db.commit()
            logger.info("[ASYNC WORKER] Transitioned document %s to status=COMPLETED", document_id)

    return {
        "document_id": document_id,
        "status": "COMPLETED",
        "task_id": self.request.id
    }
