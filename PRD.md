# Product Requirements Document
## Document Intelligence & Question Extraction Service

**Version:** 1.0
**Purpose of this document:** This PRD is written to be consumed by an AI coding agent (e.g., Claude Code) as the source of truth for building this system. Every requirement is explicit and scoped. Where the original assignment leaves a decision open, this PRD makes a concrete, documented choice so the agent does not need to guess. Sections are ordered to match a sensible build order.

---

## 1. Project Summary

Build a backend service that accepts PDF documents and images containing exam/question-bank material, processes them asynchronously, and extracts structured, machine-readable questions (with options, question type, source pages, and — where identifiable — answers). The service exposes this functionality via a REST API built with FastAPI, backed by PostgreSQL for persistence and Redis for async task coordination.

The system must NOT assume a single fixed layout. It must handle digital PDFs, scanned PDFs, JPG/PNG images, multi-page questions, varied numbering formats, and answer keys that may live in a separate document.

**Non-goal:** This is not a perfect OCR/NLP research project. The goal is a reliable *engineering system* around imperfect input — confidence scoring and graceful degradation matter more than 100% extraction accuracy.

---

## 2. Actors & Roles

| Role | Capabilities |
|---|---|
| **Authenticated User** | Upload documents, view own documents' status, retrieve own extracted questions/answers/warnings, link related documents |
| **System (background worker)** | Processes documents asynchronously, writes extraction results, updates status |

Keep auth simple: JWT bearer token auth (OAuth2 password flow), single role type is sufficient — no need for admin/multi-tenant complexity unless trivial to add. Every document and its derived data must be scoped to the `owner_user_id` who uploaded it. No cross-user access under any circumstance.

---

## 3. Mandated Technology Stack (do not substitute)

- **API framework:** FastAPI (async endpoints)
- **Primary database:** PostgreSQL (all metadata + structured extracted questions/answers)
- **Async coordination:** Redis (as Celery/ARQ broker and/or cache for job status)
- **Task queue:** Celery with Redis broker (preferred) — ARQ is an acceptable lightweight alternative if the agent judges it faster to implement correctly
- **ORM:** SQLAlchemy (async) with Alembic for migrations
- **Containerization:** Docker + docker-compose (must allow `docker-compose up` to run the full stack: API, worker, Postgres, Redis)
- **Config:** All secrets/config via environment variables (`.env`, loaded via pydantic-settings). Nothing hardcoded. `.env.example` committed, `.env` gitignored.

### Choices left open but must be decided and documented by the agent:
- OCR engine (e.g., Tesseract for local/free, or a cloud OCR/vision API if credentials are available)
- LLM/AI usage for structuring raw OCR/PDF text into questions (recommended: use an LLM with a strict JSON-schema prompt as the core extraction strategy — this is the pragmatic choice for handling layout variance without building custom NLP)
- PDF text-layer parsing library (e.g., PyMuPDF/`fitz` or `pdfplumber`)
- Object storage location (local filesystem under a mounted volume is acceptable for this assignment scope; do not over-engineer S3/MinIO unless time allows)

Document every choice made in `ARCHITECTURE.md` with a one-paragraph rationale and trade-offs.

---

## 4. Processing Pipeline (Core Logic)

This is the heart of the system. Implement as a multi-stage async pipeline, each stage updating job status in Postgres (and optionally cached in Redis for fast polling).

```
UPLOAD → VALIDATE → QUEUE → 
  [STAGE 1: Ingest & normalize]
  [STAGE 2: Text extraction (native text layer OR OCR fallback)]
  [STAGE 3: Layout/question segmentation]
  [STAGE 4: AI-based structuring into question objects]
  [STAGE 5: Answer-key detection & association]
  [STAGE 6: Confidence scoring & review-flagging]
→ COMPLETE (or FAILED / COMPLETED_WITH_WARNINGS)
```

### Stage 1 — Ingest & normalize
- Validate file type (PDF, JPG, JPEG, PNG only) and size limit (define: **max 25MB per file**, configurable via env var).
- Reject malformed/corrupt files with a clear error status, not a silent failure.
- Store the original file in a secure, non-public location keyed by a generated document ID (never trust/use the original filename for storage path).
- For PDFs: split into per-page representations for traceability.
- For images: treat as a single-page document.
- Detect and auto-correct page rotation where feasible (flag if not correctable).

