"""Gemini LLM fallback wrapper.

Per PRD section 12: the LLM is called ONLY when the rule-based engine is
uncertain. The LLM returns a small structured fact block (JSON) -- it never
produces the customer reply, agent summary, or next action.

Failure mode: any error (timeout, bad JSON, invalid enum) returns
`LLMResult(used=False, ok=False)` and the pipeline falls back to a safe
default. The classifier then sets `human_review_required = true`.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx

from .config import settings

logger = logging.getLogger("queuestorm.llm")

GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.0-flash:generateContent"
)

ALLOWED_CASE_TYPES = {
    "wrong_transfer",
    "payment_failed",
    "refund_request",
    "duplicate_payment",
    "merchant_settlement_delay",
    "agent_cash_in_issue",
    "phishing_or_social_engineering",
    "other",
}

SYSTEM_PROMPT = (
    "You are an evidence extractor for a fintech support triage system. "
    "You will receive a customer complaint (possibly in English, Bangla, "
    "or Banglish) and a JSON array of recent transactions. "
    "Output ONLY a compact JSON object with these keys and nothing else: "
    '{"relevant_txn_id": <string|null>, '
    '"case_type": <one of: wrong_transfer|payment_failed|refund_request|'
    'duplicate_payment|merchant_settlement_delay|agent_cash_in_issue|'
    'phishing_or_social_engineering|other>, '
    '"contradiction": <boolean>, '
    '"amount": <number|null>, '
    '"counterparty_hint": <string|null>}. '
    "Do NOT write any customer-facing text. Do NOT apologise. Do NOT ask "
    "for credentials. Return JSON only."
)


@dataclass
class LLMResult:
    used: bool
    ok: bool
    relevant_txn_id: Optional[str] = None
    case_type: Optional[str] = None
    contradiction: Optional[bool] = None
    amount: Optional[float] = None
    counterparty_hint: Optional[str] = None
    raw_text: str = ""
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "used": self.used,
            "ok": self.ok,
            "relevant_txn_id": self.relevant_txn_id,
            "case_type": self.case_type,
            "contradiction": self.contradiction,
            "amount": self.amount,
            "counterparty_hint": self.counterparty_hint,
            "error": self.error,
        }


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    """Find the first JSON object in the LLM response."""
    if not text:
        return None
    # Strip markdown fences.
    text = re.sub(r"```(?:json)?", "", text, flags=re.IGNORECASE)
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def _validate(obj: Dict[str, Any]) -> Optional[LLMResult]:
    """Validate the parsed JSON against allowed enums."""
    case_type = obj.get("case_type")
    if case_type not in ALLOWED_CASE_TYPES:
        return None
    relevant = obj.get("relevant_txn_id")
    if relevant is not None and not isinstance(relevant, str):
        return None
    contradiction = obj.get("contradiction")
    if contradiction is not None and not isinstance(contradiction, bool):
        return None
    amount = obj.get("amount")
    if amount is not None:
        try:
            amount = float(amount)
        except (TypeError, ValueError):
            amount = None
    counterparty_hint = obj.get("counterparty_hint")
    if counterparty_hint is not None and not isinstance(counterparty_hint, str):
        counterparty_hint = None
    return LLMResult(
        used=True,
        ok=True,
        relevant_txn_id=relevant,
        case_type=case_type,
        contradiction=contradiction,
        amount=amount,
        counterparty_hint=counterparty_hint,
    )


async def call_gemini(
    complaint: str,
    transactions: List[Dict[str, Any]],
    language: Optional[str] = None,
) -> LLMResult:
    """Call Gemini with a strict extraction prompt. Always returns an LLMResult."""
    if not settings.llm_enabled:
        return LLMResult(used=False, ok=False, error="llm_disabled")

    payload = {
        "systemInstruction": {
            "role": "system",
            "parts": [{"text": SYSTEM_PROMPT}],
        },
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "text": (
                            f"language: {language or 'unknown'}\n"
                            f"complaint: {complaint}\n"
                            f"transactions: {json.dumps(transactions, ensure_ascii=False)}"
                        )
                    }
                ],
            }
        ],
        "generationConfig": {
            "temperature": 0.0,
            "responseMimeType": "application/json",
            "maxOutputTokens": 256,
        },
    }

    params = {"key": settings.gemini_api_key}
    timeout = httpx.Timeout(settings.llm_timeout, connect=3.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(GEMINI_URL, params=params, json=payload)
            response.raise_for_status()
            body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("gemini call failed: %s", exc)
        return LLMResult(used=True, ok=False, error=str(exc))

    # Extract text from Gemini's response shape.
    text = ""
    try:
        candidates = body.get("candidates") or []
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            text = "".join(p.get("text", "") for p in parts)
    except (AttributeError, TypeError, IndexError) as exc:
        logger.warning("gemini response shape unexpected: %s", exc)
        return LLMResult(used=True, ok=False, error="bad_response_shape", raw_text=str(body)[:500])

    parsed = _extract_json(text)
    if parsed is None:
        return LLMResult(used=True, ok=False, error="unparseable_json", raw_text=text[:500])

    validated = _validate(parsed)
    if validated is None:
        return LLMResult(used=True, ok=False, error="invalid_enums", raw_text=text[:500])

    validated.raw_text = text[:500]
    return validated
