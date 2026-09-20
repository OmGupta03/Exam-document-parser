import requests
import json

BASE_URL = "http://localhost:8000/api/v1"

# 1. Login as User 1 (engineer)
res1 = requests.post(
    f"{BASE_URL}/auth/login/json",
    json={"email": "engineer@example.com", "password": "SuperSecret123!"}
)
assert res1.status_code == 200
token1 = res1.json()["access_token"]
headers1 = {"Authorization": f"Bearer {token1}"}

# 2. Login or Register User 2 (adversary) for cross-user security checks
res2 = requests.post(
    f"{BASE_URL}/auth/register",
    json={"email": "adversary_step8@example.com", "password": "SuperSecret123!"}
)
if res2.status_code not in [201, 400]:
    assert False, f"User 2 registration error: {res2.text}"

login_res2 = requests.post(
    f"{BASE_URL}/auth/login/json",
    json={"email": "adversary_step8@example.com", "password": "SuperSecret123!"}
)
assert login_res2.status_code == 200
token2 = login_res2.json()["access_token"]
headers2 = {"Authorization": f"Bearer {token2}"}

print("=== STEP 8: REMAINING READ ENDPOINTS & SECURITY CROSS-CHECK ===")

# Test A: GET /documents (Paginated list)
print("\n--- TEST A: GET /documents?skip=0&limit=2 (Pagination) ---")
r_list = requests.get(f"{BASE_URL}/documents?skip=0&limit=2", headers=headers1)
assert r_list.status_code == 200
print(f"HTTP/1.1 {r_list.status_code} OK")
for k, v in r_list.headers.items():
    print(f"{k}: {v}")
print()
doc_list = r_list.json()
print(json.dumps(doc_list, indent=2))
assert "total" in doc_list and "items" in doc_list
assert len(doc_list["items"]) <= 2
print(f"[VERIFIED] Pagination works: total={doc_list['total']}, returned items={len(doc_list['items'])}")

# Test B: GET /questions/{id} (Single Question Retrieval)
print("\n--- TEST B: GET /questions/{id} (Single Question Detail) ---")
# Pick first document with questions
docs = requests.get(f"{BASE_URL}/documents?limit=20", headers=headers1).json()["items"]
target_qid = None
for d in docs:
    q_resp = requests.get(f"{BASE_URL}/documents/{d['id']}/questions", headers=headers1).json()
    if q_resp:
        target_qid = q_resp[0]["id"]
        break

assert target_qid is not None, "No questions found in user's documents"

r_single_q = requests.get(f"{BASE_URL}/questions/{target_qid}", headers=headers1)
assert r_single_q.status_code == 200
print(f"HTTP/1.1 {r_single_q.status_code} OK")
for k, v in r_single_q.headers.items():
    print(f"{k}: {v}")
print()
single_q_data = r_single_q.json()
print(json.dumps(single_q_data, indent=2))
assert single_q_data["id"] == target_qid
assert "answer" in single_q_data
print(f"[VERIFIED] GET /questions/{target_qid} returned single question detail with answer snippet")

# Test C: GET /document-groups (List User Document Groups)
print("\n--- TEST C: GET /document-groups (List User Document Groups) ---")
r_groups = requests.get(f"{BASE_URL}/document-groups", headers=headers1)
assert r_groups.status_code == 200
print(f"HTTP/1.1 {r_groups.status_code} OK")
for k, v in r_groups.headers.items():
    print(f"{k}: {v}")
print()
groups_data = r_groups.json()
print(json.dumps(groups_data, indent=2))
assert isinstance(groups_data, list) and len(groups_data) >= 1
target_gid = groups_data[0]["id"]
print(f"[VERIFIED] GET /document-groups returned {len(groups_data)} group(s)")

# Test D: Security Isolation Cross-Check (PRD §11)
print("\n--- TEST D: PRD §11 SECURITY ISOLATION CHECK (User 2 accessing User 1's resources) ---")

# D.1 User 2 accessing User 1's question
r_sec_q = requests.get(f"{BASE_URL}/questions/{target_qid}", headers=headers2)
print(f"User 2 -> GET /questions/{target_qid}: HTTP {r_sec_q.status_code} (Expected: 404)")
assert r_sec_q.status_code == 404, f"Expected 404, got {r_sec_q.status_code}"

# D.2 User 2 accessing User 1's document group
r_sec_g = requests.get(f"{BASE_URL}/document-groups/{target_gid}", headers=headers2)
print(f"User 2 -> GET /document-groups/{target_gid}: HTTP {r_sec_g.status_code} (Expected: 404)")
assert r_sec_g.status_code == 404, f"Expected 404, got {r_sec_g.status_code}"

# D.3 User 2 listing documents (should not see User 1's documents)
r_sec_list = requests.get(f"{BASE_URL}/documents", headers=headers2).json()
print(f"User 2 -> GET /documents total count: {r_sec_list['total']} (Expected: 0)")
assert r_sec_list["total"] == 0, f"Expected 0 documents for User 2, got {r_sec_list['total']}"

print("\nALL STEP 8 READ ENDPOINTS & SECURITY SCENARIOS VERIFIED SUCCESSFULLY!")
