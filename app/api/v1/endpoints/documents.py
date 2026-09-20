from typing import Any, List, Optional
import uuid
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi.responses import PlainTextResponse
from app.api.deps import get_current_user, get_current_user_or_default, get_owned_document
from app.core.database import get_db
from app.models.document import Document
from app.models.document_page import DocumentPage
from app.models.user import User
from app.schemas.document import (
    DocumentCreateResponse,
    DocumentExtractionResultResponse,
    DocumentExtractionSummary,
    DocumentListResponse,
    DocumentResponse,
    DocumentStatusResponse,
    HumanReadableQuestionItem,
    HumanReadableQuestionOption,
)
from app.schemas.document_page import DocumentPageResponse
from app.services.file_validation import validate_file_content
from app.services.storage import save_upload_file

router = APIRouter()


@router.post(
    "/extract",
    status_code=status.HTTP_200_OK,
    summary="Upload Document & Show Human-Readable Extraction Results",
    description=(
        "Upload a PDF or image file (max 25MB) and directly receive the extracted questions, "
        "MCQ options, verified answer keys, and a clean human-readable output report rendered with proper line breaks."
    ),
    response_model=DocumentExtractionResultResponse,
    responses={
        200: {
            "content": {
                "text/plain": {
                    "schema": {"type": "string"},
                    "example": "DOCUMENT INTELLIGENCE REPORT\n..."
                },
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/DocumentExtractionResultResponse"}
                }
            },
            "description": "Human-readable formatted exam report (default) or structured JSON."
        }
    }
)
async def extract_document_questions(
    file: UploadFile = File(..., description="Document file to upload (PDF, PNG, JPG)"),
    answer_key_file: Optional[UploadFile] = File(None, description="Optional standalone answer key file (PDF, PNG, JPG)"),
    format: str = Query("text", description="Output format: 'text' (human-readable formatted exam) or 'json' (structured JSON)"),
    current_user: User = Depends(get_current_user_or_default),
    db: AsyncSession = Depends(get_db)
) -> Any:

    """Upload document, execute processing pipeline, and return human-readable structured results immediately."""
    # 1. Byte-level MIME sniffing validation
    header_bytes = await file.read(2048)
    filename = file.filename or "unknown"
    file_type = validate_file_content(header_bytes, filename)
    doc_id = uuid.uuid4()

    # 2. Save document to disk
    storage_path, file_size_bytes = await save_upload_file(
        upload_file=file,
        doc_id=doc_id,
        file_type=file_type,
        first_chunk=header_bytes
    )

    new_doc = Document(
        id=doc_id,
        owner_user_id=current_user.id,
        original_filename=filename,
        storage_path=storage_path,
        file_type=file_type,
        file_size_bytes=file_size_bytes,
        status="PENDING",
        current_stage="UPLOADED",
        total_pages=0,
        pages_processed=0
    )
    db.add(new_doc)
    await db.commit()
    await db.refresh(new_doc)

    # 3. Optional standalone answer key linking via DocumentGroup
    if answer_key_file and answer_key_file.filename:
        from app.models.document_group import DocumentGroup
        group = DocumentGroup(
            id=uuid.uuid4(),
            owner_user_id=current_user.id,
            name=f"Group: {filename} + {answer_key_file.filename}"
        )
        db.add(group)
        await db.flush()

        new_doc.group_id = group.id

        key_header = await answer_key_file.read(2048)
        key_type = validate_file_content(key_header, answer_key_file.filename)
        key_id = uuid.uuid4()
        key_storage, key_size = await save_upload_file(
            upload_file=answer_key_file,
            doc_id=key_id,
            file_type=key_type,
            first_chunk=key_header
        )
        key_doc = Document(
            id=key_id,
            owner_user_id=current_user.id,
            original_filename=answer_key_file.filename,
            storage_path=key_storage,
            file_type=key_type,
            file_size_bytes=key_size,
            status="PENDING",
            current_stage="UPLOADED",
            group_id=group.id,
            total_pages=0,
            pages_processed=0
        )
        db.add(key_doc)
        await db.commit()

        # Process key first synchronously
        from app.workers.tasks import process_document
        process_document(str(key_doc.id))

    # 4. Process document synchronously to return results immediately
    from app.workers.tasks import process_document
    process_document(str(new_doc.id))

    # 5. Query extracted results
    from sqlalchemy.orm import selectinload
    from app.models.question import Question

    q_stmt = (
        select(Question)
        .options(selectinload(Question.answer))
        .where(Question.source_document_id == new_doc.id)
        .order_by(Question.created_at.asc())
    )
    questions = (await db.execute(q_stmt)).scalars().all()

    pages_stmt = (
        select(DocumentPage)
        .where(DocumentPage.document_id == new_doc.id)
        .order_by(DocumentPage.page_number.asc())
    )
    pages = (await db.execute(pages_stmt)).scalars().all()

    # Refresh document metadata
    await db.refresh(new_doc)

    # 6. Format human-readable text and response items
    total_q = len(questions)
    verified_q = sum(1 for q in questions if q.status == "verified" or (q.confidence_score >= 0.8 and q.status != "needs_review"))
    needs_review_q = sum(1 for q in questions if q.status == "needs_review" or q.status == "partial")
    avg_conf = f"{round((sum(q.confidence_score for q in questions) / total_q) * 100)}%" if total_q > 0 else "0%"

    has_ocr = any("ocr" in (p.extraction_method or "").lower() for p in pages)
    engine = "Tesseract OCR (200 DPI)" if has_ocr else "Native Digital PDF"

    lines = []
    lines.append("=" * 80)
    lines.append("           DOCUMENT INTELLIGENCE — QUESTION EXTRACTION REPORT                   ")
    lines.append("=" * 80)
    lines.append(f"Document Name:    {new_doc.original_filename}")
    lines.append(f"Extraction Mode:  {engine}")
    lines.append(f"Total Pages:      {new_doc.total_pages or len(pages)} page(s)")
    lines.append(f"Questions Found:  {total_q} question(s)")
    lines.append(f"Quality Summary:  {avg_conf} Average Confidence ({verified_q} Verified, {needs_review_q} Needs Review)")
    lines.append("=" * 80)
    lines.append("")

    q_items = []
    for q in questions:
        ans_val = q.answer.answer_text.strip().upper() if q.answer and q.answer.answer_text else None
        ans_conf = q.answer.answer_confidence if q.answer else None
        ans_method = q.answer.answer_match_method if q.answer else "unmatched"

        source_pages_str = ", ".join(str(p) for p in q.source_pages) if q.source_pages else "1"
        spanning_str = " (Spanning Question)" if q.source_pages and len(q.source_pages) > 1 else ""
        conf_pct = f"{round((q.confidence_score or 0) * 100)}%"

        lines.append(f"QUESTION {q.question_number}  [Page {source_pages_str}{spanning_str}]  |  Confidence: {conf_pct}  |  Status: {q.status.upper()}")
        lines.append("-" * 80)
        lines.append(f"{q.question_text}")
        lines.append("")

        opts = []
        if q.options and isinstance(q.options, list):
            lines.append("Options:")
            for opt in q.options:
                lbl = opt.get("label", "")
                txt = opt.get("text", "")
                is_correct = bool(ans_val and lbl.upper() == ans_val)
                opts.append(HumanReadableQuestionOption(label=lbl, text=txt, is_correct=is_correct))

                if is_correct:
                    lines.append(f"  [*] {lbl}. {txt}   <-- VERIFIED ANSWER (Match: {ans_method} | Confidence: {round((ans_conf or 0)*100)}%)")
                else:
                    lines.append(f"  [ ] {lbl}. {txt}")
            lines.append("")
        elif ans_val:
            lines.append(f"Verified Answer: {ans_val} (Match: {ans_method} | Confidence: {round((ans_conf or 0)*100)}%)")
            lines.append("")

        if q.review_reason:
            lines.append(f"  >>> NOTE FOR REVIEW: {q.review_reason}")
            lines.append("")

        lines.append("-" * 80)
        lines.append("")

        q_items.append(HumanReadableQuestionItem(
            question_number=str(q.question_number),
            question_text=q.question_text,
            question_type=q.question_type or "mcq",
            source_pages=q.source_pages or [1],
            confidence=round(q.confidence_score or 0.0, 2),
            status=q.status,
            options=opts if opts else None,
            verified_answer=ans_val,
            answer_match_method=ans_method,
            answer_confidence=round(ans_conf, 2) if ans_conf is not None else None,
            review_reason=q.review_reason
        ))

    lines.append("=" * 80)
    lines.append("                            END OF EXTRACTED REPORT                             ")
    lines.append("=" * 80)

    summary_obj = DocumentExtractionSummary(
        document_name=new_doc.original_filename,
        status=new_doc.status,
        total_pages=new_doc.total_pages or len(pages),
        extraction_engine=engine,
        total_questions=total_q,
        verified_questions=verified_q,
        needs_review_questions=needs_review_q,
        average_confidence=avg_conf
    )

    if format.lower() == "json":
        return DocumentExtractionResultResponse(
            document_id=new_doc.id,
            summary=summary_obj,
            human_readable_results="\n".join(lines),
            questions=q_items
        )

    return PlainTextResponse(
        content="\n".join(lines),
        media_type="text/plain; charset=utf-8"
    )



