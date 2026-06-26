import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
FIXTURE = Path(__file__).parent / "fixtures" / "public_sample_cases.json"
CASES = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_public_examples_match_required_reasoning_fields(case):
    response = client.post("/analyze-ticket", json=case["input"])
    assert response.status_code == 200, response.text
    actual = response.json()
    expected = case["expected_output"]

    for field in (
        "ticket_id", "relevant_transaction_id", "evidence_verdict", "case_type",
        "severity", "department", "human_review_required",
    ):
        assert actual[field] == expected[field], f"{case['id']} mismatch in {field}: {actual}"


def test_inconsistent_wrong_transfer_pattern_is_flagged_for_human_review():
    case = next(item for item in CASES if item["id"] == "SAMPLE-02")
    response = client.post("/analyze-ticket", json=case["input"])
    body = response.json()
    assert body["evidence_verdict"] == "inconsistent"
    assert body["human_review_required"] is True
    assert "established_recipient_pattern" in body["reason_codes"]


def test_ambiguous_match_does_not_guess_a_transaction():
    case = next(item for item in CASES if item["id"] == "SAMPLE-08")
    body = client.post("/analyze-ticket", json=case["input"]).json()
    assert body["relevant_transaction_id"] is None
    assert body["evidence_verdict"] == "insufficient_data"
    assert body["case_type"] == "wrong_transfer"
    assert body["human_review_required"] is False
