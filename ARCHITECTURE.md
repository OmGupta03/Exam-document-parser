# System Architecture & Technical Decisions

**Document Intelligence & Question Extraction Service**
**Version:** 1.0.0
**Status:** In Active Development (Build Order Step 1 completed)

---

## 1. High-Level Architecture Overview

The system is structured as an asynchronous, distributed backend designed to accept unstructured or semi-structured documents (PDFs, images), persist raw documents securely, queue extraction tasks, coordinate multi-stage processing pipelines across background workers, and expose clean REST APIs for status tracking and structured question retrieval.

```mermaid
flowchart TD
    Client[REST Client / Postman / Swagger]
    
    subgraph FastAPI Layer
        API[FastAPI Service :8000]
        HealthCheck[/health Endpoint]
        AuthModule[Auth & Security Module]
        DocRouter[Document & Question Routers]
    end

    subgraph Storage & Broker
        PG[(PostgreSQL 16\nMetadata & Structured Data)]
        Redis[(Redis 7\nBroker & Result Backend)]
        StorageDir[Local Volume Storage\n/app/storage/uploads]
    end

    subgraph Background Processing
        Worker[Celery Worker Cluster\nconcurrency=2, acks_late=True]
        Stage1[Stage 1: Ingestion & Validation]
        Stage2[Stage 2: PyMuPDF / Tesseract OCR]
        Stage3[Stage 3: Question Segmentation]
        Stage4[Stage 4: Pluggable AI Structuring]
        Stage5[Stage 5: Answer-Key Association]
        Stage6[Stage 6: Confidence Scoring & Warnings]
    end

    Client -->|HTTP / JSON| API
    API --> HealthCheck
    HealthCheck -.->|Ping| PG
    HealthCheck -.->|PING| Redis
    API -->|Write Metadata / Read Status| PG
    API -->|Enqueue Task| Redis
    API -->|Save Uploaded File| StorageDir
    Redis -->|Consume Task| Worker
    Worker -->|Fetch File| StorageDir
    Worker --> Stage1 --> Stage2 --> Stage3 --> Stage4 --> Stage5 --> Stage6
    Worker -->|Update Status & Extracted Entities| PG
```

---

## 2. Core Architectural Decisions & Rationale

Per PRD §3, several technology and implementation choices are left open to engineering judgment. The decisions made, along with their rationale and trade-offs, are documented below.

### 2.1 OCR Engine: Tesseract OCR + PyMuPDF Dual-Path
- **Decision:** Use **PyMuPDF (`fitz`)** for the primary digital text extraction path, combined with **Tesseract OCR (via `pytesseract`)** as an automated fallback for scanned documents and image formats (JPEG, PNG).
- **Rationale:** Digital PDFs contain rich, selectable text layers that can be parsed orders of magnitude faster (milliseconds per page) and with 100% character fidelity compared to optical character recognition. Running OCR unconditionally on digital PDFs wastes compute and introduces recognition errors. When a page has no selectable text or when processing standalone images, the pipeline gracefully falls back to Tesseract OCR with image pre-processing (contrast/grayscale normalization).
- **Trade-offs:** Tesseract is a local, open-source OCR engine with no per-call API cost and zero cloud dependencies, making the service entirely self-contained within Docker. The trade-off is slightly lower accuracy on severely degraded or handwritten text compared to proprietary cloud vision APIs (e.g., Google Cloud Vision or AWS Textract).

### 2.2 AI Structuring Strategy: Pluggable Interface with Strict JSON-Schema
- **Decision:** Implement a pluggable AI provider architecture (`AI_PROVIDER`: `mock`, `openai`, `gemini`) with explicit JSON Schema prompts and schema validation retry loops.
- **Rationale:** Regex heuristics fail when dealing with diverse exam layouts, column splits, multi-page question continuations, and varied option identifiers. An LLM acts as an intelligent arbiter for segmentation and structuring. Providing a pluggable adapter ensures the system can run locally without external API keys (using a deterministic rule-based mock provider for automated test suites and offline demos) or connect to production LLMs (GPT-4o-mini / Gemini Flash) for high-accuracy production inference.
- **Trade-offs:** Requires defensive validation and retry loops to handle potential schema hallucinations or context truncation, which are addressed in Stage 4.

