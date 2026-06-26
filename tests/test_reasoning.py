"""End-to-end reasoning tests against the 10 PRD sample cases."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


@pytest.mark.parametrize("case_index", list(range(10)))
def test_sample_case_matches_expected(sample_cases, case_index):
    case = sample_cases[case_index]
    resp = client.post("/analyze-ticket", json=case["request"])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    expected = case["expected"]

    for key, want in expected.items():
        got = body.get(key)
        assert got == want, (
            f"[{case['name']}] field '{key}': expected {want!r}, got {got!r}\n"
            f"full body: {body}"
        )


def test_wrong_transfer_english_scores_consistent(sample_cases):
    case = sample_cases[0]
    resp = client.post("/analyze-ticket", json=case["request"])
    body = resp.json()
    assert body["relevant_transaction_id"] == "TXN-9101"
    assert body["evidence_verdict"] == "consistent"


def test_phishing_critical_overrides_everything(sample_cases):
    case = sample_cases[5]
    resp = client.post("/analyze-ticket", json=case["request"])
    body = resp.json()
    assert body["case_type"] == "phishing_or_social_engineering"
    assert body["severity"] == "critical"
    assert body["department"] == "fraud_risk"
    assert body["human_review_required"] is True


def test_high_value_triggers_severity_boost(sample_cases):
    case = sample_cases[9]  # 60,000 BDT refund_request → boosted to medium
    resp = client.post("/analyze-ticket", json=case["request"])
    body = resp.json()
    assert body["case_type"] == "refund_request"
    assert body["severity"] == "medium"


def test_bangla_or_banglish_still_routes_correctly(sample_cases):
    # Case 5 uses banglish; should still match correctly because ENABLE_LLM=false
    case = sample_cases[4]
    resp = client.post("/analyze-ticket", json=case["request"])
    body = resp.json()
    assert body["case_type"] == "agent_cash_in_issue"
    assert body["department"] == "agent_operations"


def test_no_match_insufficient_data(sample_cases):
    case = sample_cases[7]  # vague complaint, empty history
    resp = client.post("/analyze-ticket", json=case["request"])
    body = resp.json()
    assert body["evidence_verdict"] == "insufficient_data"
    assert body["relevant_transaction_id"] is None