### Stage 2 — Text extraction
- If PDF has a selectable text layer: extract text directly (fast path, e.g., PyMuPDF), page by page, preserving page numbers.
- If PDF has no text layer (scanned) or input is an image: run OCR page by page.
- Always retain: raw extracted text + page number + a quality/confidence signal from the extraction method itself (e.g., OCR engine confidence score if available).

### Stage 3 — Layout/question segmentation
- Do not assume one format. Use a combination of: pattern detection (numbering like `1.`, `Q1`, `(1)`, etc.) and the AI structuring step (Stage 4) to actually determine question boundaries — pure regex will not be robust enough per the assignment's requirements, so treat regex as a *hint generator* feeding into the AI step, not the final decision-maker.
- Track which raw page(s) contributed to each detected question — this is required for source traceability (§7 requirement).
- Handle questions spanning multiple pages by carrying segmentation context across page boundaries (e.g., a question with no terminating marker at the end of a page continues into the next page's leading text before the next detected question marker).

### Stage 4 — AI-based structuring
- Feed segmented raw text (with page metadata) to an LLM with a strict system prompt requiring JSON-only output matching the schema in §8.
- Batch by reasonable chunk size (e.g., per page or small page groups) to stay within context limits and keep cost/latency bounded.
- Each returned question object must include the LLM's own self-reported extraction confidence (ask for this explicitly in the prompt) in addition to any programmatic confidence signals.
- Handle LLM output validation: if the response fails schema validation, retry once with a corrective prompt; if it still fails, mark that segment as `requires_review` with an explicit reason, do not crash the job.

### Stage 5 — Answer-key detection & association
- Treat answer-key detection as its own sub-task: scan all pages (or a linked separate document — see §6) for answer-key-like patterns (e.g., a table/list mapping question numbers to option letters/short answers), again using the LLM to interpret ambiguous formats rather than rigid regex alone.
- Match by question number where possible. Where numbering is ambiguous or missing, attempt best-effort positional/content matching but mark the resulting association with a lower confidence and an explicit `answer_match_method` field (`"number_match"` | `"content_match"` | `"unmatched"`).
- If no reliable answer can be associated, set `answer: null` and `answer_confidence: 0.0` — **never fabricate or guess silently**. This is an explicit hard requirement from the assignment.

### Stage 6 — Confidence scoring & review flagging
- Define a composite confidence score (0.0–1.0) per question, derived from: OCR/text-extraction quality + segmentation certainty + LLM self-reported confidence + answer-match confidence.
- Define explicit status buckets (see §8 schema) rather than only a raw float, so downstream consumers can filter easily:
  - `extracted` (confidence ≥ 0.75)
  - `partial` (0.4 ≤ confidence < 0.75)
  - `needs_review` (confidence < 0.4, or any validation failure occurred)
- Every `needs_review` or `partial` item must carry a human-readable `review_reason` string (e.g., `"OCR confidence low on page 4"`, `"No answer key match found"`, `"Question boundary ambiguous"`).

---

## 5. Async Job Architecture

- On upload, create a `Document` row (status=`PENDING`) and enqueue a Celery task; return immediately to the client with the document ID and a `PROCESSING` status — client must never block on extraction.
- Worker updates `Document.status` through the pipeline stages: `PENDING → PROCESSING → COMPLETED | COMPLETED_WITH_WARNINGS | FAILED`.
- Store granular stage progress (e.g., `current_stage`, `pages_processed`/`total_pages`) so the status endpoint can report meaningful progress, not just a binary flag.
- Support concurrent processing of multiple documents (Celery worker concurrency > 1; do not serialize unnecessarily).
- On failure mid-pipeline, capture the error and persist enough of a partial result (whatever was successfully extracted before the failure) rather than discarding everything.

---

## 6. Multi-Document Relationships

- Add a `DocumentGroup` (or `RelatedDocumentLink`) concept: a user can link two or more documents (e.g., `question_paper.pdf` + `answer_key.pdf`) as related.
- When documents are linked, Stage 5 (answer-key association) must consider the linked document's extracted content as a candidate answer-key source, in addition to same-document answer keys.
- Expose an endpoint to create/view these relationships (see §9).
- A document can belong to at most one group for this assignment's scope (keep it simple — don't build a many-to-many graph unless trivial).

---

## 7. Source Traceability Requirement

Every extracted question **must** retain:
- `source_document_id`
- `source_pages`: array of page numbers it was derived from (supports multi-page questions)
- Enough of a pointer (e.g., stored page image reference or bounding info if easily available) that a human reviewer could pull up the original page and manually verify the question. At minimum, page-level traceability is required; bounding-box-level is a stretch goal, not required.

