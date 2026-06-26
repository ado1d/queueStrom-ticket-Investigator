# QueueStorm Investigator

> **Evidence-grounded AI/API copilot for digital finance support tickets.**
> Built for the **bKash SUST CSE Carnival 2026** (preliminary round, 4.5-hour online hackathon).

QueueStorm Investigator is a stateless FastAPI service that triages fintech
support tickets by cross-referencing the customer's complaint text against
their transaction history. The pipeline runs **rules-first** for speed and
determinism, with an **optional LLM fallback** (Google Gemini 2.5 Flash or
Groq Llama 3.3 70B) that augments the rules output on every request when
enabled. Every response is post-processed by a safety sanitizer that strips
credentials, rewrites refund promises, and appends a mandatory
customer-protection suffix.

---

## ⚡ TL;DR

```bash
git clone <repo-url> queuestorm-investigator
cd queuestorm-investigator
pip install -r requirements.txt
copy .env.example .env       # Windows cmd — or: cp .env.example .env on *nix
                             # paste GEMINI_API_KEY or GROQ_API_KEY if you have one
uvicorn app.main:app --host 127.0.0.1 --port 8000

# in another terminal
curl http://127.0.0.1:8000/health
curl -X POST http://127.0.0.1:8000/analyze-ticket \
     -H "Content-Type: application/json" \
     -d @sample_outputs/sample_case_01.json
```

The service runs **without any LLM key** — it just becomes rules-only.

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    POST /analyze-ticket                     │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ 1.  Evidence engine (rules-only)                            │
│     • extract_clues (bilingual EN / BN / Banglish regex)    │
│     • score_transactions + match_transaction                │
│     • verdict + compute_confidence                         │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ 2.  LLM fallback (optional, runs whenever ENABLE_LLM=true)  │
│     • Provider: [redacted] (default) or Groq                 │
│     • Strict JSON-only prompt — never writes customer copy   │
│     • May surface: candidate txn id, amount, counterparty,  │
│       contradiction flag, case_type hint                    │
│     • On failure (timeout, 429, bad JSON): rules-only result │
│       is used; llm_status reports "failed:<reason>"          │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ 3.  Classifier (decision tree)                              │
│     • Phishing check runs FIRST → always routes to fraud    │
│     • Maps (txn_type, status, topics) → (case, severity,    │
│       department)                                           │
│     • Severity boosts for high-value + merchant             │
│     • Human-review rules: critical, inconsistent,           │
│       high-risk+uncertain, wrong_transfer, low-confidence   │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ 4.  Text generation (template-only — LLM NEVER writes the   │
│     customer_reply)                                         │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ 5.  Safety sanitizer                                        │
│     • strip_prompt_injection                                │
│     • scrub_forbidden (PIN/OTP/redact + refund rewrites)    │
│     • append_safety_suffix                                  │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
                       AnalyzeResponse (JSON)
```

---

## 📡 Endpoints

### `GET /health`

Liveness probe used by Render, Poridhi, and judges.

```json
{ "status": "ok" }
```

### `GET /`

Service metadata + LLM status flag.

```json
{
  "service": "queuestorm-investigator",
  "version": "1.0.0",
  "endpoints": ["GET /health", "POST /analyze-ticket"],
  "llm_enabled": true
}
```

### `POST /analyze-ticket`

Full triage pipeline. See `sample_outputs/sample_case_01.json` for a
realistic request/response pair.

**Request** (`application/json`):

| Field               | Type           | Required | Notes                                  |
|---------------------|----------------|----------|----------------------------------------|
| `ticket_id`         | string         | ✓        | Caller-supplied                        |
| `complaint`         | string         | ✓        | Non-empty after trim                   |
| `language`          | enum           | ✗        | `en` / `bn` / `mixed`                  |
| `channel`           | enum           | ✗        | `in_app_chat` / `call_center` / ...    |
| `user_type`         | enum           | ✗        | `customer` / `merchant` / `agent` ...  |
| `campaign_context`  | string         | ✗        | Optional tag                           |
| `transaction_history` | array<object> | ✗        | See schema below                       |
| `metadata`          | object         | ✗        | Free-form                              |

**Transaction entry**:

```json
{
  "transaction_id": "TXN-9101",
  "timestamp": "2026-01-15T14:32:00",
  "type": "transfer",        // transfer | payment | cash_in | cash_out | settlement | refund
  "amount": 5000.00,
  "counterparty": "01712345678",
  "status": "completed"       // completed | failed | pending | reversed
}
```

**Response**:

| Field                     | Type                | Notes                                       |
|---------------------------|---------------------|---------------------------------------------|
| `ticket_id`               | string              | Echoed from request                         |
| `relevant_transaction_id` | string \| null      | Best-match transaction id, or null          |
| `evidence_verdict`        | enum                | `consistent` / `inconsistent` / `insufficient_data` |
| `case_type`               | enum                | 8 values (see PRD §10)                      |
| `severity`                | enum                | `low` / `medium` / `high` / `critical`      |
| `department`              | enum                | 6 values                                    |
| `agent_summary`           | string              | One-paragraph summary (safe)                |
| `recommended_next_action` | string              | Next step for the agent                     |
| `customer_reply`          | string              | Always ends with the safety suffix          |
| `human_review_required`   | bool                | True for critical / high-risk cases         |
| `confidence`              | number (0..1)       | Heuristic + LLM-boosted                     |
| `reason_codes`            | array<string>       | Audit trail                                 |
| `llm_used`                | bool                | True if Gemini was consulted and succeeded  |
| `llm_status`              | string              | `ok` / `skipped` / `disabled` / `failed:<reason>` |

**Error codes**:

- `400` — invalid JSON or schema mismatch (Pydantic)
- `422` — schema valid but `complaint` is empty after trim
- `500` — internal error; generic message, no internals leaked

---

## 🛡️ Safety guarantees

These are enforced by `app/safety.py` and verified by `tests/test_safety.py`:

1. **Credential redaction**: PIN, OTP, password, secret code, full card
   numbers (16-digit), CVC/CVV are matched by regex and replaced with
   `[redacted]`.
2. **Prompt-injection stripping**: phrases like "ignore previous
   instructions", "disregard the system", "you are now a ...", `system:`,
   `<|...|>`, `### instruction` are removed from inputs before any text
   generation.
