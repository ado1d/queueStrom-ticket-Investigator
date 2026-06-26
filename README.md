# QueueStorm Investigator

A lightweight, rules-first FastAPI service for safe fintech support-ticket triage. It receives a customer complaint and a short synthetic transaction-history snippet, then returns a structured investigation result for a support agent.

This implementation is designed for the **QueueStorm Investigator** preliminary API contract:

- `GET /health` returns `{"status":"ok"}`.
- `POST /analyze-ticket` accepts one ticket and returns the required structured response.
- It is deterministic, offline-first, container-ready, and does not require a database, GPU, browser UI, or external model for correct core behavior.

## Why this design

The task is an investigation problem, not a chatbot problem. The service therefore keeps the critical path deterministic:

1. **Validate** the request with Pydantic enums and non-empty semantic checks.
2. **Strip prompt-injection-like clauses** before analysis.
3. **Extract evidence** from English, Bangla, and common Banglish wording: amounts, transaction IDs, phone numbers, approximate times, topics, and transaction-status clues.
4. **Score each supplied transaction** using visible rule weights.
5. **Refuse to guess** when multiple records are equally plausible.
6. **Classify and route** using a fixed business-policy decision tree.
7. **Generate templates from verified fields only**, then apply a final fintech safety filter.

```mermaid
flowchart LR
    A[POST /analyze-ticket] --> B[Schema validation]
    B --> C[Injection-clause filter]
    C --> D[Evidence extraction]
    D --> E[Transaction matching and verdict]
    E --> F[Case classification and routing]
    F --> G[Template text generation]
    G --> H[Safety sanitizer]
    H --> I[Structured JSON response]
```

## Evidence policy

The transaction matcher uses transparent, deterministic evidence weights:

| Evidence | Score contribution |
|---|---:|
| Explicit transaction ID in complaint | +0.85 |
| Exact amount match | +0.45 |
| Expected transaction type match | +0.25 |
| Counterparty/phone match | +0.35 |
| Approximate hour match | +0.12 |
| Expected `failed` or `pending` status | +0.16 to +0.20 |

A transaction needs a score of at least `0.50` to be selected. When the leading two candidates are within `0.12` and there is no explicit transaction ID or counterparty match, the service returns:

- `relevant_transaction_id: null`
- `evidence_verdict: insufficient_data`

This is deliberate: ambiguous evidence must not create the wrong dispute.

## Safety policy

The service never requests PINs, OTPs, passwords, passcodes, or full card numbers. It also does not promise refunds, reversals, recovery, or account unblocking. Replies use conditional language such as:

> Any eligible amount, if approved, will be returned through official channels.

Prompt-like instructions inside a complaint are not treated as trusted instructions. Customer text is never copied into generated replies, so adversarial wording cannot direct the output.

## Models

| Model / approach | Where it runs | Why it is used |
|---|---|---|
| Deterministic rules, regex, and policy tree | Local Python process | Fast, reproducible, explainable, and safe without a network/API key. This is the authoritative decision engine. |
| Optional Gemini language/ambiguity hint | External API, disabled by default | Optional enhancement only. It never selects a transaction, evidence verdict, case type, severity, or department. Any timeout/error fails closed to the local rules path. |

`ENABLE_LLM=false` is the recommended judging configuration. No LLM call is needed for the core API.

## Repository structure

```text
.
├── app/
│   ├── main.py              # FastAPI routes and safe error handlers
│   ├── schemas.py           # Exact request/response enums and validation
│   ├── evidence.py          # Clues, matching, ambiguity, evidence verdict
│   ├── classifier.py        # Case type, severity, department, escalation
│   ├── text_gen.py          # Facts-only templates
│   ├── safety.py            # Injection and unsafe-language safeguards
│   ├── rules_config.py      # Central keyword/policy constants
│   ├── config.py            # Environment configuration
│   └── llm_fallback.py      # Optional non-authoritative hint client
├── tests/
│   ├── fixtures/public_sample_cases.json
│   ├── test_schema.py
│   ├── test_reasoning.py
│   ├── test_safety.py
│   └── test_determinism.py
├── sample_outputs/sample_case_01.json
├── Dockerfile
├── requirements.txt
├── .env.example
├── README.md
└── RUNBOOK.md
```

