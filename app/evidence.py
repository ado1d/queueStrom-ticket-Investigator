"""Rules-first evidence extraction and deterministic transaction matching."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import math
import re
from collections import Counter
from typing import Iterable

from app.rules_config import (
    AMBIGUITY_MARGIN,
    BENGALI_DIGITS,
    DUPLICATE_WINDOW_SECONDS,
    MATCH_MINIMUM,
    TOPIC_KEYWORDS,
)
from app.schemas import AnalyzeTicketRequest, EvidenceVerdict, Transaction, TransactionStatus, TransactionType


@dataclass(slots=True)
class Clues:
    normalized_text: str
    topics: set[str] = field(default_factory=set)
    amounts: list[float] = field(default_factory=list)
    explicit_transaction_ids: set[str] = field(default_factory=set)
    phone_numbers: set[str] = field(default_factory=set)
    mentioned_hour: int | None = None
    likely_types: set[TransactionType] = field(default_factory=set)

    @property
    def has_specific_reference(self) -> bool:
        return bool(self.amounts or self.explicit_transaction_ids or self.phone_numbers)


@dataclass(slots=True)
class Candidate:
    transaction: Transaction
    score: float
    reason_codes: list[str]


@dataclass(slots=True)
class EvidenceResult:
    clues: Clues
    relevant_transaction: Transaction | None
    verdict: EvidenceVerdict
    confidence: float
    reason_codes: list[str]
    ambiguous: bool = False
    duplicate_pair: tuple[Transaction, Transaction] | None = None
    score_breakdown: dict[str, float] = field(default_factory=dict)


_AMOUNT_RE = re.compile(
    r"(?<![A-Z0-9-])(?:bdt|tk|taka|টাকা|টাকার)?\s*([0-9][0-9,]*(?:\.\d+)?)\s*(?:bdt|tk|taka|টাকা|টাকার)?",
    re.I,
)
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?880|0)1\d{9}(?!\d)")
_TIME_RE = re.compile(r"\b(?:around\s*)?(1[0-2]|0?[1-9])\s*(?:[:.]\d{2})?\s*(am|pm)\b", re.I)
_BN_TIME_RE = re.compile(r"(?:সকাল|দুপুর|বিকেল|রাত)\s*(\d{1,2})")


def normalize_digits(text: str) -> str:
    return text.translate(BENGALI_DIGITS)


def normalize_phone(value: str) -> str:
    digits = re.sub(r"\D", "", normalize_digits(value))
    if digits.startswith("880") and len(digits) == 13:
        return "0" + digits[3:]
    return digits


def _contains_any(text: str, phrases: Iterable[str]) -> bool:
    return any(phrase.lower() in text for phrase in phrases)


def _extract_amounts(text: str) -> list[float]:
    amounts: list[float] = []
    for match in _AMOUNT_RE.finditer(text):
        raw = match.group(1).replace(",", "")
        try:
            value = float(raw)
        except ValueError:
            continue
        # Ignore very short numeric fragments normally found in references such as
        # ticket labels.  Transaction values in the challenge are positive BDT.
        if 1 <= value <= 1_000_000_000:
            amounts.append(value)
    # Stable de-duplication preserves complaint order.
    return list(dict.fromkeys(amounts))


def _extract_hour(text: str) -> int | None:
    match = _TIME_RE.search(text)
    if match:
        hour = int(match.group(1))
        meridiem = match.group(2).lower()
        if meridiem == "pm" and hour != 12:
            hour += 12
        if meridiem == "am" and hour == 12:
            hour = 0
        return hour

    bn = _BN_TIME_RE.search(text)
    if not bn:
        return None
    hour = int(bn.group(1))
    prefix = bn.group(0)
    if "দুপুর" in prefix or "বিকেল" in prefix or "রাত" in prefix:
        if hour < 12:
            hour += 12
    return hour % 24


def _infer_likely_types(topics: set[str]) -> set[TransactionType]:
    types: set[TransactionType] = set()
    if {"wrong_transfer", "transfer_nonreceipt", "transfer"} & topics:
        types.add(TransactionType.transfer)
    if {"payment_failed", "duplicate_payment", "payment"} & topics:
        types.add(TransactionType.payment)
    if "refund_request" in topics:
        types.update({TransactionType.payment, TransactionType.refund})
    if "agent_cash_in" in topics:
        types.add(TransactionType.cash_in)
    if "merchant_settlement" in topics:
        types.add(TransactionType.settlement)
    return types


def extract_clues(complaint: str, history: list[Transaction]) -> Clues:
    normalized = normalize_digits(complaint).lower()
    topics = {name for name, words in TOPIC_KEYWORDS.items() if _contains_any(normalized, words)}
    history_ids = {txn.transaction_id.lower() for txn in history}
    explicit_ids = {txn_id for txn_id in history_ids if txn_id in normalized}
    phones = {normalize_phone(item) for item in _PHONE_RE.findall(normalized)}

    # A generic TXN reference that is not in history is still useful for deciding
    # that the history is insufficient, but cannot be selected as relevant.
    generic_ids = re.findall(r"\btxn[-_\s]?\d+[a-z0-9_-]*\b", normalized, flags=re.I)
    explicit_ids.update(item.lower() for item in generic_ids if item.lower() in history_ids)

    return Clues(
        normalized_text=normalized,
        topics=topics,
        amounts=_extract_amounts(normalized),
        explicit_transaction_ids=explicit_ids,
        phone_numbers=phones,
        mentioned_hour=_extract_hour(normalized),
        likely_types=_infer_likely_types(topics),
    )


def _amount_matches(amount: float, target: float) -> bool:
    return math.isclose(amount, target, rel_tol=0.0, abs_tol=0.01)


def _hour_distance(one: int, two: int) -> int:
    return min(abs(one - two), 24 - abs(one - two))


def _score_transaction(txn: Transaction, clues: Clues) -> Candidate:
    score = 0.0
    reasons: list[str] = []
    txn_id = txn.transaction_id.lower()

    if txn_id in clues.explicit_transaction_ids:
        score += 0.85
        reasons.append("transaction_id_match")

    if clues.amounts:
        if any(_amount_matches(txn.amount, amount) for amount in clues.amounts):
            score += 0.45
            reasons.append("amount_match")
        else:
            # An explicit but contradictory amount makes selection less likely.
            score -= 0.18

    if clues.likely_types:
        if txn.type in clues.likely_types:
            score += 0.25
            reasons.append("transaction_type_match")
        else:
            score -= 0.08

    if clues.phone_numbers and normalize_phone(txn.counterparty) in clues.phone_numbers:
        score += 0.35
        reasons.append("counterparty_match")

    if clues.mentioned_hour is not None:
        difference = _hour_distance(txn.timestamp.hour, clues.mentioned_hour)
        if difference <= 1:
            score += 0.12
            reasons.append("time_match")

    if "payment_failed" in clues.topics and txn.type == TransactionType.payment:
        if txn.status == TransactionStatus.failed:
            score += 0.20
            reasons.append("failed_status_match")
        elif txn.status == TransactionStatus.completed:
            score -= 0.12

    if "agent_cash_in" in clues.topics and txn.type == TransactionType.cash_in:
        if txn.status == TransactionStatus.pending:
            score += 0.16
            reasons.append("pending_status_match")

    if "merchant_settlement" in clues.topics and txn.type == TransactionType.settlement:
        if txn.status == TransactionStatus.pending:
            score += 0.16
            reasons.append("pending_status_match")

    # A strictly topic-free complaint should not select a random recent item.
    if not clues.has_specific_reference and not clues.likely_types:
        score = 0.0
        reasons.clear()

    return Candidate(transaction=txn, score=max(0.0, min(score, 1.0)), reason_codes=reasons)


def find_duplicate_pair(history: list[Transaction]) -> tuple[Transaction, Transaction] | None:
    """Return the later member of a strong duplicate-payment pair when present."""
    payments = sorted((t for t in history if t.type == TransactionType.payment), key=lambda item: item.timestamp)
    for index, first in enumerate(payments):
        for second in payments[index + 1:]:
            seconds = (second.timestamp - first.timestamp).total_seconds()
            if seconds > DUPLICATE_WINDOW_SECONDS:
                break
            if (
                _amount_matches(first.amount, second.amount)
                and first.counterparty.strip().lower() == second.counterparty.strip().lower()
                and first.status == TransactionStatus.completed
                and second.status == TransactionStatus.completed
            ):
                return first, second
    return None


def _has_established_recipient_pattern(txn: Transaction, history: list[Transaction]) -> bool:
    same_recipient_transfers = [
        item
        for item in history
        if item.type == TransactionType.transfer
        and normalize_phone(item.counterparty) == normalize_phone(txn.counterparty)
        and item.status == TransactionStatus.completed
    ]
    return len(same_recipient_transfers) >= 2


def _calculate_confidence(
    *,
    topics: set[str],
    verdict: EvidenceVerdict,
    transaction: Transaction | None,
    ambiguous: bool,
    duplicate_pair: tuple[Transaction, Transaction] | None,
) -> float:
    if "phishing" in topics:
        return 0.95
    if ambiguous:
        return 0.65
    if transaction is None:
        return 0.60
    if verdict == EvidenceVerdict.inconsistent:
        return 0.75
    if duplicate_pair:
        return 0.93
    if "merchant_settlement" in topics:
        return 0.92
    if "agent_cash_in" in topics:
        return 0.88
    if "payment_failed" in topics:
        return 0.90
    if "refund_request" in topics:
        return 0.85
    if "wrong_transfer" in topics or "transfer_nonreceipt" in topics:
        return 0.90
    return 0.72


def investigate(request: AnalyzeTicketRequest, complaint_for_reasoning: str) -> EvidenceResult:
    """Extract clues, select a transaction, and determine evidence consistency.

    The result is deterministic.  No external service is consulted and no model
    can override a contradiction or an ambiguous transaction match.
    """
    history = request.transaction_history
    clues = extract_clues(complaint_for_reasoning, history)

    # Phishing reports are safety cases.  Transaction history is usually absent
    # and should not force an unrelated selection.
    if "phishing" in clues.topics:
        return EvidenceResult(
            clues=clues,
            relevant_transaction=None,
            verdict=EvidenceVerdict.insufficient_data,
            confidence=0.95,
            reason_codes=["phishing", "credential_protection", "critical_escalation"],
        )

    duplicate_pair = find_duplicate_pair(history)
    if "duplicate_payment" in clues.topics and duplicate_pair is not None:
        first, suspected_duplicate = duplicate_pair
        return EvidenceResult(
            clues=clues,
            relevant_transaction=suspected_duplicate,
            verdict=EvidenceVerdict.consistent,
            confidence=0.93,
            reason_codes=["duplicate_payment", "biller_verification_required"],
            duplicate_pair=(first, suspected_duplicate),
            score_breakdown={"duplicate_pair": 1.0},
        )

    candidates = sorted((_score_transaction(txn, clues) for txn in history), key=lambda item: item.score, reverse=True)
    viable = [candidate for candidate in candidates if candidate.score >= MATCH_MINIMUM]

    if not viable:
        reason = "vague_complaint" if not clues.has_specific_reference else "no_matching_transaction"
        return EvidenceResult(
            clues=clues,
            relevant_transaction=None,
            verdict=EvidenceVerdict.insufficient_data,
            confidence=0.60,
            reason_codes=[reason, "needs_clarification"],
        )

    top = viable[0]
    explicit_or_counterparty_match = (
        "transaction_id_match" in top.reason_codes or "counterparty_match" in top.reason_codes
    )
    ambiguous = (
        len(viable) > 1
        and not explicit_or_counterparty_match
        and abs(viable[0].score - viable[1].score) <= AMBIGUITY_MARGIN
    )
    if ambiguous:
        return EvidenceResult(
            clues=clues,
            relevant_transaction=None,
            verdict=EvidenceVerdict.insufficient_data,
            confidence=0.65,
            reason_codes=["ambiguous_match", "needs_clarification"],
            ambiguous=True,
            score_breakdown={candidate.transaction.transaction_id: round(candidate.score, 3) for candidate in viable[:3]},
        )

    matched = top.transaction
    verdict = EvidenceVerdict.consistent
    reasons = list(top.reason_codes)

    if "wrong_transfer" in clues.topics and _has_established_recipient_pattern(matched, history):
        verdict = EvidenceVerdict.inconsistent
        reasons.extend(["wrong_transfer_claim", "established_recipient_pattern", "evidence_inconsistent"])
    elif "payment_failed" in clues.topics and matched.status != TransactionStatus.failed:
        verdict = EvidenceVerdict.inconsistent
        reasons.append("status_contradiction")
    elif "merchant_settlement" in clues.topics and matched.status == TransactionStatus.completed:
        verdict = EvidenceVerdict.inconsistent
        reasons.append("settlement_marked_completed")
    elif "agent_cash_in" in clues.topics and matched.status == TransactionStatus.completed:
        verdict = EvidenceVerdict.inconsistent
        reasons.append("cash_in_marked_completed")

    # Public-score-friendly explanation codes for the most common paths.
    if "wrong_transfer" in clues.topics and verdict == EvidenceVerdict.consistent:
        reasons.extend(["wrong_transfer", "transaction_match", "dispute_initiated"])
    elif "payment_failed" in clues.topics:
        reasons.extend(["payment_failed", "potential_balance_deduction"])
    elif "refund_request" in clues.topics:
        reasons.extend(["refund_request", "merchant_policy_dependent"])
    elif "agent_cash_in" in clues.topics:
        reasons.extend(["agent_cash_in", "pending_transaction", "agent_ops"])
    elif "merchant_settlement" in clues.topics:
        reasons.extend(["merchant_settlement", "delay", "pending"])
    elif "transfer_nonreceipt" in clues.topics:
        reasons.extend(["transfer_nonreceipt", "transaction_match"])

    # Stable de-duplication keeps the response concise and deterministic.
    reasons = list(dict.fromkeys(reasons))
    confidence = _calculate_confidence(
        topics=clues.topics,
        verdict=verdict,
        transaction=matched,
        ambiguous=False,
        duplicate_pair=duplicate_pair if "duplicate_payment" in clues.topics else None,
    )
    return EvidenceResult(
        clues=clues,
        relevant_transaction=matched,
        verdict=verdict,
        confidence=confidence,
        reason_codes=reasons,
        score_breakdown={candidate.transaction.transaction_id: round(candidate.score, 3) for candidate in candidates[:3]},
    )
