"""Pydantic request and response schemas for the public API contract."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrEnum(str, Enum):
    """String enum compatible with JSON API payloads."""


class Language(StrEnum):
    en = "en"
    bn = "bn"
    mixed = "mixed"


class Channel(StrEnum):
    in_app_chat = "in_app_chat"
    call_center = "call_center"
    email = "email"
    merchant_portal = "merchant_portal"
    field_agent = "field_agent"


class UserType(StrEnum):
    customer = "customer"
    merchant = "merchant"
    agent = "agent"
    unknown = "unknown"


class TransactionType(StrEnum):
    transfer = "transfer"
    payment = "payment"
    cash_in = "cash_in"
    cash_out = "cash_out"
    settlement = "settlement"
    refund = "refund"


class TransactionStatus(StrEnum):
    completed = "completed"
    failed = "failed"
    pending = "pending"
    reversed = "reversed"


class EvidenceVerdict(StrEnum):
    consistent = "consistent"
    inconsistent = "inconsistent"
    insufficient_data = "insufficient_data"


class CaseType(StrEnum):
    wrong_transfer = "wrong_transfer"
    payment_failed = "payment_failed"
    refund_request = "refund_request"
    duplicate_payment = "duplicate_payment"
    merchant_settlement_delay = "merchant_settlement_delay"
    agent_cash_in_issue = "agent_cash_in_issue"
    phishing_or_social_engineering = "phishing_or_social_engineering"
    other = "other"


class Severity(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class Department(StrEnum):
    customer_support = "customer_support"
    dispute_resolution = "dispute_resolution"
    payments_ops = "payments_ops"
    merchant_operations = "merchant_operations"
    agent_operations = "agent_operations"
    fraud_risk = "fraud_risk"


class Transaction(BaseModel):
    """A single item from the synthetic transaction-history snippet."""

    model_config = ConfigDict(extra="ignore", use_enum_values=False)

    transaction_id: str = Field(min_length=1, max_length=128)
    timestamp: datetime
    type: TransactionType
    amount: float = Field(gt=0, le=1_000_000_000)
    counterparty: str = Field(min_length=1, max_length=256)
    status: TransactionStatus

    @field_validator("transaction_id", "counterparty", mode="before")
    @classmethod
    def normalize_required_text(cls, value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("must be a string")
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class AnalyzeTicketRequest(BaseModel):
    """Exact input contract accepted by POST /analyze-ticket."""

    model_config = ConfigDict(extra="ignore", use_enum_values=False)

    ticket_id: str = Field(min_length=1, max_length=128)
    complaint: str = Field(min_length=1, max_length=6000)
    language: Language | None = None
    channel: Channel | None = None
    user_type: UserType | None = None
    campaign_context: str | None = Field(default=None, max_length=256)
    transaction_history: list[Transaction] = Field(default_factory=list, max_length=25)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("ticket_id", "complaint", mode="before")
    @classmethod
    def normalize_text(cls, value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("must be a string")
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("campaign_context", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: Any) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("must be a string")
        return value.strip() or None


class TicketAnalysisResponse(BaseModel):
    """Exact response shape required by the QueueStorm problem statement."""

    model_config = ConfigDict(extra="forbid", use_enum_values=False)

    ticket_id: str
    relevant_transaction_id: str | None
    evidence_verdict: EvidenceVerdict
    case_type: CaseType
    severity: Severity
    department: Department
    agent_summary: str = Field(min_length=1, max_length=2000)
    recommended_next_action: str = Field(min_length=1, max_length=2000)
    customer_reply: str = Field(min_length=1, max_length=2000)
    human_review_required: bool
    confidence: float = Field(ge=0, le=1)
    reason_codes: list[str] = Field(default_factory=list, max_length=20)