---

## 8. Data Model (PostgreSQL) — Minimum Required Entities

Exact column types/naming are left to the agent, but these entities and relationships are required:

**User**
- id, email, hashed_password, created_at

**Document**
- id, owner_user_id (FK→User), original_filename, storage_path, file_type (`pdf`|`jpg`|`png`), file_size_bytes, status (`PENDING`|`PROCESSING`|`COMPLETED`|`COMPLETED_WITH_WARNINGS`|`FAILED`), current_stage, total_pages, pages_processed, group_id (nullable FK→DocumentGroup), created_at, updated_at, error_message (nullable)

**DocumentGroup**
- id, owner_user_id, name/label, created_at

**Question**
- id, source_document_id (FK→Document), question_number (nullable string — numbering formats vary), question_text, question_type (`mcq`|`true_false`|`short_answer`|`unknown`), options (JSONB array, nullable), source_pages (int array), confidence_score (float), status (`extracted`|`partial`|`needs_review`), review_reason (nullable text), created_at

**Answer**
- id, question_id (FK→Question, 1:1 or nullable), answer_text (nullable), answer_confidence (float), answer_match_method (`number_match`|`content_match`|`unmatched`|`none`), source_document_id (which doc the answer came from — may differ from question's source doc)

**ProcessingWarning** (or reuse `review_reason` fields, but a dedicated table is preferred for querying "all warnings" easily)
- id, document_id, question_id (nullable — some warnings are document-level, e.g., "page 3 unreadable"), warning_type, message, severity (`info`|`warning`|`critical`), created_at

Provide Alembic migrations for all of the above.

---

## 9. Required API Surface

All endpoints (except health check and auth) require a valid JWT bearer token, and must enforce `owner_user_id` scoping.

| Method | Path | Purpose |
|---|---|---|
| POST | `/auth/register` | Create user |
| POST | `/auth/login` | Obtain JWT |
| POST | `/documents` | Upload a PDF/image (multipart) → returns document_id + status=PENDING |
| GET | `/documents/{id}/status` | Poll processing status + stage progress |
| GET | `/documents/{id}` | Document metadata |
| GET | `/documents` | List user's documents (paginated) |
| GET | `/documents/{id}/questions` | All extracted questions for a document |
| GET | `/questions/{id}` | Single question detail |
| GET | `/questions/{id}/answer` | Answer info for a question |
| GET | `/documents/{id}/warnings` | Review/warning items for a document |
| POST | `/document-groups` | Create a group linking related documents (e.g., paper + key) |
| GET | `/document-groups/{id}` | View a group and its linked documents |
| GET | `/health` | Liveness check (no auth) |

Additional endpoints (e.g., re-trigger processing, delete document) are welcome but optional.

All endpoints must have:
- Pydantic request/response models (drives correct OpenAPI/Swagger docs automatically)
- Proper HTTP status codes (400 validation, 401/403 auth, 404 not found, 413 file too large, 422 unprocessable, 500 with safe generic message — never leak internals)
- Input validation on file type/size at the API layer, before hitting the queue

---

## 10. Structured Output Schema (per question, API response shape)

```json
{
  "id": "uuid",
  "question_number": "12" ,
  "question_text": "What is the time complexity of binary search?",
  "question_type": "mcq",
  "options": [
    {"label": "A", "text": "O(n)"},
    {"label": "B", "text": "O(log n)"},
    {"label": "C", "text": "O(n^2)"},
    {"label": "D", "text": "O(1)"}
  ],
  "answer": {
    "value": "B",
    "confidence": 0.92,
    "match_method": "number_match"
  },
  "source_document_id": "uuid",
  "source_pages": [4],
  "confidence": 0.88,
  "status": "extracted",
  "review_reason": null
}
```

When answer is unknown: `"answer": {"value": null, "confidence": 0.0, "match_method": "unmatched"}`.

---

## 11. Security Requirements

- Passwords hashed with bcrypt/argon2 (never plaintext, never reversible encryption).
- JWT with reasonable expiry (e.g., 24h) + refresh not required for this scope.
- File upload validation: reject by content-type sniffing, not just extension (avoid a `.pdf`-named executable).
- File size limit enforced server-side (not just client-side).
- Storage paths never derived from user-supplied filenames directly (prevent path traversal).
- All external AI/OCR API keys loaded from environment variables only, never logged, never returned in any API response.
- Document/question/answer access strictly filtered by `owner_user_id` at the query level (not just at the route level) — write this as a reusable dependency/helper, not repeated inline per endpoint.
- Rate limiting on upload endpoint is a nice-to-have, not required.

---

## 12. Error Handling & Resilience

- A single page/question failing extraction must not fail the entire document job — isolate failures per-unit where possible, mark that unit as `needs_review`, and continue.
- Worker tasks must be idempotent or safely retryable (e.g., use `acks_late` / re-run safe design) in case of worker crash mid-job.
- Malformed/unsupported uploads must return a clear 4xx error at upload time where detectable, or transition the document to `FAILED` with `error_message` populated if the problem is only discoverable during processing.

---

## 13. Testing Requirements

- Unit tests for: schema validation, confidence-scoring logic, answer-matching logic, auth/authorization scoping.
- Integration tests (via FastAPI `TestClient`/`httpx`) for the full API flow: register → login → upload → poll status → retrieve questions → retrieve answers → retrieve warnings.
- At least one test using a deliberately malformed/invalid file to confirm graceful rejection.
- Tests should not require live external OCR/LLM calls — mock the OCR/AI layer in tests (inject via dependency/interface so this is easy).

---

## 14. Deliverables Checklist (map directly to assignment §13)

- [ ] Complete source code (this repo)
- [ ] Alembic migrations
- [ ] Sample input documents (at least: one digital PDF, one scanned/low-quality PDF or image, one separate answer-key document)
- [ ] Sample extracted output (JSON export committed to `/samples/`)
- [ ] `SETUP.md` — how to run via docker-compose, env vars needed, how to seed a test user
- [ ] `ARCHITECTURE.md` — covers: overall architecture, processing approach, OCR/AI choices + rationale, storage design, async processing design, extraction strategy, answer-key association approach, confidence/review mechanism, security considerations, scalability considerations, known trade-offs/limitations. Include at least one architecture diagram (Mermaid is fine).
- [ ] Automated tests (pytest)
- [ ] Postman collection covering the full demo workflow (§15 below)
- [ ] Swagger/OpenAPI (auto-generated by FastAPI at `/docs` — confirm it renders cleanly with proper models)
- [ ] Demonstration evidence (screenshots or a short script/log output) for each of the 10 scenarios in §15

---

## 15. Demonstration Scenarios (must all be runnable/showable)

1. Upload a digital PDF.
2. Upload a standalone image (JPG/PNG).
3. Process a scanned/low-quality document.
4. Extract multiple questions from one document.
5. Correctly handle a question spanning multiple pages.
6. Extract question options (MCQ).
7. Detect an answer key and associate it with questions (including the linked-document case from §6).
8. Show at least one genuinely low-confidence/`needs_review` extraction with a populated `review_reason`.
9. Retrieve final structured question data via the API.
10. Attempt to upload an invalid/unsupported file and show the correct rejection behavior.

---

## 16. Explicit Non-Requirements (to keep scope bounded for the time budget)

- No frontend UI is required — API + Swagger docs is sufficient.
- No multi-tenant admin roles.
- No horizontal-scaling infrastructure (K8s, etc.) — describe scalability approach in `ARCHITECTURE.md` conceptually rather than implementing it.
- No requirement for perfect OCR/extraction accuracy — the system is evaluated on how it *handles* uncertainty, not on achieving 100% correctness.
- Bounding-box-level source traceability is a stretch goal only; page-level traceability is the hard requirement.

---

## 17. Suggested Build Order (for the agent to follow sequentially)

1. Repo scaffold + docker-compose (Postgres, Redis, API, worker) + health check endpoint.
2. Auth (register/login/JWT) + `User` model/migration.
3. `Document` model/migration + upload endpoint (validation, storage, DB row, status=PENDING) — no processing yet.
4. Celery worker wiring + a no-op task that just flips status to COMPLETED, to prove the async plumbing end-to-end.
5. Stage 2 (text extraction: native + OCR fallback) wired into the real task.
6. Stage 3+4 (segmentation + AI structuring) → `Question` model/migration + persistence.
7. Stage 5+6 (answer-key detection/association + confidence/review) → `Answer` + `ProcessingWarning` models/migrations.
8. Remaining read endpoints (`/questions/{id}`, `/documents/{id}/warnings`, etc.).
9. `DocumentGroup` support + wiring into Stage 5.
10. Security hardening pass (ownership checks, file validation, error message sanitization).
11. Tests.
12. Postman collection + sample docs/output + `ARCHITECTURE.md` + `SETUP.md`.
13. Full run-through of all 10 demo scenarios, capture evidence.

---

*End of PRD.*
