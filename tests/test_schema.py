from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_is_exactly_ok():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_blank_complaint_returns_controlled_validation_error():
    response = client.post("/analyze-ticket", json={"ticket_id": "T-1", "complaint": "   "})
    assert response.status_code == 422
    assert "validation" in response.json()["detail"].lower()


def test_unknown_enum_returns_controlled_validation_error():
    response = client.post(
        "/analyze-ticket",
        json={"ticket_id": "T-2", "complaint": "Help", "language": "english"},
    )
    assert response.status_code == 422


def test_malformed_json_returns_controlled_client_error():
    response = client.post(
        "/analyze-ticket",
        content=b'{"ticket_id":"T-3","complaint":',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code in {400, 422}


def test_response_has_only_contract_fields_and_valid_enums():
    request = {
        "ticket_id": "T-4",
        "complaint": "I paid 500 taka and want a refund.",
        "transaction_history": [
            {
                "transaction_id": "TXN-4",
                "timestamp": "2026-04-14T10:00:00Z",
                "type": "payment",
                "amount": 500,
                "counterparty": "MERCHANT-4",
                "status": "completed",
            }
        ],
    }
    response = client.post("/analyze-ticket", json=request)
    assert response.status_code == 200
    body = response.json()
    expected = {
        "ticket_id", "relevant_transaction_id", "evidence_verdict", "case_type",
        "severity", "department", "agent_summary", "recommended_next_action",
        "customer_reply", "human_review_required", "confidence", "reason_codes",
    }
    assert set(body) == expected
    assert 0 <= body["confidence"] <= 1
