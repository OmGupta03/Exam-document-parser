import requests
import json
import os

BASE_URL = "http://localhost:8000/api/v1"
login_res = requests.post(f"{BASE_URL}/auth/login/json", json={"email": "engineer@example.com", "password": "SuperSecret123!"})
token = login_res.json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}

docs = requests.get(f"{BASE_URL}/documents?limit=50", headers=headers).json()["items"]
saved = set()

os.makedirs("samples/outputs", exist_ok=True)

for doc in docs:
    doc_id = doc["id"]
    fn = doc["original_filename"]
    q_resp = requests.get(f"{BASE_URL}/documents/{doc_id}/questions", headers=headers).json()
    if not q_resp:
        continue

    if "question_paper_only" in fn and "linked" not in saved:
        with open("samples/outputs/linked_group_exam_with_answers.json", "w") as out_f:
            json.dump(q_resp, out_f, indent=2)
        saved.add("linked")
        print("Saved samples/outputs/linked_group_exam_with_answers.json")
    elif "unnumbered_exam" in fn and "unnumbered" not in saved:
        with open("samples/outputs/unnumbered_exam_content_match.json", "w") as out_f:
            json.dump(q_resp, out_f, indent=2)
        saved.add("unnumbered")
        print("Saved samples/outputs/unnumbered_exam_content_match.json")
    elif "scanned" in fn and "scanned" not in saved:
        with open("samples/outputs/scanned_physics_quiz_questions.json", "w") as out_f:
            json.dump(q_resp, out_f, indent=2)
        saved.add("scanned")
        print("Saved samples/outputs/scanned_physics_quiz_questions.json")
    elif "multipage" in fn and "multipage" not in saved:
        with open("samples/outputs/digital_exam_multipage_questions.json", "w") as out_f:
            json.dump(q_resp, out_f, indent=2)
        saved.add("multipage")
        print("Saved samples/outputs/digital_exam_multipage_questions.json")

print("Finished exporting sample outputs.")
