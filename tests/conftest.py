"""Pytest fixtures shared across the test suite."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "sample_cases.json"


@pytest.fixture(scope="session")
def sample_cases() -> List[Dict[str, Any]]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))["cases"]


@pytest.fixture(autouse=True)
def disable_llm(monkeypatch):
    """Ensure tests run without a real Gemini key."""
    from app import config

    monkeypatch.setattr(config.settings, "enable_llm", False, raising=False)
    monkeypatch.setattr(config.settings, "gemini_api_key", "", raising=False)
    yield
