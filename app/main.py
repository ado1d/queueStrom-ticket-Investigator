"""FastAPI entry point for QueueStorm Investigator."""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.status import HTTP_400_BAD_REQUEST, HTTP_422_UNPROCESSABLE_CONTENT, HTTP_500_INTERNAL_SERVER_ERROR

from app.classifier import classify
from app.config import get_settings
from app.evidence import investigate
from app.llm_fallback import get_optional_hint
from app.safety import sanitize_customer_reply, sanitize_operational_text, strip_prompt_injection
from app.schemas import AnalyzeTicketRequest, TicketAnalysisResponse
from app.text_gen import generate_text

settings = get_settings()
logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
logger = logging.getLogger("queuestorm")

app = FastAPI(
    title="QueueStorm Investigator",
    version="1.0.0",
    docs_url="/docs",
    redoc_url=None,
)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, __: RequestValidationError) -> JSONResponse:
    # Validation detail can include user values, so return a stable non-sensitive
    # message instead of reflecting the raw request body.
    return JSONResponse(
        status_code=HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": "Request validation failed. Check required fields, enums, and non-empty values."},
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error while analyzing ticket", exc_info=exc)
    return JSONResponse(
        status_code=HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error."},
    )


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/analyze-ticket", response_model=TicketAnalysisResponse)
async def analyze_ticket(request: AnalyzeTicketRequest) -> TicketAnalysisResponse:
    """Investigate one synthetic support ticket using deterministic evidence rules."""
    clean_complaint = strip_prompt_injection(request.complaint)
    evidence = investigate(request, clean_complaint)
    decision = classify(request, evidence, settings)

    # Optional LLM requests never block or affect critical decisions.  Triggering
    # is deliberately conservative to avoid latency on ordinary requests.
    if settings.enable_llm and (
        evidence.confidence < 0.50
        or (request.language is not None and request.language.value in {"bn", "mixed"} and not evidence.clues.topics)
        or evidence.relevant_transaction is None
    ):
        await get_optional_hint(clean_complaint, settings)

    summary, next_action, customer_reply = generate_text(request, evidence, decision)
    summary = sanitize_operational_text(summary)
    next_action = sanitize_operational_text(next_action)
    customer_reply = sanitize_customer_reply(customer_reply, request.language, request.complaint)

    return TicketAnalysisResponse(
        ticket_id=request.ticket_id,
        relevant_transaction_id=evidence.relevant_transaction.transaction_id if evidence.relevant_transaction else None,
        evidence_verdict=evidence.verdict,
        case_type=decision.case_type,
        severity=decision.severity,
        department=decision.department,
        agent_summary=summary,
        recommended_next_action=next_action,
        customer_reply=customer_reply,
        human_review_required=decision.human_review_required,
        confidence=evidence.confidence,
        reason_codes=evidence.reason_codes,
    )