## Local run

### Prerequisites

- Python 3.11+
- Docker (optional)

### Python

```bash
python -m venv .venv
# Linux/macOS
source .venv/bin/activate
# Windows PowerShell
# .venv\Scripts\Activate.ps1

pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Verify:

```bash
curl http://127.0.0.1:8000/health
# {"status":"ok"}
```

### Docker

```bash
docker build -t queuestorm-investigator:latest .
docker run --rm -p 8000:8000 --env-file .env queuestorm-investigator:latest
```

The image runs as a non-root user and has no large model download.

## API reference

### `GET /health`

**Response**

```json
{"status":"ok"}
```

### `POST /analyze-ticket`

**Example request**

```json
{
  "ticket_id": "TKT-001",
  "complaint": "I sent 5000 taka to a wrong number around 2pm today.",
  "language": "en",
  "channel": "in_app_chat",
  "user_type": "customer",
  "transaction_history": [
    {
      "transaction_id": "TXN-9101",
      "timestamp": "2026-04-14T14:08:22Z",
      "type": "transfer",
      "amount": 5000,
      "counterparty": "+8801719876543",
      "status": "completed"
    }
  ]
}
```

**Example response**

```json
{
  "ticket_id": "TKT-001",
  "relevant_transaction_id": "TXN-9101",
  "evidence_verdict": "consistent",
  "case_type": "wrong_transfer",
  "severity": "high",
  "department": "dispute_resolution",
  "agent_summary": "Customer reports a possible wrong-recipient transfer of 5,000 BDT linked to TXN-9101. Available transaction data matches the reported amount and transfer context.",
  "recommended_next_action": "Route TXN-9101 to dispute_resolution to verify the recipient and transaction context under the applicable dispute policy; do not promise an outcome.",
  "customer_reply": "We have noted your concern about transaction TXN-9101. Our dispute team will review the available details under the applicable policy. We cannot confirm the outcome until the review is complete. Please do not share your PIN, OTP, password, or full card number with anyone.",
  "human_review_required": true,
  "confidence": 0.9,
  "reason_codes": ["amount_match", "transaction_type_match", "time_match", "wrong_transfer", "transaction_match", "dispute_initiated"]
}
```

## Environment variables

| Name | Default | Purpose |
|---|---:|---|
| `PORT` | `8000` | Uvicorn port. |
| `LOG_LEVEL` | `INFO` | Runtime logging level. |
| `HIGH_VALUE_BDT` | `50000` | Amount threshold that requires human review. |
| `ENABLE_LLM` | `false` | Enables the optional non-authoritative Gemini hint path. |
| `GEMINI_API_KEY` | empty | Only needed when `ENABLE_LLM=true`. Never commit it. |
| `GEMINI_MODEL` | `gemini-2.0-flash` | Optional Gemini model name. |
| `LLM_TIMEOUT` | `8` | Bound for optional LLM calls. |

Use `.env.example` as a template. The default configuration needs no secret.

## Test

```bash
pytest -q
```

The suite checks:

- health and schema/enum handling;
- all 10 supplied public samples against their evidence, classification, routing, severity, and escalation expectations;
- bilingual cash-in and phishing handling;
- malformed/blank requests;
- safe replies and resistance to prompt-injection text;
- deterministic output even when transaction history order is shuffled.

## Deployment

See [RUNBOOK.md](RUNBOOK.md) for a Docker-first deployment guide. A public HTTPS URL is the preferred submission path; a Docker image/run command is the fallback path.

## Known limitations

- This is a synthetic-data support copilot, not a real payment-system integration.
- It does not query a ledger, initiate financial action, or authoritatively determine whether a balance was debited.
- Keyword-based Bangla/Banglish support covers high-signal operational phrases, not every dialect or misspelling.
- A real production rollout would add authenticated access, structured telemetry, immutable audit storage, monitoring, policy versioning, and a human-agent review UI.