### 2.3 Task Queue & Coordination: Celery with Redis Broker
- **Decision:** Celery 5.4 backed by Redis 7 with `task_acks_late=True` and `worker_prefetch_multiplier=1`.
- **Rationale:** Celery provides robust task scheduling, distributed worker scaling, and task retry mechanisms out of the box. Setting `task_acks_late=True` guarantees that if a worker crashes mid-task, the job remains unacknowledged in Redis and is re-queued for another worker. Setting `worker_prefetch_multiplier=1` prevents long-running document processing tasks from being monopolized by a single busy worker process.
- **Trade-offs:** Celery has a slightly higher configuration footprint compared to lightweight async alternatives like ARQ, but offers superior ecosystem maturity, monitoring, and task state tracking.

### 2.4 Object Storage: Volume-Mounted Local Filesystem
- **Decision:** Volume-mounted local storage (`/app/storage/uploads`) utilizing UUID-keyed file paths.
- **Rationale:** Local volume storage completely eliminates external cloud storage dependencies (e.g., S3/MinIO) for containerized deployments while satisfying the 24-hour take-home scope. Files are saved using strictly generated UUID keys (e.g., `/app/storage/uploads/{document_id}/{filename_uuid}.ext`), eliminating path traversal vulnerabilities and decoupling storage from untrusted user-supplied filenames.
- **Trade-offs:** Storage is tied to the host volume; scaling horizontally across multiple physical nodes would eventually require shared network storage (NFS) or S3-compatible object stores, which can be slotted in seamlessly behind our storage abstraction.

### 2.5 Health Check & Degraded State Handling
- **Decision:** Implement active dependency health probes on `/health` returning HTTP 200 (`status: "healthy"`) when all dependencies are reachable, and HTTP 503 (`status: "unhealthy"`) with granular component reports (`database: "connected" | "disconnected"`, `redis: "connected" | "disconnected"`) when any dependency is degraded.
- **Rationale:** Production orchestrators and load balancers rely on non-200 HTTP status codes to prevent routing traffic to degraded pods. Reporting granular component states provides immediate operational telemetry for automated alert routing.

### 2.6 Authentication & Multi-User Isolation
- **Decision:** JWT Bearer authentication with passlib/bcrypt password hashing, accompanied by a reusable `get_current_user` dependency that resolves the authenticated `User` from PostgreSQL on each protected request.
- **Rationale:** Strict user isolation is mandated by PRD §2 ("No cross-user access under any circumstance") and PRD §11 ("access strictly filtered by owner_user_id at the query level"). Decoupling auth into standard OAuth2 password flow with JWT bearer tokens enables stateless token validation at API gateways while maintaining query-level scoping guarantees in application code.
- **Trade-offs:** Stateless JWT tokens are valid until expiration (24 hours). For the current take-home scope, token revocation lists or refresh token rotation are excluded per PRD §11, which is acceptable given the single-role architecture.

### 2.7 Layout Segmentation & Multi-Page Context Carrying (PRD §4 Stage 3)
- **Decision:** Use regex pattern matching (`1.`, `Q1`, `(1)`) as candidate hints, not final arbiter, and carry segmentation context across page boundaries.
- **Rationale:** Hard regex fails when exams use nested lists or multi-line questions. By treating regex as hint generators and tracking candidate question boundaries across consecutive pages, questions that begin at the bottom of page $N$ (e.g. question prompt) and conclude on page $N+1$ (e.g. options A-D) maintain continuity. The contributing pages are recorded in the `source_pages` array (`ARRAY(Integer)`).
- **Trade-offs:** Context window and token costs must be managed when chunking pages for AI analysis. Grouping adjacent pages or passing multi-page question blocks preserves boundary context without unbounded token expansion.

### 2.8 Resilient Schema Validation & Fault Isolation (PRD §4 Stage 4 & PRD §12)
- **Decision:** Two-stage retry for LLM structured outputs with automatic fallback to `status="needs_review"` upon repeated schema validation failure. Individual page failures isolate without failing the parent document.
- **Rationale:** LLM JSON outputs may occasionally contain trailing commas, missing keys, or syntax errors. Attempting a single corrective prompt resolves 95%+ of structural defects. If validation still fails, rather than raising an unhandled exception that kills the Celery task, the segment is persisted with `status="needs_review"`, `options=null`, and a detailed `review_reason`. Similarly, if a single corrupted page fails extraction, the document reaches `COMPLETED_WITH_WARNINGS` with the remaining valid pages extracted.

