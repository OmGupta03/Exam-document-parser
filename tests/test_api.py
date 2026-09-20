import io
import uuid
import pytest
import pytest_asyncio
import httpx
from unittest.mock import patch, MagicMock

from app.main import app


@pytest_asyncio.fixture
async def async_client():
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ==============================================================================
# 1. HEALTH & ROOT ENDPOINT TESTS
# ==============================================================================

@pytest.mark.asyncio
async def test_health_check_endpoints(async_client):
    res1 = await async_client.get("/health")
    assert res1.status_code == 200
    assert res1.json()["status"] == "healthy"
    assert res1.json()["version"] == "1.0.1"

    res2 = await async_client.get("/api/v1/health")
    assert res2.status_code == 200
    assert res2.json() == res1.json()


# ==============================================================================
# 2. AUTHENTICATION & USER MANAGEMENT (PRD §13)
# ==============================================================================

@pytest.mark.asyncio
async def test_auth_registration_and_login_flow(async_client):
    email = f"test_user_{uuid.uuid4().hex[:8]}@example.com"
    password = "SuperSecretPassword123!"

    # 1. Register user
    reg_res = await async_client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password}
    )
    assert reg_res.status_code == 201
    user_data = reg_res.json()
    assert user_data["email"] == email
    assert "id" in user_data

    # 2. Duplicate registration should return 400
    dup_res = await async_client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password}
    )
    assert dup_res.status_code == 400
    assert "already exists" in dup_res.json()["detail"]

    # 3. Login with wrong password returns 401
    bad_login = await async_client.post(
        "/api/v1/auth/login/json",
        json={"email": email, "password": "WrongPassword!"}
    )
    assert bad_login.status_code == 401

    # 4. Login with correct password returns JWT token
    login_res = await async_client.post(
        "/api/v1/auth/login/json",
        json={"email": email, "password": password}
    )
    assert login_res.status_code == 200
    assert "access_token" in login_res.json()
    assert login_res.json()["token_type"] == "bearer"


# ==============================================================================
# 3. MALFORMED / INVALID FILE REJECTION TESTS (PRD §13 Explicit Requirement)
# ==============================================================================

