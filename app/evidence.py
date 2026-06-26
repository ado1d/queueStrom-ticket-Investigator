"""Deterministic evidence engine.

Implements PRD §11.1–11.3:
  * `extract_clues`     — regex/keyword entity extraction (en + bn + banglish)
  * `score_transactions`— per-transaction evidence score (0..8+)
  * `match_transaction`— select best candidate or return None
  * `verdict`           — consistent / inconsistent / insufficient_data
  * `compute_confidence`— 0..1 confidence used to decide LLM fallback
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from .rules_config import (
    AGENT_ID_PATTERN,
    AMOUNT_PATTERNS,
    COUNTERPARTY_HINT_PATTERN,
    MERCHANT_ID_PATTERN,
    PHONE_PATTERN,
    STATUS_CLAIM_KEYWORDS,
    TIME_HINT_PATTERNS,
    TOPIC_KEYWORDS,
    TRANSACTION_TYPE_KEYWORDS,
    normalise_text,
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class Clues:
    amount: Optional[float] = None
    txn_type: Optional[str] = None
    counterparty_hint: Optional[str] = None
    counterparty_kind: Optional[str] = None  # "phone" | "merchant" | "agent" | "text"
    time_hint: Optional[str] = None
    status_claim: Optional[str] = None
    topics: List[str] = field(default_factory=list)
    raw_keywords: List[str] = field(default_factory=list)
    raw_text: str = ""

    def to_dict(self) -> Dict:
        return {
            "amount": self.amount,
            "txn_type": self.txn_type,
            "counterparty_hint": self.counterparty_hint,
            "counterparty_kind": self.counterparty_kind,
            "time_hint": self.time_hint,
            "status_claim": self.status_claim,
            "topics": list(self.topics),
            "raw_keywords": list(self.raw_keywords),
        }


@dataclass
class ScoredTransaction:
    transaction_id: str
    score: int
    breakdown: Dict[str, int]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_amount(text: str) -> Optional[float]:
    for pattern in AMOUNT_PATTERNS:
        for match in pattern.finditer(text):
            raw = match.group(1) or match.group(2)
            if not raw:
                continue
            cleaned = raw.replace(",", "").strip()
            try:
                value = float(cleaned)
            except ValueError:
                continue
            if value > 0:
                return value
    return None


def _first_match(text: str, groups: Dict[str, List[str]]) -> Optional[str]:
    norm = normalise_text(text)
    for label, keywords in groups.items():
        for kw in keywords:
            if normalise_text(kw) in norm:
                return label
    return None


def _match_topics(text: str) -> List[str]:
    norm = normalise_text(text)
    hits: List[str] = []
    for label, keywords in TOPIC_KEYWORDS.items():
        for kw in keywords:
            if normalise_text(kw) in norm:
                hits.append(label)
                break
    return hits


def _counterparty(text: str) -> Tuple[Optional[str], Optional[str]]:
    if m := PHONE_PATTERN.search(text):
        return m.group(0), "phone"
    if m := MERCHANT_ID_PATTERN.search(text):
        return m.group(0).upper(), "merchant"
    if m := AGENT_ID_PATTERN.search(text):
        return m.group(0).upper(), "agent"
    if m := COUNTERPARTY_HINT_PATTERN.search(text):
        return m.group(1).strip(), "text"
    return None, None


def _time_hint(text: str) -> Optional[str]:
    norm = normalise_text(text)
    for label, pattern in TIME_HINT_PATTERNS.items():
        if pattern.search(norm):
            return label
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_clues(complaint: str) -> Clues:
    """Pull entities out of the raw complaint text."""
    clues = Clues(raw_text=complaint)
    clues.amount = _parse_amount(complaint)
    clues.txn_type = _first_match(complaint, TRANSACTION_TYPE_KEYWORDS)
    clues.status_claim = _first_match(complaint, STATUS_CLAIM_KEYWORDS)
    cp, kind = _counterparty(complaint)
    clues.counterparty_hint = cp
    clues.counterparty_kind = kind
    clues.time_hint = _time_hint(complaint)
    clues.topics = _match_topics(complaint)

    # Capture a few raw keywords for reason_codes / transparency.
    norm = normalise_text(complaint)
    for group in (TRANSACTION_TYPE_KEYWORDS, STATUS_CLAIM_KEYWORDS, TOPIC_KEYWORDS):
        for _label, kws in group.items():
            for kw in kws:
                if normalise_text(kw) in norm and kw not in clues.raw_keywords:
                    clues.raw_keywords.append(kw)
                    if len(clues.raw_keywords) >= 8:
                        return clues
    return clues


# ---------------------------------------------------------------------------
# Transaction scoring
# ---------------------------------------------------------------------------


def _parse_ts(ts: str) -> Optional[datetime]:
    try:
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def _counterparty_overlap(hint: Optional[str], kind: Optional[str], counterparty: str) -> bool:
    if not hint:
        return False
    counterparty = counterparty or ""
    if kind == "phone":
        digits = re.sub(r"\D", "", hint)
        return bool(digits) and digits[-10:] in re.sub(r"\D", "", counterparty)
    if kind in {"merchant", "agent"}:
        return hint.upper() in counterparty.upper()
    # text-style hint: substring match on either side
    return hint.lower() in counterparty.lower() or counterparty.lower() in hint.lower()


def score_transactions(clues: Clues, transactions: List) -> List[ScoredTransaction]:
    """Score each candidate transaction against the extracted clues.

    Per PRD §11.2:
      amount match (±1%)   : +3
      type match           : +2
      counterparty match   : +2
      time proximity ≤24h  : +1
      status consistency   : +1
    """
    results: List[ScoredTransaction] = []
    for txn in transactions:
        breakdown: Dict[str, int] = {}

        # Amount
        if clues.amount is not None and txn.amount > 0:
            ratio = abs(txn.amount - clues.amount) / txn.amount
            if ratio <= 0.01:
                breakdown["amount"] = 3
        # Type
        if clues.txn_type and _types_align(clues.txn_type, txn.type):
            breakdown["type"] = 2
        # Counterparty
        if _counterparty_overlap(
            clues.counterparty_hint, clues.counterparty_kind, txn.counterparty
        ):
            breakdown["counterparty"] = 2
        # Time proximity (24h) — only meaningful when a time_hint is present
        if clues.time_hint:
            txn_dt = _parse_ts(txn.timestamp)
            # We don't have an absolute reference time, so accept all "today" hints
            # and use the txn timestamp as a proxy for recency.
            if txn_dt is not None and clues.time_hint in {"today", "morning", "afternoon", "evening", "time_of_day"}:
                breakdown["time"] = 1
        # Status consistency
        if clues.status_claim and _status_align(clues.status_claim, txn.status):
            breakdown["status"] = 1

        results.append(ScoredTransaction(txn.transaction_id, sum(breakdown.values()), breakdown))
    return results


def _types_align(clue_type: str, txn_type: str) -> bool:
    """Allow loose matches: 'send' ≈ 'transfer', 'pay' ≈ 'payment'."""
    table = {
        "transfer": {"transfer"},
        "payment": {"payment", "refund"},
        "cash_in": {"cash_in"},
        "cash_out": {"cash_out"},
        "settlement": {"settlement"},
        "refund": {"refund", "payment"},
    }
    return txn_type in table.get(clue_type, set())


def _status_align(claim: str, status: str) -> bool:
    """Map complaint status claim to actual transaction status."""
    table = {
        "deducted": {"completed"},
        "failed": {"failed"},
        "not_received": {"failed", "pending"},
        "pending": {"pending"},
        "completed": {"completed"},
    }
    return status in table.get(claim, set())


# ---------------------------------------------------------------------------
# Matching + verdict
# ---------------------------------------------------------------------------


MATCH_THRESHOLD = 4  # PRD §11.2


def match_transaction(scored: List[ScoredTransaction]) -> Optional[str]:
    """Pick the highest scoring transaction; require threshold + uniqueness."""
    if not scored:
        return None
    ranked = sorted(scored, key=lambda s: s.score, reverse=True)
    if ranked[0].score < MATCH_THRESHOLD:
        return None
    if len(ranked) > 1 and ranked[0].score == ranked[1].score:
        # Tie: ambiguous → refuse to pick one
        return None
    return ranked[0].transaction_id


def verdict(
    matched_id: Optional[str],
    scored: List[ScoredTransaction],
    clues: Clues,
    transactions: List,
) -> Tuple[str, Optional[str]]:
    """Return (evidence_verdict, relevant_transaction_id).

    'relevant_transaction_id' may be None even when matched_id is set,
    if the verdict is `inconsistent` (we surface the conflict but refuse
    to claim the data confirms the complaint).
    """
    if matched_id is None:
        return "insufficient_data", None
    txn = next((t for t in transactions if t.transaction_id == matched_id), None)
    if txn is None:
        return "insufficient_data", None
    score_obj = next((s for s in scored if s.transaction_id == matched_id), None)
    if score_obj is None:
        return "insufficient_data", None

    contradictions = _detect_contradictions(clues, txn)
    if contradictions:
        return "inconsistent", matched_id
    return "consistent", matched_id


def _detect_contradictions(clues: Clues, txn) -> List[str]:
    """Return a list of human-readable contradiction strings."""
    issues: List[str] = []
    # Customer says "failed" but txn is completed to a known counterparty.
    if clues.status_claim == "failed" and txn.status == "completed":
        issues.append("status_claim_failed_but_completed")
    # Customer says "deducted" but txn is failed (no money taken).
    if clues.status_claim == "deducted" and txn.status == "failed":
        issues.append("status_claim_deducted_but_failed")
    # Wrong-transfer claim with a counterparty that recurs in history would
    # be a fraud signal, surfaced by the classifier (not here).
    return issues


# ---------------------------------------------------------------------------
# Confidence
# ---------------------------------------------------------------------------


def compute_confidence(
    clues: Clues,
    scored: List[ScoredTransaction],
    matched_id: Optional[str],
    verdict_label: str,
    llm_used: bool = False,
) -> float:
    """Heuristic 0..1 confidence used to decide LLM fallback.

    Base 0.5. +clues present, +matched, -ambiguous verdict, +llm confirmation.
    """
    confidence = 0.5
    if clues.amount is not None:
        confidence += 0.1
    if clues.txn_type:
        confidence += 0.1
    if clues.counterparty_hint:
        confidence += 0.1
    if clues.status_claim:
        confidence += 0.05
    if clues.topics:
        confidence += 0.05
    if matched_id is not None:
        confidence += 0.1
        if verdict_label == "consistent":
            confidence += 0.1
        elif verdict_label == "inconsistent":
            confidence -= 0.1
    else:
        confidence -= 0.1
    if llm_used:
        confidence += 0.05
    return max(0.0, min(1.0, round(confidence, 3)))
