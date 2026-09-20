import time
import requests

BASE_URL = "http://localhost:8000/api/v1"

# 1. Login as engineer
login_res = requests.post(
    f"{BASE_URL}/auth/login/json",
    json={"email": "engineer@example.com", "password": "SuperSecret123!"}
)
assert login_res.status_code == 200, f"Login failed: {login_res.text}"
token = login_res.json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}

print("=== FAILURE ISOLATION TEST (PRD §12) ===")
with open("/app/tests/fixtures/corrupted_middle_page.pdf", "rb") as f:
    up_res = requests.post(
        f"{BASE_URL}/documents",
        headers=headers,
        files={"file": ("corrupted_middle_page.pdf", f, "application/pdf")}
    )
assert up_res.status_code == 201, f"Upload failed: {up_res.text}"
doc_id = up_res.json()["id"]
print(f"Uploaded corrupted_middle_page.pdf -> document_id: {doc_id}")

# 2. Poll until complete
st = None
for _ in range(30):
    status_res = requests.get(f"{BASE_URL}/documents/{doc_id}/status", headers=headers)
    st = status_res.json()
    if st["status"] in ["COMPLETED", "COMPLETED_WITH_WARNINGS", "FAILED"]:
        break
    time.sleep(0.3)

print(f"Document Final Status: {st['status']}")
print(f"Current Stage:         {st['current_stage']}")
print(f"Total Pages:           {st['total_pages']}")
print(f"Pages Processed:       {st['pages_processed']}")
print(f"Error Message:         {st['error_message']}\n")

# 3. Fetch pages
pages_res = requests.get(f"{BASE_URL}/documents/{doc_id}/pages", headers=headers)
pages = pages_res.json()
print(f"Extracted {len(pages)} pages from database:")
for p in pages:
    print(f"  Page {p['page_number']}: method={p['extraction_method']}, conf={p['confidence']}, chars={len(p['raw_text'])}")

assert st["status"] == "COMPLETED_WITH_WARNINGS", f"Expected COMPLETED_WITH_WARNINGS, got {st['status']}"
assert pages[0]["extraction_method"] == "native_text"
assert pages[1]["extraction_method"] == "failed"
assert pages[2]["extraction_method"] == "native_text"
print("\nFailure isolation test PASSED successfully!")