### 2.9 Unified & Reconciled Composite Confidence Model (PRD §4 Stage 6)
- **Decision:** Explicit two-phase scoring lifecycle within the same processing run: Stage 4 computes an initial Question Extraction Confidence, and Stage 6 recomputes and overwrites `Question.confidence_score` in-place using the final composite formula (replacing the Stage 4 value before the document reaches `COMPLETED`).
- **Rationale & Mathematical Formulation:**
  1. **Phase 1: Question Extraction Quality (Stage 4):**
     $$\text{question\_conf} = \text{round}((\text{upstream\_ocr\_conf} \times 0.40) + (\text{llm\_self\_reported\_conf} \times 0.60), 2)$$
     This measures the fidelity of the raw text and the structural validity of the parsed question.
  2. **Phase 2: In-Place Recomputation & Final Composite Confidence (Stage 6):**
     Within the same task execution, after Stage 5 finishes answer-key association, Stage 6 updates `Question.confidence_score` in PostgreSQL:
     - When an answer key is present (same-document or linked document group):
       $$\text{final\_composite} = \text{round}((\text{question\_conf} \times 0.80) + (\text{answer\_match\_conf} \times 0.20), 2)$$
       Where `answer_match_conf` is `0.95` for exact `number_match`, `0.70` for `content_match`, and `0.0` for `unmatched`. This replaces the Stage 4 extraction score with the definitive composite score.
     - When no answer key exists for the document (standalone question paper):
       $$\text{final\_composite} = \text{question\_conf}$$
  3. **Status Bucketing:**
     - `extracted`: $\text{final\_composite} \ge 0.75$
     - `partial`: $0.40 \le \text{final\_composite} < 0.75$
     - `needs_review`: $\text{final\_composite} < 0.40$ or any schema validation failure occurred.
  This reconciles Step 6 and Step 7 into a single, cohesive mathematical model that avoids unfairly penalizing standalone question papers while accurately incorporating answer-key verification.

### 2.10 Cross-Document Answer-Key Resolution (PRD §4 Stage 5 & PRD §6)
- **Decision:** DocumentGroup abstraction linking related documents (e.g. `question_paper.pdf` + `answer_key.pdf`) with two-tier matching and strict non-fabrication guarantee.
- **Rationale:** Exams frequently split questions and solutions across separate files. When documents share a `group_id`, the worker pools candidate text from all linked documents. Questions try `number_match` first; fall back to `content_match` *only* if the question is unnumbered/ambiguous with meaningful token overlap; and default to `answer: null`, `confidence: 0.0`, `match_method: "unmatched"` if no key is present. Unmatched items log non-blocking `ProcessingWarning` records.

---

---

## 3. Security Architecture & Threat Model

Per PRD §11 and §16, the system enforces end-to-end multi-tenant security:
- **Shared Query-Level Ownership Scoping:** Access to documents, questions, answers, warnings, and document groups is strictly filtered by `owner_user_id == current_user.id` using reusable FastAPI dependencies (`get_owned_document`, `get_owned_question`, `get_owned_document_group` in `app/api/deps.py`). Cross-user access returns HTTP 404 cleanly, preventing enumeration of resource existence.
- **Storage Path Sanitization:** Uploaded filenames are stored solely for display. Files on disk are organized into `/app/storage/uploads/{document_id}/{file_uuid}.{ext}` using cryptographically random UUIDv4 identifiers, preventing path traversal attacks.
- **MIME Sniffing & Payload Validation:** File validation inspects initial byte signatures using `python-magic` to block executables or disguised scripts (e.g. `.exe` renamed to `.pdf`), and enforces a strict 25 MB ceiling before writing to disk.
- **Global Error Sanitization:** The global exception handler in `app/main.py` catches all unhandled exceptions, logging tracebacks internally while returning a uniform, sanitized HTTP 500 JSON response (`{"detail": "An internal server error occurred. Please contact support or try again later."}`), preventing leakage of filesystem paths, database connection strings, or system sockets.
- **Zero Secrets in Logs:** Secrets (`SECRET_KEY`, `POSTGRES_PASSWORD`, API keys) are injected exclusively via environment variables and are never emitted in stdout/stderr logs.

