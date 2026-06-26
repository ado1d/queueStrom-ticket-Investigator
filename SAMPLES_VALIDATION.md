# Sample Pack Validation Results

This document records the validation of the QueueStorm Investigator against
the **10-case official sample pack** provided by the hackathon organizers
("Public Sample Case Pack v1.0").

## How to reproduce

```bash
cd queuestorm-investigator
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m pytest                 # 36 unit tests pass
# Then run the 10 official samples (download the sample pack JSON separately
# from the hackathon site, or use the inline copy in tests/fixtures/):
PYTHONPATH=. python scripts/run_samples.py
```

## Results

| Sample | Label | Status |
|--------|-------|--------|
| SAMPLE-01 | Wrong transfer with matching evidence | ✅ PASS |
| SAMPLE-02 | Wrong transfer claim with inconsistent evidence | ✅ PASS |
| SAMPLE-03 | Failed payment with balance deducted | ✅ PASS |
| SAMPLE-04 | Refund request requiring safe handling | ✅ PASS |
| SAMPLE-05 | Phishing or social engineering report | ✅ PASS |
| SAMPLE-06 | Vague complaint, insufficient evidence | ✅ PASS |
| SAMPLE-07 | Agent cash-in issue, Bangla complaint | ✅ PASS |
| SAMPLE-08 | Multiple plausible transactions, ambiguous match | ✅ PASS |
| SAMPLE-09 | Merchant settlement delay | ✅ PASS |
| SAMPLE-10 | Duplicate payment claim | ✅ PASS |

**Total: 10/10 pass on all critical fields** (`relevant_transaction_id`,
`evidence_verdict`, `case_type`, `severity`, `department`,
`human_review_required`).

## Field comparison policy

For each sample, we compare the following fields exactly:

- `relevant_transaction_id` — must match exactly (including `null`)
- `evidence_verdict` — must match exactly
- `case_type` — must match exactly
- `severity` — must match exactly
- `department` — must match exactly
- `human_review_required` — must match exactly

The text fields (`agent_summary`, `recommended_next_action`,
`customer_reply`) are checked for **safety** (no forbidden phrases, safety
suffix present) but NOT for exact text match — the spec explicitly allows
"other valid responses" as long as they are functionally equivalent.

## Notable behaviors

### Established-recipient pattern (SAMPLE-02)
When a customer claims "wrong transfer" but their history shows 2+ prior
completed transfers to the same counterparty, the verdict is marked
`inconsistent` and severity is lowered to `medium`. The case still routes
to `dispute_resolution` and forces `human_review_required: true` — a human
must verify whether this was genuinely a mistake before any reversal.

### Duplicate detection (SAMPLE-10)
When the customer mentions "twice"/"double charged" AND two near-identical
completed transactions exist (same amount, same counterparty, within 60s),
the **second (later)** transaction is identified as the suspected duplicate.
This overrides the normal tie-break behavior (which would refuse to pick).

### Ambiguous match (SAMPLE-08)
When 3+ transactions all score above the match threshold AND the top two
are within 1 point of each other, the system refuses to pick any
(`relevant_transaction_id: null`, `evidence_verdict: insufficient_data`).
The customer is asked for the disambiguating detail (e.g. "the brother's
number") instead of risking an incorrect dispute.

### Bangla customer replies (SAMPLE-07)
When `language: "bn"` or `"mixed"`, the `customer_reply` is rendered from
Bangla templates. `agent_summary` and `recommended_next_action` stay in
English (they're internal agent-facing fields, not customer-facing).

### Refund on completed payment (SAMPLE-04)
A refund request on a *completed* merchant payment (change-of-mind
scenario) routes to `refund_request` / `customer_support` (low severity),
NOT to `payment_failed` / `payments_ops`. The customer_reply never
promises a refund — it says "any eligible adjustment will be processed
through official channels".

### Vague complaints (SAMPLE-06)
A complaint with no extracted clues (no amount, no transaction type, no
topics) returns `case_type: "other"`, `severity: "low"`,
`human_review_required: false`. The customer is asked for clarification
rather than auto-escalating to a human reviewer.