@router.post(
    "",
    response_model=DocumentCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload Document (Asynchronous)",
    description="Upload a PDF or image file (max 25MB). Validates content-type via byte-level MIME sniffing and enqueues async background processing."
)
async def upload_document(
    file: UploadFile = File(..., description="Document file to upload (PDF, JPG, PNG)"),
    current_user: User = Depends(get_current_user_or_default),
    db: AsyncSession = Depends(get_db)
) -> Any:

    """Upload and validate document, saving it to secure UUID-keyed storage."""
    # Read the initial chunk (up to 2048 bytes) for MIME sniffing
    header_bytes = await file.read(2048)
    filename = file.filename or "unknown"

    # Byte-level MIME sniffing validation
    file_type = validate_file_content(header_bytes, filename)

    # Generate isolated Document UUID
    doc_id = uuid.uuid4()

    # Save to disk with 25MB server-side streaming enforcement
    storage_path, file_size_bytes = await save_upload_file(
        upload_file=file,
        doc_id=doc_id,
        file_type=file_type,
        first_chunk=header_bytes
    )

    # Persist document metadata row in PostgreSQL
    new_doc = Document(
        id=doc_id,
        owner_user_id=current_user.id,
        original_filename=filename,
        storage_path=storage_path,
        file_type=file_type,
        file_size_bytes=file_size_bytes,
        status="PENDING",
        current_stage="UPLOADED",
        total_pages=0,
        pages_processed=0
    )
    db.add(new_doc)
    await db.commit()
    await db.refresh(new_doc)

    # Enqueue async processing task via Celery
    from app.workers.tasks import process_document
    process_document.delay(str(new_doc.id))

    return new_doc