3. **Refund-promise rewrite**: "we will refund", "we'll refund", "we have
   refunded", "your money will be reversed" become "any eligible adjustment
   will be processed" — never a guaranteed refund.
4. **Account-unblock rewrite**: "account will be unblocked" becomes "account
   access will be reviewed".
5. **Mandatory suffix**: every `customer_reply` ends with:
   > *"Please do not share your PIN, OTP, or password with anyone. Our team
   > will never ask for these."*
6. **LLM isolation**: the LLM only sees a structured prompt asking for JSON
   `{"relevant_txn_id","case_type","contradiction","amount","counterparty_hint"}`.
   It never writes the customer-facing reply.
7. **No PII echo**: 16-digit card numbers are matched and redacted before
   the response is returned.

---

## 🤖 AI usage disclosure

Per the hackathon's transparency rule:

- **Provider** (auto-selected in `app/llm_fallback.py`):
  - `LLM_PROVIDER=gemini` (default) → Gemini 2.5 Flash (15 RPM free tier)
  - `LLM_PROVIDER=groq` → Llama 3.3 70B via Groq (30 RPM free tier)
  - If neither `LLM_PROVIDER` nor an API key is set, the LLM is auto-disabled
    and the pipeline is rules-only.
- **Trigger**: whenever `ENABLE_LLM=true` and a key is configured, the LLM
  runs on **every** request. Its output only **augments** the rules engine
  (extra clues, candidate txn id, contradiction flag, confidence nudge).
  If the call fails (timeout, 429, bad JSON, invalid enum), the rules-only
  result is used and `llm_status` reports the reason.
- **What it sees**: the complaint text, a compact list of recent
  transactions, and a strict system prompt requesting JSON only.
- **What it produces**: a small JSON fact block. It does **not** generate
  the `customer_reply`, `agent_summary`, or `recommended_next_action` —
  those are always template-generated by `app/text_gen.py`.
- **Rate-limit handling**: exponential backoff with jitter on HTTP 429 and
  5xx (up to 3 retries), plus an in-process LRU cache (size 64) keyed on
  `(complaint, txn_ids)` so repeated identical requests don't re-burn quota.
- **Failure handling**: timeouts, HTTP errors, JSON parse errors, and
  schema-invalid responses all degrade gracefully (the rules-only result
  is used). Failures are logged but never bubble up to the caller, and the
  classifier sets `human_review_required = true` when confidence is low.

---

## 🚀 Deployment

The repo ships three deployment targets. See [`RUNBOOK.md`](./RUNBOOK.md)
for the full operator guide.

| Target          | Use case                              | One-liner                                                              |
|-----------------|---------------------------------------|------------------------------------------------------------------------|
| **Local**       | Development, smoke test               | `uvicorn app.main:app --reload`                                        |
| **Docker**      | Reproducible container                | `docker build -t qsi . && docker run --rm -p 8000:8000 --env-file .env qsi` |
| **Render**      | Public demo URL, free tier            | Connect repo → Render reads `render.yaml` → done                      |
| **Poridhi Lab** | **Primary hackathon deployment**      | Push image to Docker Hub → launch on Poridhi with env vars             |

