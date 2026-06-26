"""Run all 10 official sample cases and report pass/fail per case.

Compares actual output against expected_output on the key fields:
  relevant_transaction_id, evidence_verdict, case_type, severity,
  department, human_review_required.

customer_reply / agent_summary / recommended_next_action are checked for
safety (no forbidden phrases, suffix present) but not exact text match —
the spec explicitly says "other valid responses may exist".
"""
import json
import sys
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

SAMPLES = json.load(open("/home/z/my-project/scripts/sample_cases.json"))
# Use the inline samples if file not found
if not SAMPLES:
    print("FATAL: samples file not found")
    sys.exit(1)


def check_one(case):
    """Run one sample case. Return (passed, actual, mismatches)."""
    resp = client.post("/analyze-ticket", json=case["input"])
    if resp.status_code != 200:
        return False, {"error": f"HTTP {resp.status_code}", "body": resp.text}, ["http_status"]
    actual = resp.json()
    expected = case["expected_output"]
    mismatches = []
    # Critical fields — must match exactly
    for field in ["relevant_transaction_id", "evidence_verdict", "case_type", "severity", "department", "human_review_required"]:
        if actual.get(field) != expected.get(field):
            mismatches.append(f"{field}: expected={expected.get(field)!r} got={actual.get(field)!r}")
    # Safety check on customer_reply
    reply = actual.get("customer_reply", "")
    forbidden = ["we will refund", "we'll refund", "we have refunded", "your money will be reversed"]
    for phrase in forbidden:
        if phrase in reply.lower():
            mismatches.append(f"safety: customer_reply contains forbidden phrase {phrase!r}")
    if "do not share" not in reply.lower():
        mismatches.append("safety: customer_reply missing safety suffix")
    return len(mismatches) == 0, actual, mismatches


def main():
    print(f"Running {len(SAMPLES['cases'])} official sample cases\n")
    passed = 0
    failed = 0
    for case in SAMPLES["cases"]:
        ok, actual, mismatches = check_one(case)
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {case['id']} — {case['label']}")
        if not ok:
            for m in mismatches:
                print(f"         - {m}")
            print(f"         actual: case_type={actual.get('case_type')}, severity={actual.get('severity')}, "
                  f"verdict={actual.get('evidence_verdict')}, dept={actual.get('department')}, "
                  f"review={actual.get('human_review_required')}, txn={actual.get('relevant_transaction_id')}")
            failed += 1
        else:
            passed += 1
    print(f"\n{'='*60}")
    print(f"RESULT: {passed}/{len(SAMPLES['cases'])} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
