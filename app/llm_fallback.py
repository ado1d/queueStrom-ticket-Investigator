"""LLM fallback wrapper — multi-provider (Gemini + Groq).

Per PRD section 12: the LLM is called ONLY when the rule-based engine is
uncertain. The LLM returns a small structured fact block (JSON) -- it never
produces the customer reply, agent summary, or next action.

Provider selection:
  * LLM_PROVIDER=groq  (default if GROQ_API_KEY is set) — 30 RPM free tier,
    Llama 3.3 70B, OpenAI-compatible API.
  * LLM_PROVIDER=gemini — 15 RPM free tier, Gemini 2.5 Flash.
  * Auto: if neither LLM_PROVIDER nor a key is set, LLM is disabled.

Failure mode: any error (timeout, bad JSON, invalid enum) returns
`LLMResult(used=False, ok=False)` and the pipeline falls back to a safe
default. The classifier then sets `human_review_required = true`.

Rate-limit handling:
  * Exponential backoff with jitter on HTTP 429 / 5xx (up to 3 retries).
  * In-memory LRU cache keyed on (complaint, txn_ids) so repeated identical
    requests within the same process don't re-burn quota.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import httpx

from .config import settings

logger = logging.getLogger("queuestorm.llm")

GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.5-flash:generateContent"
)
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"


def _is_retryable(exc: Exception) -> bool:
    """Return True for transient errors worth retrying (429, 5xx, network)."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in {429, 500, 502, 503, 504}
    return isinstance(exc, (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError))


# In-process LRU cache for LLM results.
_LLM_CACHE: Dict[Tuple[str, Tuple[str, ...]], "LLMResult"] = {}
_LLM_CACHE_MAX = 64


def _cache_key(complaint: str, transactions: List[Dict[str, Any]]) -> Tuple[str, Tuple[str, ...]]:
    norm = re.sub(r"\s+", " ", (complaint or "").lower().strip())
    txn_ids = tuple(t.get("transaction_id", "") for t in transactions)
    return (norm, txn_ids)


def clear_llm_cache() -> None:
    """Test/admin helper to flush the cache."""
    _LLM_CACHE.clear()


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


def _select_provider() -> Optional[str]:
    """Pick which LLM provider to use based on env vars.

    Priority:
      1. Explicit LLM_PROVIDER env var ('groq' or 'gemini').
      2. If GROQ_API_KEY is set, use Groq (higher free-tier RPM).
      3. If GEMINI_API_KEY is set, use Gemini.
      4. Otherwise None (LLM disabled).
    """
    explicit = (os.getenv("LLM_PROVIDER") or "").strip().lower()
    if explicit in {"groq", "gemini"}:
        return explicit
    if (os.getenv("GROQ_API_KEY") or "").strip():
        return "groq"
    if (os.getenv("GEMINI_API_KEY") or "").strip():
        return "gemini"
    return None


