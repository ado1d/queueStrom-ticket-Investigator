"""Verified-facts-only template generation for agent and customer text."""
from __future__ import annotations

from app.classifier import Classification
from app.evidence import EvidenceResult
from app.safety import is_bangla
from app.schemas import AnalyzeTicketRequest, CaseType, EvidenceVerdict


def _format_amount(amount: float | None) -> str:
    if amount is None:
        return "the reported amount"
    if float(amount).is_integer():
        return f"{int(amount):,} BDT"
    return f"{amount:,.2f} BDT"


def _summary(request: AnalyzeTicketRequest, evidence: EvidenceResult, decision: Classification) -> str:
    txn = evidence.relevant_transaction
    amount = _format_amount(txn.amount if txn else (evidence.clues.amounts[0] if evidence.clues.amounts else None))

    if decision.case_type == CaseType.phishing_or_social_engineering:
        return "Customer reports a suspected social-engineering attempt involving account credentials. No specific transaction can be verified from the supplied history."
    if evidence.ambiguous:
        count = len(request.transaction_history)
        return f"Customer reports a transfer concern involving {amount}, but multiple plausible transactions exist in the supplied history ({count} records). A single transaction cannot be identified safely."
    if txn is None:
        return "Customer reports a concern without enough specific transaction details to identify a relevant record in the supplied history."

    if decision.case_type == CaseType.wrong_transfer:
        if evidence.verdict == EvidenceVerdict.inconsistent:
            return f"Customer claims {amount} transfer {txn.transaction_id} was sent to the wrong recipient, but the transaction history shows an established completed-transfer pattern to the same counterparty."
        return f"Customer reports a possible wrong-recipient transfer of {amount} linked to {txn.transaction_id}. Available transaction data matches the reported amount and transfer context."
    if decision.case_type == CaseType.payment_failed:
        return f"Customer reports a failed payment of {amount} linked to {txn.transaction_id}. The recorded payment status is {txn.status.value}."
    if decision.case_type == CaseType.refund_request:
        return f"Customer requests a refund review for payment {txn.transaction_id} of {amount}. The transaction is recorded as {txn.status.value}."
    if decision.case_type == CaseType.duplicate_payment:
        first = evidence.duplicate_pair[0].transaction_id if evidence.duplicate_pair else "an earlier payment"
        return f"Customer reports a possible duplicate payment. {first} and {txn.transaction_id} are matching completed payments of {amount} to the same counterparty within a short interval."
    if decision.case_type == CaseType.agent_cash_in_issue:
        return f"Customer reports that cash-in {txn.transaction_id} of {amount} via {txn.counterparty} is not reflected in the balance. The transaction status is {txn.status.value}."
    if decision.case_type == CaseType.merchant_settlement_delay:
        return f"Merchant reports delayed settlement {txn.transaction_id} of {amount}. The supplied settlement record is {txn.status.value}."
    return f"Customer concern references transaction {txn.transaction_id} of {amount}. Additional review is required to determine the appropriate resolution."


def _next_action(evidence: EvidenceResult, decision: Classification) -> str:
    txn = evidence.relevant_transaction
    txn_id = txn.transaction_id if txn else None

    if decision.case_type == CaseType.phishing_or_social_engineering:
        return "Route the report to fraud_risk for review, preserve the reported channel details, and remind the customer to use only official support channels."
    if evidence.ambiguous:
        return "Ask the customer for a non-sensitive disambiguating detail, such as the recipient number or transaction ID, before creating a dispute workflow."
    if txn_id is None:
        return "Request non-sensitive transaction details, including transaction ID, amount, approximate time, and the issue observed; do not request security credentials."
    if decision.case_type == CaseType.wrong_transfer:
        return f"Route {txn_id} to dispute_resolution to verify the recipient and transaction context under the applicable dispute policy; do not promise an outcome."
    if decision.case_type == CaseType.payment_failed:
        return f"Route {txn_id} to payments_ops to verify the payment status and balance impact. Any eligible adjustment must follow the standard review workflow."
    if decision.case_type == CaseType.refund_request:
        return f"Review {txn_id} against the merchant and refund policy, then communicate only the approved outcome through official channels."
    if decision.case_type == CaseType.duplicate_payment:
        return f"Route {txn_id} to payments_ops to verify the duplicate indicator with the biller before any eligible adjustment is processed."
    if decision.case_type == CaseType.agent_cash_in_issue:
        return f"Route {txn_id} to agent_operations to verify agent-side submission and settlement state within the cash-in SLA."
    if decision.case_type == CaseType.merchant_settlement_delay:
        return f"Route {txn_id} to merchant_operations to verify the settlement batch status and provide a policy-approved ETA through official channels."
    return "Collect non-sensitive transaction details and route the case to customer_support for review."


