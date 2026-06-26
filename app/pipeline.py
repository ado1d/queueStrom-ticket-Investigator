"""Pipeline orchestrator: ties evidence + classifier + LLM + text + safety together.

Single async entry point used by app.main.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .classifier import classify
from .config import settings
from .evidence import (
    compute_confidence,
    extract_clues,
    match_transaction,
    score_transactions,
    verdict as compute_verdict,
)
from .llm_fallback import call_gemini
from .safety import sanitize_response_fields
from .schemas import AnalyzeRequest, AnalyzeResponse
from .text_gen import render_text

logger = logging.getLogger("queuestorm.pipeline")


def _should_call_llm(
    language: Optional[str],
    confidence: float,
    matched_id: Optional[str],
) -> bool:
    """Decide whether the LLM fallback should run.

    Per updated behavior: whenever the LLM is enabled it runs on every request.
    The rules-based classifier still produces a normal answer if the LLM fails
    or returns no usable result — the LLM only augments (extra clues,
    contradiction flag, candidate txn id, confidence nudge).
    """
    if not settings.llm_enabled:
        return False
    return True


def _apply_llm_facts(
    clues,
    llm_result,
    transactions: List,
) -> tuple:
    """Merge LLM facts into clues; return updated (clues, candidate_txn_ids)."""
    if not llm_result or not llm_result.ok:
        return clues, []
    # LLM may surface a relevant txn id that the rule engine missed.
    candidate_ids: List[str] = []
    if llm_result.relevant_txn_id and any(
        t.transaction_id == llm_result.relevant_txn_id for t in transactions
    ):
        candidate_ids.append(llm_result.relevant_txn_id)
    if llm_result.amount is not None and not clues.amount:
        clues.amount = llm_result.amount
    if llm_result.counterparty_hint and not clues.counterparty_hint:
        clues.counterparty_hint = llm_result.counterparty_hint
    return clues, candidate_ids


async def analyze(request: AnalyzeRequest) -> AnalyzeResponse:
    complaint = (request.complaint or "").strip()
    transactions = request.transaction_history or []
    txn_dicts = [t.model_dump() for t in transactions]

    # 1. Extract clues (rules-based).
    clues = extract_clues(complaint)

    # 2. Score and match.
    scored = score_transactions(clues, transactions)
    matched_id = match_transaction(scored)
    matched_txn = next(
        (t for t in transactions if t.transaction_id == matched_id), None
    )
    matched_txn_dict = matched_txn.model_dump() if matched_txn else None

    # 3. Initial verdict + confidence.
    verdict_label, _ = compute_verdict(matched_id, scored, clues, transactions)
    confidence = compute_confidence(
        clues, scored, matched_id, verdict_label, llm_used=False
    )

    # 4. LLM fallback when needed.
    llm_result = None
    if _should_call_llm(request.language, confidence, matched_id):
        try:
            llm_result = await call_gemini(complaint, txn_dicts, request.language)
        except Exception as exc:  # pragma: no cover -- defensive
            logger.warning("LLM fallback raised: %s", exc)
            llm_result = None

        if llm_result and llm_result.ok:
            clues, candidate_ids = _apply_llm_facts(clues, llm_result, transactions)
            # If LLM pointed to a specific txn id we missed, prefer it.
            if (
                llm_result.relevant_txn_id
                and llm_result.relevant_txn_id in candidate_ids
                and matched_id is None
            ):
                matched_id = llm_result.relevant_txn_id
                matched_txn = next(
                    t for t in transactions if t.transaction_id == matched_id
                )
                matched_txn_dict = matched_txn.model_dump()
                # Re-score with the LLM-supplied candidate at top.
                scored = score_transactions(clues, transactions)
            # If LLM flagged contradiction, escalate to inconsistent.
            if llm_result.contradiction and verdict_label == "consistent":
                verdict_label = "inconsistent"
            # If LLM gave a case_type, allow it to bias the classifier.
            confidence = compute_confidence(
                clues, scored, matched_id, verdict_label, llm_used=True
            )
        elif llm_result and not llm_result.ok:
            logger.info("LLM returned no usable result: %s", llm_result.error)

    # 4b. Stash LLM-suggested case_type so the classifier can prefer it.
    llm_case_type: Optional[str] = None
    if llm_result and llm_result.ok and llm_result.case_type:
        llm_case_type = llm_result.case_type

    # 5. Classify + route.
    classification = classify(
        clues=clues,
        verdict_label=verdict_label,
        matched_txn=matched_txn_dict,
        user_type=request.user_type,
        confidence=confidence,
        llm_case_type=llm_case_type,
    )

    # 6. Render safe text.
    text_fields = render_text(
        classification.case_type, clues, matched_txn_dict, verdict_label
    )
    safe_fields = sanitize_response_fields(text_fields)

    # 7. Build response.
    reason_codes = list(classification.reason_codes)
    if matched_id is not None:
        reason_codes.append("transaction_match")
    if verdict_label == "consistent":
        reason_codes.append("evidence_consistent")
    elif verdict_label == "inconsistent":
        reason_codes.append("evidence_inconsistent")
    else:
        reason_codes.append("evidence_insufficient")

    return AnalyzeResponse(
        ticket_id=request.ticket_id,
        relevant_transaction_id=matched_id,
        evidence_verdict=verdict_label,
        case_type=classification.case_type,
        severity=classification.severity,
        department=classification.department,
        agent_summary=safe_fields["agent_summary"],
        recommended_next_action=safe_fields["recommended_next_action"],
        customer_reply=safe_fields["customer_reply"],
        human_review_required=classification.human_review_required,
        confidence=confidence,
        reason_codes=reason_codes,
    )
