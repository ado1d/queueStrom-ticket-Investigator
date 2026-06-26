"""LLM fallback tests (httpx is mocked, no real Gemini call)."""
from __future__ import annotations

import json
from typing import Any, Dict

import httpx
import pytest

from app import config
from app.llm_fallback import LLMResult, _extract_json, _validate, call_gemini


def test_extract_json_strips_fences():
    raw = "```json\n{\"a\": 1}\n```"
    assert _extract_json(raw) == {"a": 1}


def test_extract_json_handles_garbage():
    assert _extract_json("hello world") is None
    assert _extract_json("") is None
    assert _extract_json(None) is None


def test_validate_rejects_bad_case_type():
    out = _validate({"case_type": "made_up", "contradiction": True})
    assert out is None


def test_validate_coerces_amount():
    out = _validate({"case_type": "other", "amount": "1500.5", "contradiction": False})
    assert out is not None
    assert out.amount == 1500.5
    assert out.case_type == "other"


def test_validate_rejects_non_string_txn_id():
    out = _validate({"case_type": "other", "relevant_txn_id": 12345})
    assert out is None


@pytest.mark.asyncio
async def test_call_gemini_returns_used_false_when_disabled(monkeypatch):
    monkeypatch.setattr(config.settings, "enable_llm", False, raising=False)
    out = await call_gemini("hi", [], "en")
    assert out.used is False
    assert out.ok is False


@pytest.mark.asyncio
async def test_call_gemini_timeout_falls_back(monkeypatch):
    monkeypatch.setattr(config.settings, "enable_llm", True, raising=False)
    monkeypatch.setattr(config.settings, "gemini_api_key", "fake-key", raising=False)
    monkeypatch.setattr(config.settings, "llm_timeout", 0.1, raising=False)

    async def _raise(*_a, **_kw):
        raise httpx.ReadTimeout("boom")

    monkeypatch.setattr(httpx.AsyncClient, "post", _raise)
    out = await call_gemini("hi", [], "en")
    assert out.used is True
    assert out.ok is False
    assert out.error is not None


@pytest.mark.asyncio
async def test_call_gemini_parses_valid_response(monkeypatch):
    monkeypatch.setattr(config.settings, "enable_llm", True, raising=False)
    monkeypatch.setattr(config.settings, "gemini_api_key", "fake-key", raising=False)

    class _Resp:
        def __init__(self, body: Dict[str, Any]):
            self._body = body

        def raise_for_status(self):
            return None

        def json(self):
            return self._body

    class _Client:
        def __init__(self, *_, **__):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *_, **__):
            return _Resp({
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": json.dumps({
                                        "relevant_txn_id": "TXN-1",
                                        "case_type": "wrong_transfer",
                                        "contradiction": False,
                                        "amount": 5000,
                                        "counterparty_hint": "01719876543",
                                    })
                                }
                            ]
                        }
                    }
                ]
            })

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    out = await call_gemini("wrong number 5000 taka", [], "en")
    assert out.ok is True
    assert out.relevant_txn_id == "TXN-1"
    assert out.case_type == "wrong_transfer"
    assert out.amount == 5000
    assert out.counterparty_hint == "01719876543"


@pytest.mark.asyncio
async def test_call_gemini_rejects_invalid_enum(monkeypatch):
    monkeypatch.setattr(config.settings, "enable_llm", True, raising=False)
    monkeypatch.setattr(config.settings, "gemini_api_key", "fake-key", raising=False)

    class _Resp:
        def raise_for_status(self): return None
        def json(self): return {"candidates": [{"content": {"parts": [{"text": json.dumps({"case_type": "hackerman"})}]}}]}

    class _Client:
        def __init__(self, *_, **__): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return None
        async def post(self, *_, **__): return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    out = await call_gemini("hi", [], "en")
    assert out.ok is False
    assert out.error == "invalid_enums"
