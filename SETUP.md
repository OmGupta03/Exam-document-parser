# System Setup & Deployment Guide

This guide details how to build, configure, deploy, migrate, and verify the **Document Intelligence & Question Extraction Backend Service**.

---

## 1. Prerequisites

- **Docker & Docker Compose**: Docker 24.0+ and Docker Compose v2.20+
- **Host OS**: Linux, macOS, or Windows (WSL2 / PowerShell)
- **Ports Required**:
  - `8000`: FastAPI REST API
  - `5432`: PostgreSQL 16
  - `6379`: Redis 7

---

## 2. Quickstart (Docker Compose)

### Step 1: Clone & Configure Environment
Clone the repository and copy the environment template:
```bash
cp .env.example .env
```

### Step 2: Build & Launch Stack
Launch all services in detached mode:
```bash
docker-compose up -d --build
```
This builds and starts 4 containerized services:
1. `pbnc_postgres`: PostgreSQL 16 database with health check.
2. `pbnc_redis`: Redis 7 broker and result cache with health check.
3. `pbnc_api`: FastAPI application server running Uvicorn.
4. `pbnc_worker`: Celery distributed worker running text extraction, layout segmentation, and answer association pipelines.

### Step 3: Verify Stack Health
Check service health and container status:
```bash
docker-compose ps
curl -s http://localhost:8000/health
```
**Expected Response:**
```json
{
  "status": "healthy",
  "database": "connected",
  "redis": "connected",
  "version": "1.0.1"
}
```

---

## 3. Environment Variables Reference (`.env`)

| Variable | Default Value | Description |
| :--- | :--- | :--- |
| `PROJECT_NAME` | `Document Intelligence & Question Extraction Service` | Name displayed in OpenAPI documentation |
| `API_V1_STR` | `/api/v1` | URL prefix for v1 API routes |
| `ENVIRONMENT` | `development` | Environment mode (`development`, `testing`, `production`) |
| `DEBUG` | `true` | Debug flag |
| `SECRET_KEY` | `(32+ char secret string)` | Cryptographic key for JWT token signing |
| `ALGORITHM` | `HS256` | JWT signing algorithm |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `1440` | Access token lifespan (24 hours) |
| `POSTGRES_SERVER` | `db` | Database hostname inside Docker network |
| `POSTGRES_PORT` | `5432` | PostgreSQL port |
| `POSTGRES_USER` | `postgres` | Database superuser |
| `POSTGRES_PASSWORD` | `postgres_password` | Database password |
| `POSTGRES_DB` | `document_intelligence` | PostgreSQL database name |
| `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres_password@db:5432/document_intelligence` | Async SQLAlchemy database URL |
| `SYNC_DATABASE_URL` | `postgresql+psycopg2://postgres:postgres_password@db:5432/document_intelligence` | Sync database URL for Alembic |
| `REDIS_HOST` | `redis` | Redis container hostname |
| `REDIS_PORT` | `6379` | Redis port |
| `CELERY_BROKER_URL` | `redis://redis:6379/0` | Celery message queue connection string |
| `CELERY_RESULT_BACKEND` | `redis://redis:6379/1` | Celery result store connection string |
| `STORAGE_DIR` | `/app/storage/uploads` | Internal filesystem upload directory |
| `MAX_FILE_SIZE_BYTES` | `26214400` | Maximum upload size in bytes (25 MB) |
| `OCR_ENGINE` | `tesseract` | Optical Character Recognition engine |
| `TESSERACT_CMD` | `/usr/bin/tesseract` | Absolute path to Tesseract binary |
| `AI_PROVIDER` | `mock` | AI extraction provider (`mock`, `openai`, `gemini`) |
| `OPENAI_API_KEY` | `""` | OpenAI API key (optional, for live LLM mode) |
| `GEMINI_API_KEY` | `""` | Google Gemini API key (optional) |
| `LLM_MODEL` | `gpt-4o-mini` | LLM model identifier |

---

## 4. Running Database Migrations

Alembic migrations run automatically on container startup. To inspect migration history or run migrations manually:

```bash
# Check current migration revision
docker-compose exec api alembic current

# Run all pending migrations to head
docker-compose exec api alembic upgrade head

# View migration history
docker-compose exec api alembic history --verbose
```

---

## 5. Seed Test User & Obtain JWT Token

### 1. Register a Test User
```bash
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "engineer@example.com",
    "password": "SuperSecret123!"
  }'
```
**Response (HTTP 201 Created):**
```json
{
  "email": "engineer@example.com",
  "id": "ddf173b2-4400-4903-a594-94662e216e31",
  "created_at": "2026-09-19T18:24:10.123456Z"
}
```

### 2. Login and Acquire Access Token
```bash
curl -X POST http://localhost:8000/api/v1/auth/login/json \
  -H "Content-Type: application/json" \
  -d '{
    "email": "engineer@example.com",
    "password": "SuperSecret123!"
  }'
```
**Response (HTTP 200 OK):**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

---

## 6. Running the Automated Test Suite

Run the full automated test suite (all 21 unit, integration, and security tests) inside the running Docker container:

```bash
docker-compose exec api pytest -v tests/test_unit.py tests/test_api.py tests/test_openai_provider.py
```

---

## 7. Interactive OpenAPI Documentation

Once started, interactive API documentation is accessible via:
- **Swagger UI**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc UI**: [http://localhost:8000/redoc](http://localhost:8000/redoc)
- **OpenAPI JSON**: [http://localhost:8000/api/v1/openapi.json](http://localhost:8000/api/v1/openapi.json)
