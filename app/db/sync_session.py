from contextlib import contextmanager
from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

# Synchronous engine and session for Celery workers
sync_engine = create_engine(
    settings.sync_database_url,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)

SyncSessionLocal = sessionmaker(
    bind=sync_engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


@contextmanager
def get_sync_db() -> Generator[Session, None, None]:
    """Context manager providing a synchronous DB session for background worker tasks."""
    session = SyncSessionLocal()
    try:
        yield session
    finally:
        session.close()