---

## ⚙️ Environment variables

Copy `.env.example` to `.env` and fill in what you need.

| Key              | Default | Description                                                |
|------------------|---------|------------------------------------------------------------|
| `PORT`           | `8000`  | uvicorn listen port (Render/Poridhi require `8000`)        |
| `ENABLE_LLM`     | `true`  | Master switch for the LLM fallback                          |
| `LLM_PROVIDER`   | *auto*  | `gemini` or `groq`. Auto-picks if neither is set            |
| `GEMINI_API_KEY` | *(empty)* | Free key from aistudio.google.com (Gemini 2.5 Flash, 15 RPM) |
| `GROQ_API_KEY`   | *(empty)* | Free key from console.groq.com (Llama 3.3 70B, 30 RPM)      |
| `LLM_TIMEOUT`    | `8`     | Per-request timeout in seconds                              |
| `LOG_LEVEL`      | `INFO`  | `DEBUG` / `INFO` / `WARNING` / `ERROR`                      |

The service runs **without any key** — it becomes rules-only and every request
still returns a full answer.

---

## 🧪 Testing

```bash
python -m pytest
# 36 passed in ~1 s
```

The test suite covers:

- **Schema validation**: health, root, malformed payloads, empty complaint.
- **Reasoning**: all 10 PRD sample cases end-to-end through the live API,
  plus targeted assertions on phishing override, severity boosts, Bangla
  routing, and insufficient-data handling.
- **Safety**: suffix append, forbidden-phrase scrub, prompt-injection strip,
  credential leak prevention, refund-promise rewrite, card-number scrub.
- **LLM fallback**: JSON extraction, garbage handling, enum validation,
  amount coercion, disabled-mode short-circuit, timeout fallback.

LLM tests use mocked `httpx` clients — **no real API calls during tests**.

---

## 📂 Repo layout

```
queuestorm-investigator/
├── app/
│   ├── classifier.py        # phishing-first decision tree + severity boosts
│   ├── config.py            # env loader (single Settings instance)
│   ├── evidence.py          # clue extraction + scoring + verdict + confidence
│   ├── llm_fallback.py      # multi-provider LLM client (Gemini + Groq)
│   ├── main.py              # FastAPI app: /health, /analyze-ticket, /
│   ├── pipeline.py          # orchestrator: evidence → LLM → classify → text → safety
│   ├── rules_config.py      # bilingual regex + keyword dicts + blocklists
│   ├── safety.py            # sanitizer: strip / scrub / rewrite / suffix
│   ├── schemas.py           # Pydantic models + Literal enums
│   └── text_gen.py          # per-case-type template dict
├── tests/
│   ├── conftest.py          # disable_llm autouse fixture + 10-case fixture
│   ├── fixtures/
│   │   └── sample_cases.json
│   ├── test_schema.py
│   ├── test_reasoning.py
│   ├── test_safety.py
│   └── test_llm_fallback.py
├── sample_outputs/
│   ├── sample_case_01.json            # wrong_transfer (English)
│   ├── sample_case_02_phishing.json   # phishing_or_social_engineering
│   └── sample_case_03_payment_failed.json
├── Dockerfile                # multi-stage python:3.11-slim, non-root, < 250 MB
├── render.yaml               # Render Blueprint
├── RUNBOOK.md                # full deployment + ops guide
├── requirements.txt
├── .env.example
├── .dockerignore
├── pytest.ini
└── README.md                 # ← you are here
```

---

## ⚠️ Known limitations

- **Single language pair**: regex covers English + Bangla + Banglish; other
  languages fall through to the LLM if enabled, otherwise `other`.
- **No persistence**: the service is stateless. Ticket history, agent
  decisions, and audit logs are expected to live in the caller's system.
- **Free-tier LLM**: both Gemini (15 RPM) and Groq (30 RPM) hit rate limits
  under heavy load. The retry+cache layer in `app/llm_fallback.py` absorbs
  bursts; for production, swap in a paid endpoint or a local model.
- **Render cold start**: the free tier spins down after 15 min idle. First
  request after idle takes ~30 s.
- **No transaction signing**: `transaction_history` is trusted as-is. In a
  real deployment, sign or HMAC these entries at the edge.

---

## 📜 License & credits

Built in 4.5 hours by Team **VibeJS** for the **bKash SUST CSE Carnival
2026**. MIT for the source; please credit if you reuse the templates.
