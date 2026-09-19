import time
from datetime import datetime, timezone
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

print("=== STEP 4 ASYNC PLUMBING VERIFICATION ===")

# 2. Upload document
t_upload_start = datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3]
print(f"[{t_upload_start}] Client sends POST /api/v1/documents...")

with open("/app/tests/fixtures/sample_exam.pdf", "rb") as f:
    upload_res = requests.post(
        f"{BASE_URL}/documents",
        headers=headers,
        files={"file": ("sample_exam.pdf", f, "application/pdf")}
    )

t_upload_end = datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3]
assert upload_res.status_code == 201, f"Upload failed: {upload_res.text}"
doc_data = upload_res.json()
doc_id = doc_data["id"]

print(f"[{t_upload_end}] Client received HTTP 201 Created immediately (non-blocking)!")
print(f"Returned Payload: {doc_data}")
print(f"Initial Status in Response: {doc_data['status']}\n")

# 3. Immediate poll (< 50ms)
t_poll1 = datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3]
poll1_res = requests.get(f"{BASE_URL}/documents/{doc_id}/status", headers=headers)
print(f"[{t_poll1}] Immediate poll (GET /documents/{doc_id}/status):")
print(f"Status Code: {poll1_res.status_code}")
print(f"Body: {poll1_res.json()}\n")

# 4. Wait for worker processing to finish
print("Client sleeps 2.5 seconds while Celery worker executes in background...")
time.sleep(2.5)

# 5. Follow-up poll
t_poll2 = datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3]
poll2_res = requests.get(f"{BASE_URL}/documents/{doc_id}/status", headers=headers)
print(f"[{t_poll2}] Follow-up poll (GET /documents/{doc_id}/status):")
print(f"Status Code: {poll2_res.status_code}")
print(f"Body: {poll2_res.json()}\n")