@pytest.mark.asyncio
async def test_malformed_and_disguised_file_rejection(async_client):
    email = f"file_test_{uuid.uuid4().hex[:8]}@example.com"
    password = "SuperSecretPassword123!"
    await async_client.post("/api/v1/auth/register", json={"email": email, "password": password})
    login_data = (await async_client.post("/api/v1/auth/login/json", json={"email": email, "password": password})).json()
    token = login_data["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Test A: Executable disguised as PDF (MIME sniffing check)
    fake_exe_bytes = b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff\x00\x00This is a Windows executable!"
    res_exe = await async_client.post(
        "/api/v1/documents",
        headers=headers,
        files={"file": ("malware.pdf", fake_exe_bytes, "application/pdf")}
    )
    assert res_exe.status_code == 400
    assert "Unsupported file type" in res_exe.json()["detail"]

    # Test B: Plain text file disguised as PDF
    plain_txt = b"Hello world, I am just a plain text file, not a valid PDF or PNG."
    res_txt = await async_client.post(
        "/api/v1/documents",
        headers=headers,
        files={"file": ("notes.pdf", plain_txt, "application/pdf")}
    )
    assert res_txt.status_code == 400
    assert "Unsupported file type" in res_txt.json()["detail"]


# ==============================================================================
# 4. FULL PIPELINE & READ ENDPOINTS INTEGRATION FLOW (PRD §13)
# ==============================================================================

@pytest.mark.asyncio
@patch("app.workers.tasks.process_document.delay")
async def test_full_document_pipeline_flow(mock_celery_delay, async_client):
    # Mock celery task dispatch so integration test does not wait on async workers
    mock_celery_delay.return_value = None

    email = f"pipeline_{uuid.uuid4().hex[:8]}@example.com"
    password = "SuperSecretPassword123!"
    await async_client.post("/api/v1/auth/register", json={"email": email, "password": password})
    login_data = (await async_client.post("/api/v1/auth/login/json", json={"email": email, "password": password})).json()
    token = login_data["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Upload valid document
    with open("tests/fixtures/digital_exam.pdf", "rb") as f:
        pdf_bytes = f.read()

    up_res = await async_client.post(
        "/api/v1/documents",
        headers=headers,
        files={"file": ("digital_exam.pdf", pdf_bytes, "application/pdf")}
    )
    assert up_res.status_code == 201
    doc_id = up_res.json()["id"]
    assert doc_id is not None
    assert mock_celery_delay.called

    # 2. Retrieve document metadata
    meta_res = await async_client.get(f"/api/v1/documents/{doc_id}", headers=headers)
    assert meta_res.status_code == 200
    assert meta_res.json()["id"] == doc_id
    assert meta_res.json()["original_filename"] == "digital_exam.pdf"

    # 3. Poll document status
    st_res = await async_client.get(f"/api/v1/documents/{doc_id}/status", headers=headers)
    assert st_res.status_code == 200
    assert "status" in st_res.json()
    assert "current_stage" in st_res.json()

    # 4. List documents with pagination
    list_res = await async_client.get("/api/v1/documents?skip=0&limit=10", headers=headers)
    assert list_res.status_code == 200
    data = list_res.json()
    assert "total" in data and "items" in data
    assert any(d["id"] == doc_id for d in data["items"])

    # 5. Retrieve pages
    pages_res = await async_client.get(f"/api/v1/documents/{doc_id}/pages", headers=headers)
    assert pages_res.status_code == 200
    assert isinstance(pages_res.json(), list)

    # 6. Retrieve questions
    q_res = await async_client.get(f"/api/v1/documents/{doc_id}/questions", headers=headers)
    assert q_res.status_code == 200
    assert isinstance(q_res.json(), list)

    # 7. Retrieve warnings
    warn_res = await async_client.get(f"/api/v1/documents/{doc_id}/warnings", headers=headers)
    assert warn_res.status_code == 200
    assert isinstance(warn_res.json(), list)


# ==============================================================================
# 5. DOCUMENT GROUPS & CROSS-USER OWNERSHIP SCOPING (PRD §11 & §13)
# ==============================================================================

@pytest.mark.asyncio
@patch("app.workers.tasks.process_document.delay")
async def test_ownership_scoping_and_cross_user_isolation(mock_celery_delay, async_client):
    mock_celery_delay.return_value = None

    # User 1 setup
    user1_email = f"owner_{uuid.uuid4().hex[:8]}@example.com"
    pwd = "SuperSecretPassword123!"
    await async_client.post("/api/v1/auth/register", json={"email": user1_email, "password": pwd})
    token1 = (await async_client.post("/api/v1/auth/login/json", json={"email": user1_email, "password": pwd})).json()["access_token"]
    headers1 = {"Authorization": f"Bearer {token1}"}

    # User 2 setup (Adversary)
    user2_email = f"adversary_{uuid.uuid4().hex[:8]}@example.com"
    await async_client.post("/api/v1/auth/register", json={"email": user2_email, "password": pwd})
    token2 = (await async_client.post("/api/v1/auth/login/json", json={"email": user2_email, "password": pwd})).json()["access_token"]
    headers2 = {"Authorization": f"Bearer {token2}"}

    # User 1 creates two documents and a document group
    with open("tests/fixtures/digital_exam.pdf", "rb") as f1:
        b1 = f1.read()
    up1 = await async_client.post("/api/v1/documents", headers=headers1, files={"file": ("doc1.pdf", b1, "application/pdf")})
    up2 = await async_client.post("/api/v1/documents", headers=headers1, files={"file": ("doc2.pdf", b1, "application/pdf")})
    doc1_id = up1.json()["id"]
    doc2_id = up2.json()["id"]

    grp_res = await async_client.post(
        "/api/v1/document-groups",
        headers=headers1,
        json={"name": "User 1 Exam Group", "document_ids": [doc1_id, doc2_id]}
    )
    assert grp_res.status_code == 201
    group_id = grp_res.json()["id"]

    # --- CROSS-USER SECURITY CHECKS (PRD §11) ---
    # User 2 attempting to access User 1's document -> 404
    sec_doc = await async_client.get(f"/api/v1/documents/{doc1_id}", headers=headers2)
    assert sec_doc.status_code == 404

    # User 2 attempting to access User 1's document pages -> 404
    sec_pages = await async_client.get(f"/api/v1/documents/{doc1_id}/pages", headers=headers2)
    assert sec_pages.status_code == 404

    # User 2 attempting to access User 1's document group -> 404
    sec_grp = await async_client.get(f"/api/v1/document-groups/{group_id}", headers=headers2)
    assert sec_grp.status_code == 404

    # User 2 listing document groups should return 0 groups
    sec_grp_list = (await async_client.get("/api/v1/document-groups", headers=headers2)).json()
    assert len(sec_grp_list) == 0


# ==============================================================================
# 6. GLOBAL 500 EXCEPTION SANITIZATION TEST (PRD §9)
# ==============================================================================

@pytest.mark.asyncio
async def test_global_exception_sanitization(async_client):
    """Verify unhandled server errors are strictly sanitized to generic 500 JSON without stack traces."""
    # Mount temporary route for testing exception handler
    @app.get("/api/v1/test-runtime-crash", include_in_schema=False)
    async def deliberate_crash():
        raise RuntimeError("FATAL SYSTEM ERROR: /var/lib/postgresql/data/connection_lost.sock")

    res = await async_client.get("/api/v1/test-runtime-crash")
    assert res.status_code == 500
    data = res.json()
    # Confirm exact sanitized message
    assert data["detail"] == "An internal server error occurred. Please contact support or try again later."
    # Confirm no stack trace or internal path leaked
    assert "FATAL" not in res.text
    assert "postgresql" not in res.text
    assert "connection_lost" not in res.text
