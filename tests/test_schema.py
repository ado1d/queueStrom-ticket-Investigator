"""Schema + endpoint contract tests."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_ok():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_root_metadata():
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["service"] == "queuestorm-investigator"
    assert "POST /analyze-ticket" in body["endpoints"]


def test_invalid_json_returns_400():
    resp = client.post(
        "/analyze-ticket",
        content="not json at all",
        headers={"content-type": "application/json"},
    )
    assert resp.status_code == 400


def test_missing_required_field_returns_400():
    resp = client.post("/analyze-ticket", json={"ticket_id": "X"})
    assert resp.status_code == 400


def test_empty_complaint_returns_422():
    resp = client.post(
        "/analyze-ticket",
        json={"ticket_id": "T-empty", "complaint": "   "},
    )
    assert resp.status_code == 422


def test_minimal_valid_request_returns_200(sample_cases):
    case = sample_cases[0]
    resp = client.post("/analyze-ticket", json=case["request"])
    assert resp.status_code == 200
    body = resp.json()

    # All required response fields present
    required = [
        "ticket_id",
        "relevant_transaction_id",
        "evidence_verdict",
        "case_type",
        "severity",
        "department",
        "agent_summary",
        "recommended_next_action",
        "customer_reply",
        "human_review_required",
        "confidence",
        "reason_codes",
    ]
    for field in required:
        assert field in body, f"missing field: {field}"

    # Enum-value checks
    assert body["evidence_verdict"] in {"consistent", "inconsistent", "insufficient_data"}
    assert body["case_type"] in {
        "wrong_transfer", "payment_failed", "refund_request",
        "duplicate_payment", "merchant_settlement_delay",
        "agent_cash_in_issue", "phishing_or_social_engineering", "other",
    }
    assert body["severity"] in {"low", "medium", "high", "critical"}
    assert body["department"] in {
        "customer_support", "dispute_resolution", "payments_ops",
        "merchant_operations", "agent_operations", "fraud_risk",
    }
    assert 0.0 <= body["confidence"] <= 1.0
    assert isinstance(body["human_review_required"], bool)
    assert isinstance(body["reason_codes"], list)
    assert body["ticket_id"] == case["request"]["ticket_id"]