async def _call_groq(
    complaint: str,
    transactions: List[Dict[str, Any]],
    language: Optional[str],
    timeout: httpx.Timeout,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Call Groq's OpenAI-compatible endpoint. Returns (body, error)."""
    api_key = (os.getenv("GROQ_API_KEY") or "").strip()
    if not api_key:
        return None, "missing_groq_key"
    user_text = (
        f"language: {language or 'unknown'}\n"
        f"complaint: {complaint}\n"
        f"transactions: {json.dumps(transactions, ensure_ascii=False)}"
    )
    payload = {
        "model": GROQ_MODEL,
        "temperature": 0.0,
        "max_tokens": 256,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    return await _http_post_with_retry(GROQ_URL, payload, timeout, headers=headers)


async def _call_gemini(
    complaint: str,
    transactions: List[Dict[str, Any]],
    language: Optional[str],
    timeout: httpx.Timeout,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Call Gemini's generateContent endpoint. Returns (body, error)."""
    api_key = (settings.gemini_api_key or "").strip()
    if not api_key:
        return None, "missing_gemini_key"
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
    params = {"key": api_key}
    return await _http_post_with_retry(GEMINI_URL, payload, timeout, params=params)


async def _http_post_with_retry(
    url: str,
    payload: Dict[str, Any],
    timeout: httpx.Timeout,
    *,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, str]] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """POST with exponential backoff on 429/5xx. Returns (body_json, error)."""
    max_retries = 3
    retryable_statuses = {429, 500, 502, 503, 504}
    async with httpx.AsyncClient(timeout=timeout) as client:
        for attempt in range(max_retries + 1):
            try:
                response = await client.post(url, params=params, json=payload, headers=headers)
                status = getattr(response, "status_code", 200)
                if status in retryable_statuses and attempt < max_retries:
                    delay = (2 ** attempt) + random.uniform(0, 0.5)
                    logger.warning(
                        "LLM returned %d (attempt %d/%d); retrying in %.2fs",
                        status, attempt + 1, max_retries, delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                response.raise_for_status()
                return response.json(), None
            except (httpx.HTTPError, ValueError) as exc:
                if attempt < max_retries and _is_retryable(exc):
                    delay = (2 ** attempt) + random.uniform(0, 0.5)
                    logger.warning(
                        "LLM call raised %s (attempt %d/%d); retrying in %.2fs",
                        type(exc).__name__, attempt + 1, max_retries, delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                logger.warning("LLM call failed: %s", exc)
                return None, str(exc)
    return None, "max_retries_exhausted"


def _extract_text_from_body(body: Dict[str, Any], provider: str) -> str:
    """Pull the text content out of a provider-specific response body."""
    if provider == "groq":
        # OpenAI-compatible: choices[0].message.content
        try:
            choices = body.get("choices") or []
            if choices:
                return choices[0].get("message", {}).get("content", "") or ""
        except (AttributeError, TypeError, IndexError):
            pass
        return ""
    # Gemini: candidates[0].content.parts[].text
    try:
        candidates = body.get("candidates") or []
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            return "".join(p.get("text", "") for p in parts)
    except (AttributeError, TypeError, IndexError):
        pass
    return ""


async def call_gemini(
    complaint: str,
    transactions: List[Dict[str, Any]],
    language: Optional[str] = None,
) -> LLMResult:
    """Call the configured LLM provider. Always returns an LLMResult.

    Despite the name (kept for backwards compat with pipeline.py), this
    dispatches to Groq OR Gemini based on env vars.
    """
    if not settings.llm_enabled:
        return LLMResult(used=False, ok=False, error="llm_disabled")

    # Cache hit?
    key = _cache_key(complaint, transactions)
    cached = _LLM_CACHE.get(key)
    if cached is not None:
        logger.info("LLM cache hit for complaint prefix=%r", complaint[:40])
        return cached

    provider = _select_provider()
    if provider is None:
        return LLMResult(used=False, ok=False, error="no_provider_configured")

    timeout = httpx.Timeout(settings.llm_timeout, connect=3.0)
    if provider == "groq":
        body, error = await _call_groq(complaint, transactions, language, timeout)
    else:
        body, error = await _call_gemini(complaint, transactions, language, timeout)

    if body is None:
        return LLMResult(used=True, ok=False, error=error or "unknown")

    text = _extract_text_from_body(body, provider)
    if not text:
        logger.warning("%s response shape unexpected: %s", provider, str(body)[:500])
        return LLMResult(used=True, ok=False, error="bad_response_shape", raw_text=str(body)[:500])

    parsed = _extract_json(text)
    if parsed is None:
        return LLMResult(used=True, ok=False, error="unparseable_json", raw_text=text[:500])

    validated = _validate(parsed)
    if validated is None:
        return LLMResult(used=True, ok=False, error="invalid_enums", raw_text=text[:500])

    validated.raw_text = text[:500]
    # Cache the successful result.
    if len(_LLM_CACHE) >= _LLM_CACHE_MAX:
        _LLM_CACHE.pop(next(iter(_LLM_CACHE)))
    _LLM_CACHE[key] = validated
    return validated
