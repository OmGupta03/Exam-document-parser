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

---

## 3. Storage & Data Protection Design

- **Path Sanitization:** User-uploaded filenames are stored in the database for display purposes only. File paths on disk are constructed solely using cryptographically random UUIDv4 identifiers.
- **MIME Sniffing:** Uploaded files undergo MIME type verification via `python-magic` (inspecting byte headers) to prevent disguised executable uploads.
- **Size Bounds:** Enforced at the streaming layer up to a strict 25 MB ceiling.

---

## 4. Current Status & Next Steps

| Build Step | Description | Status |
|---|---|---|
| **Step 1** | Repo scaffold, Docker Compose, Celery, /health with 503 degraded handling | **Completed** |
| **Step 2** | Auth (Register/Login/JWT), User model, Alembic initial migration | **Completed** |
| **Step 3** | Document model, file validation, storage service, POST /documents | Up Next |
| **Step 4** | Celery worker task pipeline & async verification | Queued |

