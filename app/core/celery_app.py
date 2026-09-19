from celery import Celery
from app.core.config import settings

celery_app = Celery(
    "document_intelligence_worker",
    broker=settings.celery_broker,
    backend=settings.celery_backend,
    include=["app.workers.tasks"]
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    # Resilience settings per PRD §5 & §12
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)
