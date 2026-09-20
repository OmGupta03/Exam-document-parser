import time
import requests

BASE_URL = "http://localhost:8000/api/v1"

# Login
login_res = requests.post(
    f"{BASE_URL}/auth/login/json",
    json={"email": "engineer@example.com", "password": "SuperSecret123!"}
)
assert login_res.status_code == 200, f"Login failed: {login_res.text}"
token = login_res.json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}

print("=== UPLOADING MULTIPAGE EXAM FOR STEP 6 ===")
with open("/app/tests/fixtures/multipage_exam.pdf", "rb") as f:
    up = requests.post(
        f"{BASE_URL}/documents",
        headers=headers,
        files={"file": ("multipage_exam.pdf", f, "application/pdf")}
    )
assert up.status_code == 201, f"Upload failed: {up.text}"
doc_id = up.json()["id"]
print(f"Uploaded multipage_exam.pdf -> document_id: {doc_id}")

# Wait for processing
for _ in range(30):
    st = requests.get(f"{BASE_URL}/documents/{doc_id}/status", headers=headers).json()
    if st["status"] in ["COMPLETED", "COMPLETED_WITH_WARNINGS", "FAILED"]:
        break
    time.sleep(0.3)

print(f"Document Status: {st['status']} | Total Pages: {st['total_pages']}")
assert st["status"] == "COMPLETED"

# Query questions
q_res = requests.get(f"{BASE_URL}/documents/{doc_id}/questions", headers=headers)
assert q_res.status_code == 200
questions = q_res.json()

print(f"\nExtracted {len(questions)} structured question(s):")
for q in questions:
    print(f"\n[Question {q['question_number']}]")
    print(f"  Type:         {q['question_type']}")
    print(f"  Source Pages: {q['source_pages']}")
    print(f"  Confidence:   {q['confidence']}")
    print(f"  Status:       {q['status']}")
    print(f"  Text:         {q['question_text'][:120]}...")
    if q["options"]:
        print(f"  Options ({len(q['options'])}): {[o['label'] + ': ' + o['text'][:25] for o in q['options']]}")

# Verify assertions
assert len(questions) >= 5, f"Expected at least 5 questions, got {len(questions)}"
# Questions 1, 2, 3 should be on page 1
assert questions[0]["source_pages"] == [1]
assert questions[1]["source_pages"] == [1]
assert questions[2]["source_pages"] == [1]

# Question 4 must span pages 1 and 2
q4 = next((q for q in questions if q["question_number"] == "4"), None)
assert q4 is not None, "Question 4 not found"
assert q4["source_pages"] == [1, 2], f"Expected source_pages [1, 2] for question 4, got {q4['source_pages']}"
assert len(q4["options"]) == 4, f"Expected 4 options for question 4, got {len(q4['options'])}"

print("\nAll Step 6 assertions (segmentation + multi-page context carrying) PASSED successfully!")
print(f"DOCUMENT_ID={doc_id}")
