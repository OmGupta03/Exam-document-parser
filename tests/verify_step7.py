import time
import requests
import json

BASE_URL = "http://localhost:8000/api/v1"

# 1. Login
login_res = requests.post(
    f"{BASE_URL}/auth/login/json",
    json={"email": "engineer@example.com", "password": "SuperSecret123!"}
)
assert login_res.status_code == 200, f"Login failed: {login_res.text}"
token = login_res.json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}

print("=== STEP 7 VERIFICATION: ANSWER-KEY ASSOCIATION & LINKED DOCUMENTS ===")

# 2. Upload standalone answer key first
with open("/app/tests/fixtures/answer_key_standalone.pdf", "rb") as f:
    up_ak = requests.post(
        f"{BASE_URL}/documents",
        headers=headers,
        files={"file": ("answer_key_standalone.pdf", f, "application/pdf")}
    )
assert up_ak.status_code == 201, f"Upload answer key failed: {up_ak.text}"
ak_id = up_ak.json()["id"]
print(f"Uploaded answer_key_standalone.pdf -> document_id: {ak_id}")

# Wait for answer key doc to process
for _ in range(30):
    st = requests.get(f"{BASE_URL}/documents/{ak_id}/status", headers=headers).json()
    if st["status"] in ["COMPLETED", "COMPLETED_WITH_WARNINGS", "FAILED"]:
        break
    time.sleep(0.3)
print(f"Answer Key Doc Status: {st['status']}")

# 3. Upload question paper only
with open("/app/tests/fixtures/question_paper_only.pdf", "rb") as f:
    up_qp = requests.post(
        f"{BASE_URL}/documents",
        headers=headers,
        files={"file": ("question_paper_only.pdf", f, "application/pdf")}
    )
assert up_qp.status_code == 201, f"Upload question paper failed: {up_qp.text}"
qp_id = up_qp.json()["id"]
print(f"Uploaded question_paper_only.pdf  -> document_id: {qp_id}")

# 4. Create DocumentGroup linking Question Paper + Answer Key (PRD §6 requirement)
group_payload = {
    "name": "Midterm Exam 2026 - Paper & Solutions",
    "document_ids": [qp_id, ak_id]
}
group_res = requests.post(f"{BASE_URL}/document-groups", headers=headers, json=group_payload)
assert group_res.status_code == 201, f"Create group failed: {group_res.text}"
group_data = group_res.json()
group_id = group_data["id"]
print(f"Created DocumentGroup -> id: {group_id}, linked {len(group_data['documents'])} documents")

# 5. Wait for question paper to complete processing with linked answer key
for _ in range(30):
    st = requests.get(f"{BASE_URL}/documents/{qp_id}/status", headers=headers).json()
    if st["status"] in ["COMPLETED", "COMPLETED_WITH_WARNINGS", "FAILED"]:
        break
    time.sleep(0.3)

print(f"Question Paper Final Status: {st['status']} (Stage: {st['current_stage']})")

# 6. Verify GET /documents/{id}/questions
q_res = requests.get(f"{BASE_URL}/documents/{qp_id}/questions", headers=headers)
assert q_res.status_code == 200
questions = q_res.json()
print(f"\nExtracted {len(questions)} question(s) with answer associations:")

for q in questions:
    ans = q["answer"]
    print(f"\n[Question {q['question_number']}]")
    print(f"  Prompt:     {q['question_text'][:80]}...")
    print(f"  Confidence: {q['confidence']} | Status: {q['status']}")
    print(f"  Answer:     value='{ans['value']}', conf={ans['confidence']}, match_method='{ans['match_method']}'")

# Assertions
assert len(questions) == 4, f"Expected 4 questions, got {len(questions)}"

# Q1: 1 -> B
q1 = next(q for q in questions if q["question_number"] == "1")
assert q1["answer"]["value"] == "B"
assert q1["answer"]["match_method"] == "number_match"
assert q1["answer"]["confidence"] == 0.95

# Q2: 2 -> C
q2 = next(q for q in questions if q["question_number"] == "2")
assert q2["answer"]["value"] == "C"
assert q2["answer"]["match_method"] == "number_match"

# Q3: 3 -> A
q3 = next(q for q in questions if q["question_number"] == "3")
assert q3["answer"]["value"] == "A"
assert q3["answer"]["match_method"] == "number_match"

# Q4: omitted from answer key -> MUST be unmatched with null value (Strict Non-Fabrication!)
q4 = next(q for q in questions if q["question_number"] == "4")
assert q4["answer"]["value"] is None, f"Expected None for Q4 answer, got {q4['answer']['value']}"
assert q4["answer"]["confidence"] == 0.0
assert q4["answer"]["match_method"] == "unmatched"
print("\n[VERIFIED] Question 4 was omitted from key and correctly persisted as unmatched with value=None (Non-fabrication proven!)")

# 7. Verify GET /questions/{id}/answer
q1_id = q1["id"]
ans_res = requests.get(f"{BASE_URL}/questions/{q1_id}/answer", headers=headers)
assert ans_res.status_code == 200
ans_body = ans_res.json()
assert ans_body["question_id"] == q1_id
assert ans_body["answer_text"] == "B"
assert ans_body["source_document_id"] == ak_id
print(f"[VERIFIED] GET /questions/{q1_id}/answer returned linked source doc {ans_body['source_document_id']}")

# 8. Verify GET /documents/{id}/warnings
warn_res = requests.get(f"{BASE_URL}/documents/{qp_id}/warnings", headers=headers)
assert warn_res.status_code == 200
warnings = warn_res.json()
print(f"\n[VERIFIED] GET /documents/{qp_id}/warnings returned {len(warnings)} warning(s):")
for w in warnings:
    print(f"  - [{w['severity'].upper()}] {w['warning_type']}: {w['message']}")

assert any(w["warning_type"] == "answer_unmatched" for w in warnings), "Expected answer_unmatched warning for Q4"

# 9. Verify GET /document-groups/{group_id}
grp_get = requests.get(f"{BASE_URL}/document-groups/{group_id}", headers=headers)
assert grp_get.status_code == 200
grp_details = grp_get.json()
assert grp_details["id"] == group_id
assert len(grp_details["documents"]) == 2
print(f"[VERIFIED] GET /document-groups/{group_id} confirmed {len(grp_details['documents'])} linked documents")

print("\nALL STEP 7 VERIFICATIONS PASSED SUCCESSFULLY!")
print(f"QP_DOC_ID={qp_id}")
print(f"AK_DOC_ID={ak_id}")
print(f"Q1_ID={q1_id}")
print(f"GROUP_ID={group_id}")
