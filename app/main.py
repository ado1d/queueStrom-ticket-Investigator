"""FastAPI entrypoint for the QueueStorm Investigator.

Routes:
  GET  /health           -> liveness probe
  POST /analyze-ticket   -> full triage pipeline (see app.pipeline)

Errors:
  400  invalid JSON or missing required fields (caught by Pydantic)
  422  schema valid but semantically invalid (empty complaint etc.)
  500  internal error — generic message, no stack trace leaked
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .config import settings
from .pipeline import analyze
from .schemas import AnalyzeRequest, AnalyzeResponse

logger = logging.getLogger("queuestorm.api")

app = FastAPI(
    title="QueueStorm Investigator",
    version="1.0.0",
    description="Evidence-grounded AI/API copilot for digital finance support tickets.",
)


@app.get("/health")
def health() -> Dict[str, str]:
    """Liveness probe used by Render, Poridhi, and judges."""
    return {"status": "ok"}


@app.post(
    "/analyze-ticket",
    response_model=AnalyzeResponse,
)
async def analyze_ticket(payload: AnalyzeRequest) -> AnalyzeResponse:
    """Run the full triage pipeline for a single ticket."""
    if not payload.complaint.strip():
        raise HTTPException(
            status_code=422,
            detail="complaint must be non-empty after stripping whitespace",
        )
    try:
        return await analyze(payload)
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover — defensive guard
        logger.exception("analyze-ticket failed: %s", exc)
        raise HTTPException(status_code=500, detail="internal error") from exc


# ---------------------------------------------------------------------------
# Error handlers — never leak internals to the client
# ---------------------------------------------------------------------------


@app.exception_handler(RequestValidationError)
async def _validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={"error": "invalid_request", "details": exc.errors()},
    )


@app.exception_handler(Exception)
async def _unhandled_handler(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled exception: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"error": "internal_error", "message": "an unexpected error occurred"},
    )


@app.get("/")
def root() -> Dict[str, Any]:
    return {
        "service": "queuestorm-investigator",
        "version": app.version,
        "endpoints": ["GET /health", "POST /analyze-ticket"],
        "llm_enabled": settings.llm_enabled,
    }