def _english_reply(evidence: EvidenceResult, decision: Classification) -> str:
    txn = evidence.relevant_transaction
    txn_id = txn.transaction_id if txn else None

    if decision.case_type == CaseType.phishing_or_social_engineering:
        return "Thank you for reporting this suspicious contact. Please stop engaging with the caller or message and use only official support channels. Our fraud risk team will review your report."
    if evidence.ambiguous:
        return "Thank you for reaching out. We found more than one possible transaction in the supplied details. Please share the recipient number or transaction ID through an official channel so we can identify the correct record."
    if txn_id is None:
        return "Thank you for reaching out. To help us investigate, please share the transaction ID, amount, approximate time, and a short description of what went wrong through an official channel."
    if decision.case_type == CaseType.wrong_transfer:
        return f"We have noted your concern about transaction {txn_id}. Our dispute team will review the available details under the applicable policy. We cannot confirm the outcome until the review is complete."
    if decision.case_type == CaseType.payment_failed:
        return f"We have noted the failed-payment concern for transaction {txn_id}. Our payments team will verify the transaction status and balance impact. Any eligible amount, if approved, will be returned through official channels."
    if decision.case_type == CaseType.refund_request:
        return f"We have noted your request regarding transaction {txn_id}. Our support team will review the transaction and the applicable merchant policy. Any eligible amount, if approved, will be returned through official channels."
    if decision.case_type == CaseType.duplicate_payment:
        return f"We have noted a possible duplicate payment for transaction {txn_id}. Our payments team will verify it with the biller. Any eligible amount, if approved, will be returned through official channels."
    if decision.case_type == CaseType.agent_cash_in_issue:
        return f"We have noted your cash-in concern for transaction {txn_id}. Our agent operations team will verify the transaction status and update you through official channels."
    if decision.case_type == CaseType.merchant_settlement_delay:
        return f"We have noted your concern about settlement {txn_id}. Our merchant operations team will check the batch status and update you on the expected settlement time through official channels."
    return "We have recorded your concern and our support team will review the available details through official channels."


