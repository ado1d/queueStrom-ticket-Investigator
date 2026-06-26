"""Deterministic case classification, routing, escalation, and severity policy."""
from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings
from app.evidence import EvidenceResult
from app.rules_config import DEPARTMENT_BY_CASE
from app.schemas import (
    AnalyzeTicketRequest,
    CaseType,
    Department,
    EvidenceVerdict,
    Severity,
    TransactionStatus,
    TransactionType,
)


@dataclass(slots=True)
class Classification:
    case_type: CaseType
    severity: Severity
    department: Department
    human_review_required: bool


def _is_high_value(amount: float | None, settings: Settings) -> bool:
    return amount is not None and amount >= settings.high_value_bdt


def _select_case_type(request: AnalyzeTicketRequest, evidence: EvidenceResult) -> CaseType:
    topics = evidence.clues.topics
    txn = evidence.relevant_transaction

    # Safety-sensitive social engineering is intentionally first and absolute.
    if "phishing" in topics:
        return CaseType.phishing_or_social_engineering
    if "duplicate_payment" in topics or evidence.duplicate_pair is not None:
        return CaseType.duplicate_payment
    if "agent_cash_in" in topics or (txn and txn.type == TransactionType.cash_in and "agent" in topics):
        return CaseType.agent_cash_in_issue
    if "merchant_settlement" in topics or (
        txn and txn.type == TransactionType.settlement and request.user_type and request.user_type.value == "merchant"
    ):
        return CaseType.merchant_settlement_delay
    if "payment_failed" in topics or (txn and txn.type == TransactionType.payment and txn.status == TransactionStatus.failed):
        return CaseType.payment_failed
    # A wrong-recipient or transfer-nonreceipt allegation takes precedence over a
    # generic request to "reverse" or "refund" the same transfer.
    if "wrong_transfer" in topics or "transfer_nonreceipt" in topics:
        return CaseType.wrong_transfer
    if "refund_request" in topics:
        return CaseType.refund_request
    if txn and txn.type == TransactionType.transfer and "transfer" in topics:
        return CaseType.wrong_transfer
    return CaseType.other


def _select_severity(
    case_type: CaseType,
    evidence: EvidenceResult,
    settings: Settings,
) -> Severity:
    txn = evidence.relevant_transaction
    amount = txn.amount if txn else (evidence.clues.amounts[0] if evidence.clues.amounts else None)

    if case_type == CaseType.phishing_or_social_engineering:
        return Severity.critical
    if _is_high_value(amount, settings):
        return Severity.high
    if case_type == CaseType.duplicate_payment:
        return Severity.high
    if case_type == CaseType.agent_cash_in_issue:
        return Severity.high if txn and txn.status == TransactionStatus.pending else Severity.medium
    if case_type == CaseType.payment_failed:
        return Severity.high if txn and txn.status == TransactionStatus.failed else Severity.medium
    if case_type == CaseType.wrong_transfer:
        if evidence.ambiguous or evidence.verdict == EvidenceVerdict.inconsistent:
            return Severity.medium
        return Severity.high if txn is not None else Severity.medium
    if case_type == CaseType.merchant_settlement_delay:
        return Severity.medium
    if case_type == CaseType.refund_request:
        return Severity.low
    return Severity.low


def _requires_human_review(
    case_type: CaseType,
    evidence: EvidenceResult,
    severity: Severity,
    settings: Settings,
) -> bool:
    txn = evidence.relevant_transaction
    amount = txn.amount if txn else (evidence.clues.amounts[0] if evidence.clues.amounts else None)

    if case_type == CaseType.phishing_or_social_engineering:
        return True
    if evidence.verdict == EvidenceVerdict.inconsistent:
        return True
    if _is_high_value(amount, settings):
        return True
    if case_type in {CaseType.duplicate_payment, CaseType.agent_cash_in_issue}:
        return True
    # A confirmed wrong-transfer dispute is escalated.  A low-information,
    # ambiguous transfer instead asks for clarification first (public sample 08).
    if case_type == CaseType.wrong_transfer and txn is not None and not evidence.ambiguous:
        return True
    return False


def classify(request: AnalyzeTicketRequest, evidence: EvidenceResult, settings: Settings) -> Classification:
    case_type = _select_case_type(request, evidence)
    severity = _select_severity(case_type, evidence, settings)
    department = DEPARTMENT_BY_CASE[case_type]
    human_review_required = _requires_human_review(case_type, evidence, severity, settings)
    return Classification(
        case_type=case_type,
        severity=severity,
        department=department,
        human_review_required=human_review_required,
    )
