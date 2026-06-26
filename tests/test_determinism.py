import copy

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_same_request_produces_same_output():
    payload = {
        "ticket_id": "DET-1",
        "complaint": "I sent 5000 taka to a wrong number around 2pm.",
        "transaction_history": [
            {
                "transaction_id": "TXN-1",
                "timestamp": "2026-04-14T14:08:22Z",
                "type": "transfer",
                "amount": 5000,
                "counterparty": "+8801719876543",
                "status": "completed",
            }
        ],
    }
    one = client.post("/analyze-ticket", json=payload).json()
    two = client.post("/analyze-ticket", json=payload).json()
    assert one == two


def test_duplicate_selection_is_history_order_independent():
    payload = {
        "ticket_id": "DET-2",
        "complaint": "My electricity bill payment of 850 was deducted twice.",
        "transaction_history": [
            {
                "transaction_id": "TXN-OLD",
                "timestamp": "2026-04-14T08:15:30Z",
                "type": "payment",
                "amount": 850,
                "counterparty": "BILLER-DESCO",
                "status": "completed",
            },
            {
                "transaction_id": "TXN-NEW",
                "timestamp": "2026-04-14T08:15:42Z",
                "type": "payment",
                "amount": 850,
                "counterparty": "BILLER-DESCO",
                "status": "completed",
            },
        ],
    }
    shuffled = copy.deepcopy(payload)
    shuffled["transaction_history"].reverse()
    first = client.post("/analyze-ticket", json=payload).json()
    second = client.post("/analyze-ticket", json=shuffled).json()
    assert first["relevant_transaction_id"] == "TXN-NEW"
    assert second["relevant_transaction_id"] == "TXN-NEW"
    assert first["case_type"] == second["case_type"] == "duplicate_payment"
