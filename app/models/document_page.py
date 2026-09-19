from datetime import datetime, timezone
import uuid
from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class DocumentPage(Base):
    __tablename__ = "document_pages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    page_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        index=True
    )
    raw_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default=""
    )
    extraction_method: Mapped[str] = mapped_column(
        String(50),
        nullable=False # 'native_text' | 'ocr_tesseract' | 'failed'
    )
    confidence: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Relationships
    document = relationship("Document", backref="pages")

    def __repr__(self) -> str:
        return f"<DocumentPage doc_id={self.document_id} page={self.page_number} method={self.extraction_method} conf={self.confidence}>"
