"""Case classifier + routing decision tree.

Implements PRD section 11.4. Phishing detection runs FIRST so we never
route a scam complaint into the wrong queue. Severity boosts and
human_review rules are centralised here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from .evidence import Clues


@dataclass
class Classification:
    case_type: str
    severity: str
    department: str
    human_review_required: bool
    reason_codes: List[str]

    def to_dict(self) -> Dict:
        return {
            "case_type": self.case_type,
            "severity": self.severity,
            "department": self.department,
            "human_review_required": self.human_review_required,
            "reason_codes": list(self.reason_codes),
        }


_SEVERITY_ORDER = ["low", "medium", "high", "critical"]

# When the LLM overrides the rules-based case_type, look up the canonical
# (severity, department) pair from this table. Keeps the override deterministic.
_LLM_ROUTE: Dict[str, tuple] = {
    "wrong_transfer": ("high", "dispute_resolution"),
    "payment_failed": ("high", "payments_ops"),
    "refund_request": ("low", "customer_support"),
    "duplicate_payment": ("high", "payments_ops"),
    "merchant_settlement_delay": ("medium", "merchant_operations"),
    "agent_cash_in_issue": ("high", "agent_operations"),
    "phishing_or_social_engineering": ("critical", "fraud_risk"),
    "other": ("low", "customer_support"),
}


def _bump_severity(severity: str, levels: int = 1) -> str:
    try:
        idx = _SEVERITY_ORDER.index(severity)
    except ValueError:
        idx = 0
    return _SEVERITY_ORDER[min(idx + levels, len(_SEVERITY_ORDER) - 1)]


def _has_topic(clues: Clues, name: str) -> bool:
    return name in clues.topics


def _has_status_claim(clues: Clues, name: str) -> bool:
    return clues.status_claim == name


def classify(
    clues: Clues,
    verdict_label: str,
    matched_txn: Optional[Dict],
    user_type: Optional[str] = None,
    confidence: float = 1.0,
    llm_case_type: Optional[str] = None,
    request_language: Optional[str] = None,
) -> Classification:
    reason_codes: List[str] = []

    # 0. Phishing wins always.
    if _has_topic(clues, "phishing"):
        reason_codes.append("phishing_keywords")
        reason_codes.append("human_review")
        return Classification(
            case_type="phishing_or_social_engineering",
            severity="critical",
            department="fraud_risk",
            human_review_required=True,
            reason_codes=reason_codes,
        )

    case_type = "other"
    severity = "low"
    department = "customer_support"

    txn_type = (matched_txn or {}).get("type")
    txn_status = (matched_txn or {}).get("status")
    txn_amount = (matched_txn or {}).get("amount") or 0.0

    if matched_txn is not None:
        if txn_type == "transfer":
            if _has_topic(clues, "wrong_number"):
                case_type = "wrong_transfer"
                # Severity depends on verdict: consistent=high, inconsistent=medium
                # (established recipient pattern lowers the urgency).
                if verdict_label == "inconsistent":
                    severity = "medium"
                    reason_codes.append("wrong_transfer_inconsistent")
                else:
                    severity = "high"
                    reason_codes.append("wrong_transfer")
                department = "dispute_resolution"
            elif _has_topic(clues, "refund"):
                case_type = "refund_request"
                severity = "low"
                department = "customer_support"
                reason_codes.append("refund_request")
            else:
                # Transfer with no specific topic: customer mentions a transfer
                # but doesn't say it's wrong. Treat as wrong_transfer if they
                # also claim non-receipt; otherwise generic refund_request.
                if _has_status_claim(clues, "not_received"):
                    case_type = "wrong_transfer"
                    severity = "medium"
                    department = "dispute_resolution"
                    reason_codes.append("transfer_not_received")
                else:
                    case_type = "refund_request"
                    severity = "low"
                    department = "customer_support"
                    reason_codes.append("generic_transfer")

        elif txn_type == "payment":
            # Refund request on a completed payment (change-of-mind) takes
            # priority over the default payment_failed routing.
            if _has_topic(clues, "refund") and txn_status == "completed":
                case_type = "refund_request"
                severity = "low"
                department = "customer_support"
                reason_codes.append("refund_request_completed_payment")
            elif _has_topic(clues, "duplicate"):
                case_type = "duplicate_payment"
                severity = "high"
                department = "payments_ops"
                reason_codes.append("duplicate_payment")
            elif txn_status in {"failed", "pending"} or _has_status_claim(clues, "deducted"):
                case_type = "payment_failed"
                severity = "high"
                department = "payments_ops"
                reason_codes.append("payment_failed")
            elif _has_topic(clues, "settlement"):
                case_type = "merchant_settlement_delay"
                severity = "medium"
                department = "merchant_operations"
                reason_codes.append("settlement_delay")
            else:
                case_type = "payment_failed"
                severity = "high"
                department = "payments_ops"
                reason_codes.append("payment_review")

        elif txn_type == "cash_in":
            if _has_topic(clues, "agent_cash_in") or _has_status_claim(clues, "not_received"):
                case_type = "agent_cash_in_issue"
                severity = "high"
                department = "agent_operations"
                reason_codes.append("agent_cash_in")
            else:
                case_type = "agent_cash_in_issue"
                severity = "medium"
                department = "agent_operations"
                reason_codes.append("cash_in_review")

        elif txn_type == "settlement":
            case_type = "merchant_settlement_delay"
            severity = "medium"
            department = "merchant_operations"
            reason_codes.append("settlement_delay")

        elif txn_type == "refund":
            case_type = "refund_request"
            severity = "low"
            department = "customer_support"
            reason_codes.append("refund_txn")

        elif txn_type == "cash_out":
            case_type = "other"
            severity = "low"
            department = "customer_support"
            reason_codes.append("cash_out_review")

    else:
        # No matched transaction. If the complaint mentions a transfer and
        # ambiguous multiple txns exist, route to wrong_transfer at medium
        # severity (need customer clarification, not a hard dispute).
        if _has_topic(clues, "wrong_number"):
            case_type = "wrong_transfer"
            severity = "medium"  # no match → ambiguous → don't auto-escalate
            department = "dispute_resolution"
            reason_codes.append("wrong_transfer_no_match")
        elif clues.txn_type == "transfer" and _has_status_claim(clues, "not_received"):
            # 'I sent to my brother but he didn't get it' with multiple matches
            case_type = "wrong_transfer"
            severity = "medium"
            department = "dispute_resolution"
            reason_codes.append("transfer_ambiguous_no_match")
        elif _has_topic(clues, "refund"):
            case_type = "refund_request"
            severity = "low"
            department = "customer_support"
            reason_codes.append("refund_request_no_match")
        elif _has_topic(clues, "duplicate"):
            case_type = "duplicate_payment"
            severity = "high"
            department = "payments_ops"
            reason_codes.append("duplicate_no_match")
        elif _has_topic(clues, "settlement"):
            case_type = "merchant_settlement_delay"
            severity = "medium"
            department = "merchant_operations"
            reason_codes.append("settlement_no_match")
        elif _has_topic(clues, "agent_cash_in"):
            case_type = "agent_cash_in_issue"
            severity = "high"
            department = "agent_operations"
            reason_codes.append("agent_cash_in_no_match")
        elif _has_status_claim(clues, "deducted") or _has_status_claim(clues, "failed"):
            case_type = "payment_failed"
            severity = "high"
            department = "payments_ops"
            reason_codes.append("status_claim_no_match")
        else:
            case_type = "other"
            severity = "low"
            department = "customer_support"
            reason_codes.append("no_match")

    if txn_amount and txn_amount > 50_000 and severity != "critical":
        severity = _bump_severity(severity, 1)
        reason_codes.append("severity_boost_high_value")
    if user_type == "merchant" and case_type == "merchant_settlement_delay" and severity == "low":
        severity = "medium"
        reason_codes.append("severity_boost_merchant")

    # LLM override: only trust it when the rules fell back to a generic bucket
    # (refund_request / other) OR when the LLM is more specific than the rules
    # (e.g. "wrong_transfer" beats a generic transfer verdict). We never let
    # the LLM downgrade a rules-detected critical/high-risk case.
    _HIGH_RISK = {"wrong_transfer", "phishing_or_social_engineering", "duplicate_payment"}
    if llm_case_type and llm_case_type != case_type:
        if case_type in {"other", "refund_request"} or (
            case_type not in _HIGH_RISK and llm_case_type in _HIGH_RISK
        ):
            new_severity, new_department = _LLM_ROUTE.get(
                llm_case_type, (severity, department)
            )
            case_type = llm_case_type
            severity = new_severity
            department = new_department
            reason_codes.append(f"llm_override_to_{llm_case_type}")

    human_review = False
    if severity == "critical":
        human_review = True
        reason_codes.append("human_review_critical")
    elif severity == "high" and verdict_label != "consistent":
        human_review = True
        reason_codes.append("human_review_high_uncertain")
    if verdict_label == "inconsistent":
        human_review = True
        reason_codes.append("human_review_inconsistent")
    # Duplicate payments are a financial event — always require human review
    # before any reversal is initiated.
    if case_type == "duplicate_payment":
        human_review = True
        reason_codes.append("human_review_duplicate_payment")
    # Wrong-transfer with a MATCHED transaction is a high-impact financial
    # event — always require human reviewer to authorise any reversal.
    # BUT when matched_txn is None (ambiguous, need clarification), do NOT
    # force review — just ask the customer for the disambiguating detail.
    if case_type == "wrong_transfer" and matched_txn is not None:
        human_review = True
        reason_codes.append("human_review_wrong_transfer")
    # Agent cash-in issues where the customer claims non-receipt are
    # high-stakes (money missing). Always require human review.
    if case_type == "agent_cash_in_issue" and _has_status_claim(clues, "not_received"):
        human_review = True
        reason_codes.append("human_review_agent_cash_in_non_receipt")
    # Low-confidence cases warrant human review ONLY when we actually have
    # a transaction context. A vague 'other' complaint with no clues should
    # just get a clarification reply, not a human-reviewer queue entry.
    if confidence < 0.7 and case_type != "other" and matched_txn is not None:
        human_review = True
        reason_codes.append("human_review_low_confidence")

    return Classification(
        case_type=case_type,
        severity=severity,
        department=department,
        human_review_required=human_review,
        reason_codes=reason_codes,
    )