---

## 4. Known Trade-Offs & Architectural Limitations

1. **Regex-Hint-then-LLM Segmentation:**
   - *Design Choice:* Line-by-line regex patterns (`1.`, `Q1`, `(1)`) are used to generate candidate question splits, which are then carried across page boundaries and structured by the AI provider.
   - *Trade-off:* For non-standard question headers (e.g., questions beginning with plain prose without numbers or letter markers), segmentation relies on unnumbered fallback logic. A full visual layout parser (e.g., LayoutLMv3) could detect boundaries purely from spatial bounding boxes, but would significantly increase compute footprint and dependency complexity.
2. **Pluggable AI Provider (`MockAIProvider` vs. `OpenAIProvider`):**
   - *Design Choice:* A dual-provider abstraction allows the service to operate completely offline using `MockAIProvider` (deterministic rule-based parser) while supporting `OpenAIProvider` (strict JSON schema prompt) when `OPENAI_API_KEY` is provided.
   - *Trade-off:* The local test environment runs with `MockAIProvider` to ensure fast, deterministic CI/CD and offline execution without paid external API quotas. For production environments, setting `AI_PROVIDER="openai"` routes extraction through GPT-4o-mini for complex multi-lingual or nuanced question formulations.
3. **Traceability Granularity (Page-Level vs. Bounding-Box):**
   - *Design Choice:* Source traceability tracks page numbers (`source_pages: [1, 2]`) per question.
   - *Trade-off:* Bounding-box coordinate extraction (pixel coordinates $[x_0, y_0, x_1, y_1]$) is an explicit stretch goal per PRD §16. Page-level attribution meets the core requirement while maintaining lightweight JSON schemas and predictable payload sizes.
4. **Local Volume Storage vs. Distributed Object Storage:**
   - *Design Choice:* Files are persisted to `/app/storage/uploads` mounted via Docker volume.
   - *Trade-off:* Perfectly suited for single-host and containerized take-home evaluation. For horizontal multi-node scaling across Kubernetes pods, the storage service interface is decoupled and can be swapped for S3/MinIO by replacing `app/services/storage.py`.

---

## 5. Implementation Status & Roadmap

| Build Step | Description | Status | Verification Evidence |
|---|---|---|---|
| **Step 1** | Repo scaffold, Docker Compose, Celery, /health degraded handling | **Completed** | Dynamic version 1.0.1, HTTP 503 on degraded Redis/Postgres |
| **Step 2** | Auth (Register/Login/JWT), User model, Alembic migrations | **Completed** | Bcrypt hashing, 24h JWT, duplicate user rejection (400) |
| **Step 3** | Document model, MIME validation, UUID storage, POST /documents | **Completed** | Blocked disguised .exe, 25MB limit, UUID path generation |
| **Step 4** | Celery worker task pipeline & async non-blocking execution | **Completed** | Non-blocking HTTP 201 response, background completion |
| **Step 5** | Stage 2 text extraction (PyMuPDF native + Tesseract OCR fallback) | **Completed** | Fast path (0.106s), OCR fallback (2.14s), failure isolation on corrupted page |
| **Step 6** | Stage 3 & 4 layout segmentation, multi-page question spanning, Question entity | **Completed** | Q4 spanning pages [1, 2], schema retry loop, degraded input propagation |
| **Step 7** | Stage 5 & 6 answer-key association, DocumentGroup linked keys & confidence | **Completed** | Number match (0.95), content match (0.70), Q4 non-fabrication (null/0.0) |
| **Step 8** | Remaining read endpoints & pagination | **Completed** | GET /documents pagination, GET /questions/{id}, GET /document-groups |
| **Step 9** | DocumentGroup multi-document support & re-processing | **Completed** | Cross-document key resolution via linked group |
| **Step 10** | Security hardening & secret audit | **Completed** | Reusable ownership deps, sanitized 500 error, zero secrets in logs |
| **Step 11** | Automated Test Suite (pytest) | **Completed** | 21/21 tests passing in 12.43s (unit, API integration, security) |
| **Step 12** | Deliverables Package | **Completed** | Postman collection, sample inputs/outputs, SETUP.md, ARCHITECTURE.md |