@router.get(
    "/{document_id}/status",
    response_model=DocumentStatusResponse,
    summary="Poll Document Processing Status",
    description="Returns processing status and pipeline stage progress for an owned document."
)
async def get_document_status(
    document: Document = Depends(get_owned_document)
) -> Any:
    """Poll document processing status with strict user isolation via shared dependency (PRD §11)."""
    return document


@router.get(
    "/{document_id}",
    response_model=DocumentResponse,
    summary="Get Document Metadata",
    description="Returns full metadata for an owned document."
)
async def get_document_metadata(
    document: Document = Depends(get_owned_document)
) -> Any:
    """Retrieve document metadata with strict user isolation via shared dependency (PRD §11)."""
    return document


@router.get(
    "",
    response_model=DocumentListResponse,
    summary="List User Documents",
    description="Returns paginated list of documents owned by the authenticated user."
)
async def list_documents(
    skip: int = Query(0, ge=0, description="Offset for pagination"),
    limit: int = Query(20, ge=1, le=100, description="Limit for pagination"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> Any:
    """List documents belonging to the authenticated user."""
    # Count total
    count_stmt = select(func.count(Document.id)).where(Document.owner_user_id == current_user.id)
    total = (await db.execute(count_stmt)).scalar() or 0

    # Query items
    query = (
        select(Document)
        .where(Document.owner_user_id == current_user.id)
        .order_by(desc(Document.created_at))
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(query)
    items = result.scalars().all()

    return {
        "total": total,
        "items": items
    }


@router.get(
    "/{document_id}/pages",
    response_model=List[DocumentPageResponse],
    summary="Get Extracted Pages",
    description="Returns raw extracted text, extraction method (native vs OCR), and confidence score per page."
)
async def get_document_pages(
    document: Document = Depends(get_owned_document),
    db: AsyncSession = Depends(get_db)
) -> Any:
    """Retrieve raw extracted pages for an owned document via shared dependency (PRD §11)."""
    # Fetch pages ordered by page_number
    pages_stmt = (
        select(DocumentPage)
        .where(DocumentPage.document_id == document.id)
        .order_by(DocumentPage.page_number.asc())
    )
    pages_result = await db.execute(pages_stmt)
    pages = pages_result.scalars().all()

    return pages