def _bangla_reply(evidence: EvidenceResult, decision: Classification) -> str:
    txn = evidence.relevant_transaction
    txn_id = txn.transaction_id if txn else None

    if decision.case_type == CaseType.phishing_or_social_engineering:
        return "সন্দেহজনক যোগাযোগের তথ্য দেওয়ার জন্য ধন্যবাদ। কলার বা বার্তার সঙ্গে আর যোগাযোগ করবেন না এবং শুধু অফিসিয়াল সহায়তা চ্যানেল ব্যবহার করুন। আমাদের ফ্রড রিস্ক টিম বিষয়টি যাচাই করবে।"
    if evidence.ambiguous:
        return "যোগাযোগ করার জন্য ধন্যবাদ। দেওয়া তথ্যের মধ্যে একাধিক সম্ভাব্য লেনদেন পাওয়া গেছে। সঠিক লেনদেন শনাক্ত করতে অফিসিয়াল চ্যানেলে প্রাপকের নম্বর বা ট্রানজেকশন আইডি দিন।"
    if txn_id is None:
        return "যোগাযোগ করার জন্য ধন্যবাদ। তদন্তে সহায়তার জন্য অফিসিয়াল চ্যানেলে ট্রানজেকশন আইডি, টাকার পরিমাণ, আনুমানিক সময় এবং কী সমস্যা হয়েছে তার সংক্ষিপ্ত বিবরণ দিন।"
    if decision.case_type == CaseType.wrong_transfer:
        return f"লেনদেন {txn_id} সম্পর্কে আপনার উদ্বেগ আমরা নথিভুক্ত করেছি। আমাদের ডিসপিউট টিম প্রযোজ্য নীতিমালা অনুযায়ী তথ্য যাচাই করবে। যাচাই শেষ না হওয়া পর্যন্ত ফলাফল নিশ্চিত করা সম্ভব নয়।"
    if decision.case_type == CaseType.payment_failed:
        return f"লেনদেন {txn_id} সম্পর্কিত পেমেন্ট সমস্যাটি আমরা নথিভুক্ত করেছি। আমাদের পেমেন্টস টিম লেনদেনের অবস্থা ও ব্যালেন্স প্রভাব যাচাই করবে। অনুমোদিত হলে যেকোনো প্রযোজ্য অর্থ অফিসিয়াল চ্যানেলে ফেরত দেওয়া হবে।"
    if decision.case_type == CaseType.refund_request:
        return f"লেনদেন {txn_id} সম্পর্কিত আপনার অনুরোধটি আমরা নথিভুক্ত করেছি। আমাদের টিম লেনদেন এবং প্রযোজ্য মার্চেন্ট নীতিমালা যাচাই করবে। অনুমোদিত হলে প্রযোজ্য অর্থ অফিসিয়াল চ্যানেলে ফেরত দেওয়া হবে।"
    if decision.case_type == CaseType.duplicate_payment:
        return f"লেনদেন {txn_id} সম্পর্কিত সম্ভাব্য ডুপ্লিকেট পেমেন্টটি আমরা নথিভুক্ত করেছি। আমাদের পেমেন্টস টিম বিলারের সঙ্গে বিষয়টি যাচাই করবে। অনুমোদিত হলে প্রযোজ্য অর্থ অফিসিয়াল চ্যানেলে ফেরত দেওয়া হবে।"
    if decision.case_type == CaseType.agent_cash_in_issue:
        return f"আপনার ক্যাশ-ইন লেনদেন {txn_id} সম্পর্কে আমরা অবগত হয়েছি। আমাদের এজেন্ট অপারেশন্স টিম লেনদেনের অবস্থা যাচাই করে অফিসিয়াল চ্যানেলে আপনাকে জানাবে।"
    if decision.case_type == CaseType.merchant_settlement_delay:
        return f"সেটেলমেন্ট {txn_id} সম্পর্কে আপনার উদ্বেগ আমরা নথিভুক্ত করেছি। আমাদের মার্চেন্ট অপারেশন্স টিম ব্যাচের অবস্থা যাচাই করে অফিসিয়াল চ্যানেলে প্রত্যাশিত সময় জানাবে।"
    return "আপনার উদ্বেগটি আমরা নথিভুক্ত করেছি। আমাদের সহায়তা টিম অফিসিয়াল চ্যানেলে উপলব্ধ তথ্য যাচাই করবে।"


def generate_text(
    request: AnalyzeTicketRequest,
    evidence: EvidenceResult,
    decision: Classification,
) -> tuple[str, str, str]:
    """Return agent summary, safe next action, and language-aware customer reply."""
    summary = _summary(request, evidence, decision)
    action = _next_action(evidence, decision)
    reply = _bangla_reply(evidence, decision) if is_bangla(request.language, request.complaint) else _english_reply(evidence, decision)
    return summary, action, reply
