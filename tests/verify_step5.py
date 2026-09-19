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

def wait_for_completion(doc_id: str, timeout: float = 10.0):
    start = time.time()
    while time.time() - start < timeout:
        res = requests.get(f"{BASE_URL}/documents/{doc_id}/status", headers=headers)
        data = res.json()
        if data["status"] in ["COMPLETED", "COMPLETED_WITH_WARNINGS", "FAILED"]:
            return data
        time.sleep(0.3)
    raise TimeoutError(f"Document {doc_id} did not complete within {timeout}s")

print("=================================================================")
print("  STEP 5: STAGE 1 & 2 TEXT EXTRACTION PIPELINE VERIFICATION")
print("=================================================================\n")

# TEST 1: Digital PDF (Native Text Layer Fast Path)
print("--- TEST 1: Digital PDF (PyMuPDF Native Text Layer Fast Path) ---")
with open("/app/tests/fixtures/digital_exam.pdf", "rb") as f:
    up1 = requests.post(
        f"{BASE_URL}/documents",
        headers=headers,
        files={"file": ("digital_exam.pdf", f, "application/pdf")}
    )
assert up1.status_code == 201, f"Upload 1 failed: {up1.text}"
doc1_id = up1.json()["id"]
print(f"Uploaded digital_exam.pdf -> document_id: {doc1_id}")

status1 = wait_for_completion(doc1_id)
print(f"Processing Status: {status1['status']} | Total Pages: {status1['total_pages']}")

pages1_res = requests.get(f"{BASE_URL}/documents/{doc1_id}/pages", headers=headers)
assert pages1_res.status_code == 200
pages1 = pages1_res.json()

for p in pages1:
    print(f"\n[Page {p['page_number']}]")
    print(f"  Method:     {p['extraction_method']} (Expected: native_text)")
    print(f"  Confidence: {p['confidence']}")
    print(f"  Raw Text Snippet:\n{p['raw_text'].strip()[:200]}")
    assert p["extraction_method"] == "native_text", f"Expected native_text, got {p['extraction_method']}"


# TEST 2: Scanned / Raster Image (Tesseract OCR Fallback)
print("\n--- TEST 2: Scanned PNG Image (Tesseract OCR Fallback) ---")
with open("/app/tests/fixtures/scanned_physics_quiz.png", "rb") as f:
    up2 = requests.post(
        f"{BASE_URL}/documents",
        headers=headers,
        files={"file": ("scanned_physics_quiz.png", f, "image/png")}
    )
assert up2.status_code == 201, f"Upload 2 failed: {up2.text}"
doc2_id = up2.json()["id"]
print(f"Uploaded scanned_physics_quiz.png -> document_id: {doc2_id}")

status2 = wait_for_completion(doc2_id)
print(f"Processing Status: {status2['status']} | Total Pages: {status2['total_pages']}")

pages2_res = requests.get(f"{BASE_URL}/documents/{doc2_id}/pages", headers=headers)
assert pages2_res.status_code == 200
pages2 = pages2_res.json()

for p in pages2:
    print(f"\n[Page {p['page_number']}]")
    print(f"  Method:     {p['extraction_method']} (Expected: ocr_tesseract)")
    print(f"  Confidence: {p['confidence']}")
    print(f"  Raw Text Snippet:\n{p['raw_text'].strip()[:200]}")
    assert p["extraction_method"] == "ocr_tesseract", f"Expected ocr_tesseract, got {p['extraction_method']}"


# TEST 3: Scanned PDF with No Selectable Text Layer (Tesseract OCR Fallback on PDF)
print("\n--- TEST 3: Scanned PDF with No Text Layer (OCR Fallback on PDF) ---")
with open("/app/tests/fixtures/scanned_exam.pdf", "rb") as f:
    up3 = requests.post(
        f"{BASE_URL}/documents",
        headers=headers,
        files={"file": ("scanned_exam.pdf", f, "application/pdf")}
    )
assert up3.status_code == 201, f"Upload 3 failed: {up3.text}"
doc3_id = up3.json()["id"]
print(f"Uploaded scanned_exam.pdf -> document_id: {doc3_id}")

status3 = wait_for_completion(doc3_id)
print(f"Processing Status: {status3['status']} | Total Pages: {status3['total_pages']}")

pages3_res = requests.get(f"{BASE_URL}/documents/{doc3_id}/pages", headers=headers)
assert pages3_res.status_code == 200
pages3 = pages3_res.json()

for p in pages3:
    print(f"\n[Page {p['page_number']}]")
    print(f"  Method:     {p['extraction_method']} (Expected: ocr_tesseract)")
    print(f"  Confidence: {p['confidence']}")
    print(f"  Raw Text Snippet:\n{p['raw_text'].strip()[:200]}")
    assert p["extraction_method"] == "ocr_tesseract", f"Expected ocr_tesseract, got {p['extraction_method']}"

print("\nAll Stage 2 extraction assertions passed!")
