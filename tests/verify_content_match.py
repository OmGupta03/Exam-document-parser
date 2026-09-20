import time
import requests
import json

BASE_URL = "http://localhost:8000/api/v1"

# Login
login_res = requests.post(
    f"{BASE_URL}/auth/login/json",
    json={"email": "engineer@example.com", "password": "SuperSecret123!"}
)
assert login_res.status_code == 200, f"Login failed: {login_res.text}"
token = login_res.json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}

print("=== VERIFYING TIER 2: CONTENT_MATCH FALLBACK ===")

# 1. Upload answer key with content mapping (Relational Queries: SQL Language)
with open("/app/tests/fixtures/unnumbered_answer_key.pdf", "rb") as f:
    up_ak = requests.post(
        f"{BASE_URL}/documents",
        headers=headers,
        files={"file": ("unnumbered_answer_key.pdf", f, "application/pdf")}
    )
assert up_ak.status_code == 201
ak_id = up_ak.json()["id"]

# Wait for answer key doc
for _ in range(30):
    st = requests.get(f"{BASE_URL}/documents/{ak_id}/status", headers=headers).json()
    if st["status"] in ["COMPLETED", "COMPLETED_WITH_WARNINGS", "FAILED"]:
        break
    time.sleep(0.3)

# 2. Upload unnumbered question document
with open("/app/tests/fixtures/unnumbered_exam.pdf", "rb") as f:
    up_qp = requests.post(
        f"{BASE_URL}/documents",
        headers=headers,
        files={"file": ("unnumbered_exam.pdf", f, "application/pdf")}
    )
assert up_qp.status_code == 201
qp_id = up_qp.json()["id"]

# 3. Create DocumentGroup linking both
group_res = requests.post(
    f"{BASE_URL}/document-groups",
    headers=headers,
    json={"name": "Unnumbered Quiz & Solutions", "document_ids": [qp_id, ak_id]}
)
assert group_res.status_code == 201

# Wait for question document to complete re-processing with linked group
time.sleep(0.5)
for _ in range(30):
    st = requests.get(f"{BASE_URL}/documents/{qp_id}/status", headers=headers).json()
    q_check = requests.get(f"{BASE_URL}/documents/{qp_id}/questions", headers=headers).json()
    if st["status"] in ["COMPLETED", "COMPLETED_WITH_WARNINGS"] and q_check and q_check[0]["answer"]["match_method"] == "content_match":
        break
    time.sleep(0.4)

print(f"Document Status: {st['status']}")

# 4. Fetch questions and print verbatim HTTP response
q_res = requests.get(f"{BASE_URL}/documents/{qp_id}/questions", headers=headers)
assert q_res.status_code == 200
questions = q_res.json()

print(f"HTTP/1.1 {q_res.status_code} OK")
for k, v in q_res.headers.items():
    print(f"{k}: {v}")
print()
print(json.dumps(questions, indent=2))

# Assertions
assert len(questions) >= 1
q = questions[0]
assert q["question_number"] is None, f"Expected None question_number, got {q['question_number']}"
assert q["answer"]["value"] == "A", f"Expected normalized option label 'A', got {q['answer']['value']}"
assert q["answer"]["match_method"] == "content_match", f"Expected content_match, got {q['answer']['match_method']}"
assert q["answer"]["confidence"] == 0.70, f"Expected 0.70 confidence, got {q['answer']['confidence']}"
print("\n[VERIFIED] Content match successfully normalized and matched unnumbered question to label 'A' with confidence 0.70!")
