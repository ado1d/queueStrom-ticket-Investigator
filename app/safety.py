"""Safety post-processor for all generated text fields.

Per PRD section 13:
  - Block / redact PIN, OTP, password, secret code, full card numbers, CVC.
  - Rewrite unconditional refund / unblock promises.
  - Strip prompt-injection patterns before interpolation.
  - Append a standard safety suffix to every customer_reply.
"""
from __future__ import annotations

import re
from typing import Dict

from .rules_config import (
    FORBIDDEN_OUTPUT_PHRASES,
    PROMPT_INJECTION_PATTERNS,
)

SAFETY_SUFFIX = (
    "Please do not share your PIN, OTP, or password with anyone. "
    "Our team will never ask for these."
)

REPLACEMENTS = [
    (re.compile(r"\bwe will refund\b", re.IGNORECASE), "any eligible adjustment will be processed"),
    (re.compile(r"\bwe'?ll refund\b", re.IGNORECASE), "any eligible adjustment will be processed"),
    (re.compile(r"\bwe have refunded\b", re.IGNORECASE), "any eligible adjustment has been processed"),
    (re.compile(r"\byour money will be reversed\b", re.IGNORECASE), "any eligible adjustment will be processed"),
    (re.compile(r"\baccount (?:will be )?unblocked\b", re.IGNORECASE), "account access will be reviewed"),
]


def strip_prompt_injection(text: str) -> str:
    """Remove prompt-injection attempts from raw text."""
    cleaned = text or ""
    for pattern in PROMPT_INJECTION_PATTERNS:
        cleaned = pattern.sub(" ", cleaned)
    return cleaned.strip()


def scrub_forbidden(text: str) -> str:
    """Replace forbidden phrases with neutral placeholders.

    REPLACEMENTS (rewrite-to-allowed) run FIRST so phrases like
    "we will refund" become the approved alternative phrasing instead of a
    bare "[redacted]". The blocklist then redactions anything still forbidden.
    """
    cleaned = text or ""
    for pattern, replacement in REPLACEMENTS:
        cleaned = pattern.sub(replacement, cleaned)
    for pattern in FORBIDDEN_OUTPUT_PHRASES:
        cleaned = pattern.sub("[redacted]", cleaned)
    return cleaned


def append_safety_suffix(text: str) -> str:
    """Ensure the standard safety suffix is on the customer reply."""
    suffix = SAFETY_SUFFIX.strip()
    if suffix.lower() in (text or "").lower():
        return (text or "").rstrip()
    separator = " " if not (text or "").endswith((" ", "\n")) else ""
    return f"{(text or '').rstrip()}{separator}{suffix}"


def sanitize_response_fields(fields: Dict[str, str]) -> Dict[str, str]:
    """Sanitize a dict of agent_summary / recommended_next_action / customer_reply."""
    cleaned: Dict[str, str] = {}
    for key, value in fields.items():
        text = strip_prompt_injection(value)
        text = scrub_forbidden(text)
        cleaned[key] = text.strip()
    if "customer_reply" in cleaned:
        cleaned["customer_reply"] = append_safety_suffix(cleaned["customer_reply"])
    return cleaned


def assert_safety(text: str) -> None:
    """Test helper: raise AssertionError if forbidden phrases remain.

    The standard safety suffix is exempted because it intentionally mentions
    PIN / OTP / password as a customer warning — that is allowed content.
    The suffix is anchored on a stable prefix that only appears in the suffix.
    """
    haystack = text or ""
    # Anchor on the start of the safety suffix (unique phrase) and strip from
    # there onwards so PIN / OTP / password mentions in the suffix don't trip.
    suffix_prefix = "Please do not share your PIN"
    cut = haystack.find(suffix_prefix)
    if cut >= 0:
        haystack = haystack[:cut]
    for pattern in FORBIDDEN_OUTPUT_PHRASES:
        if pattern.search(haystack):
            raise AssertionError(
                f"forbidden phrase matched: {pattern.pattern} in {haystack!r}"
            )
    for pattern, _ in REPLACEMENTS:
        if pattern.search(haystack):
            raise AssertionError(
                f"unrewritten forbidden phrase: {pattern.pattern} in {haystack!r}"
            )
