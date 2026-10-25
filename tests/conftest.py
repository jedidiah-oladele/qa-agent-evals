"""Shared fixtures. API keys are removed for every test so nothing can call a paid API."""

from __future__ import annotations

import pytest

from harness.paths import TASKS
from harness.task import load_task


@pytest.fixture(autouse=True)
def _no_api_keys(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)


@pytest.fixture
def py_task():
    return load_task(TASKS / "bf_001_tax_half_even")


@pytest.fixture
def ts_task():
    return load_task(TASKS / "pr_016_invoice_void")
