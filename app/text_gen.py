"""Template-based text generation for agent summary, next action, customer reply.

Per PRD section 12 / 13: the LLM NEVER writes the customer_reply. Templates
interpolate only extracted facts (transaction id, amount, counterparty) --
never raw complaint text. The safety suffix is appended by app.safety.
"""
from __future__ import annotations

from typing import Dict, Optional


def _fmt_amount(amount: Optional[float]) -> str:
    if amount is None:
        return "the transaction amount"
    return f"BDT {amount:,.2f}"


def _txn_ref(txn: Optional[Dict]) -> str:
    if not txn:
        return "N/A"
    return str(txn.get("transaction_id", "N/A"))


def _counterparty(txn: Optional[Dict]) -> str:
    if not txn:
        return "the agent"
    return str(txn.get("counterparty", "the agent"))


_TEMPLATES = {
    "wrong_transfer": {
        "summary": (
            "Customer reports transferring {amount} to the wrong recipient"
            "{txn_clause}. Evidence {verdict_clause}."
        ),
        "next_action": (
            "Verify recipient identity, freeze outgoing leg of transaction {txn_id}, "
            "and escalate to dispute_resolution for reversal eligibility check."
        ),
        "reply": (
            "Thank you for contacting us. We understand you sent {amount} to the wrong "
            "recipient. We have flagged transaction {txn_id} for review by our dispute "
            "team. Any eligible adjustment will be processed through official channels "
            "after verification. We will update you on the outcome."
        ),
    },
    "payment_failed": {
        "summary": (
            "Customer reports {amount} payment {status_clause} but balance was "
            "deducted. Evidence {verdict_clause}."
        ),
        "next_action": (
            "Confirm transaction {txn_id} status with payments switch, initiate "
            "refund trace if money was debited, and update customer within SLA."
        ),
        "reply": (
            "Thank you for reaching out. We see your payment of {amount} "
            "(transaction {txn_id}) is under review. If your balance was deducted, "
            "our payments team will process any eligible adjustment through official "
            "channels within the standard timeline."
        ),
    },
    "refund_request": {
        "summary": (
            "Customer requests a refund of {amount}. Evidence {verdict_clause}."
        ),
        "next_action": (
            "Open refund eligibility check for transaction {txn_id} and respond "
            "to customer with policy-compliant timeline."
        ),
        "reply": (
            "Thank you for contacting us regarding your refund request for "
            "{amount} (transaction {txn_id}). Any eligible adjustment will be "
            "processed through official channels after our review."
        ),
    },
    "duplicate_payment": {
        "summary": (
            "Customer reports being charged {amount} multiple times for the same "
            "payment. Evidence {verdict_clause}."
        ),
        "next_action": (
            "Pull duplicate ledger entries for transaction {txn_id}, identify the "
            "extra leg, and route to payments_ops for reversal."
        ),
        "reply": (
            "Thank you for flagging this. We have detected a possible duplicate "
            "charge for {amount} (transaction {txn_id}). Our payments team will "
            "verify and process any eligible adjustment through official channels."
        ),
    },
    "merchant_settlement_delay": {
        "summary": (
            "Merchant reports settlement of {amount} is delayed. Evidence "
            "{verdict_clause}."
        ),
        "next_action": (
            "Check settlement batch status for transaction {txn_id}, escalate to "
            "merchant_operations if pending beyond SLA."
        ),
        "reply": (
            "Thank you for your patience. We are checking the settlement status "
            "for {amount} (transaction {txn_id}). Our merchant operations team will "
            "update you shortly with the confirmed timeline."
        ),
    },
    "agent_cash_in_issue": {
        "summary": (
            "Customer reports an agent cash-in of {amount} not reflected in "
            "balance. Evidence {verdict_clause}."
        ),
        "next_action": (
            "Contact agent {counterparty}, reconcile ledger entry for transaction "
            "{txn_id}, and escalate to agent_operations."
        ),
        "reply": (
            "Thank you for letting us know. We have flagged the agent cash-in of "
            "{amount} (transaction {txn_id}) for reconciliation. Our agent "
            "operations team will verify and process any eligible adjustment "
            "through official channels."
        ),
    },
    "phishing_or_social_engineering": {
        "summary": (
            "Customer appears to have been contacted by a fraudster requesting "
            "sensitive credentials. This is a critical fraud-risk case."
        ),
        "next_action": (
            "Immediately escalate to fraud_risk, advise customer to secure their "
            "account, and block any further outbound transactions pending review."
        ),
        "reply": (
            "Thank you for reporting this. We take fraud very seriously. Our "
            "fraud-risk team will contact you through official channels only and "
            "guide you on securing your account."
        ),
    },
    "other": {
        "summary": (
            "Customer complaint does not match a standard category. Evidence "
            "{verdict_clause}."
        ),
        "next_action": (
            "Route to customer_support for manual triage and follow-up with "
            "customer."
        ),
        "reply": (
            "Thank you for contacting us. We have received your message and our "
            "support team will review your case and respond through official "
            "channels."
        ),
    },
}


def _verdict_phrase(verdict_label: str) -> str:
    return {
        "consistent": "matches the transaction data",
        "inconsistent": "contradicts the transaction data",
        "insufficient_data": "could not be confirmed against available data",
    }.get(verdict_label, "is inconclusive")


def _status_phrase(status: Optional[str]) -> str:
    if not status:
        return "attempted"
    return {
        "completed": "marked as completed",
        "failed": "marked as failed",
        "pending": "still pending",
        "reversed": "already reversed",
    }.get(status, status)


def render_text(
    case_type: str,
    clues,
    matched_txn: Optional[Dict],
    verdict_label: str,
) -> Dict[str, str]:
    template = _TEMPLATES.get(case_type, _TEMPLATES["other"])
    amount = getattr(clues, "amount", None)
    if amount is None and matched_txn is not None:
        amount = matched_txn.get("amount")
    txn_id = _txn_ref(matched_txn)
    counterparty = _counterparty(matched_txn)

    amount_str = _fmt_amount(amount)
    verdict_clause = _verdict_phrase(verdict_label)
    status_clause = _status_phrase((matched_txn or {}).get("status"))
    txn_clause = f" (transaction {txn_id})" if matched_txn else ""

    def _fill(text: str) -> str:
        return text.format(
            amount=amount_str,
            txn_id=txn_id,
            counterparty=counterparty,
            verdict_clause=verdict_clause,
            status_clause=status_clause,
            txn_clause=txn_clause,
        )

    return {
        "agent_summary": _fill(template["summary"]),
        "recommended_next_action": _fill(template["next_action"]),
        "customer_reply": _fill(template["reply"]),
    }
