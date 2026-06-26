"""Pydantic request/response schemas for the QueueStorm Investigator API.

Schema values are locked to the enums in PRD §10. Validation is strict so
malformed payloads fail fast (400/422) without leaking internals.
"""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

# ---------------------------------------------------------------------------
# Enums (PRD §10)
# ---------------------------------------------------------------------------

CaseType = Literal[
    "wrong_transfer",
    "payment_failed",
    "refund_request",
    "duplicate_payment",
    "merchant_settlement_delay",
    "agent_cash_in_issue",
    "phishing_or_social_engineering",
    "other",
]

Severity = Literal["low", "medium", "high", "critical"]

Department = Literal[
    "customer_support",
    "dispute_resolution",
    "payments_ops",
    "merchant_operations",
    "agent_operations",
    "fraud_risk",
]

EvidenceVerdict = Literal["consistent", "inconsistent", "insufficient_data"]

TransactionType = Literal[
    "transfer",
    "payment",
    "cash_in",
    "cash_out",
    "settlement",
    "refund",
]

TransactionStatus = Literal["completed", "failed", "pending", "reversed"]

Language = Literal["en", "bn", "mixed"]
Channel = Literal["in_app_chat", "call_center", "email", "merchant_portal", "field_agent"]
UserType = Literal["customer", "merchant", "agent", "unknown"]


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class TransactionEntry(BaseModel):
    transaction_id: str = Field(..., min_length=1)
    timestamp: str = Field(..., min_length=1)
    type: TransactionType
    amount: float = Field(..., ge=0)
    counterparty: str = Field(..., min_length=1)
    status: TransactionStatus

    @field_validator("timestamp")
    @classmethod
    def _validate_timestamp(cls, value: str) -> str:
        # Accept ISO-8601-ish strings. Real parsing happens in evidence engine.
        if "T" not in value:
            raise ValueError("timestamp must be ISO-8601 with 'T' separator")
        return value


class AnalyzeRequest(BaseModel):
    ticket_id: str = Field(..., min_length=1)
    complaint: str = Field(..., min_length=1)
    language: Optional[Language] = None
    channel: Optional[Channel] = None
    user_type: Optional[UserType] = None
    campaign_context: Optional[str] = None
    transaction_history: List[TransactionEntry] = Field(default_factory=list)
    metadata: Optional[dict] = None


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class AnalyzeResponse(BaseModel):
    ticket_id: str
    relevant_transaction_id: Optional[str]
    evidence_verdict: EvidenceVerdict
    case_type: CaseType
    severity: Severity
    department: Department
    agent_summary: str
    recommended_next_action: str
    customer_reply: str
    human_review_required: bool
    confidence: float = Field(..., ge=0.0, le=1.0)
    reason_codes: List[str] = Field(default_factory=list)
    # Transparency: was the LLM consulted, and did it succeed?
    llm_used: bool = False
    llm_status: Optional[str] = None  # "ok" | "skipped" | "failed:<reason>" | "disabled"
