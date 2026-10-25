"""Adapters for vendor coding-agent CLIs (optional; skipped when not installed)."""

from .base import NativeHarness, NativeResult
from .claude_code import ClaudeCodeHarness
from .codex_cli import CodexHarness

ADAPTERS = {"claude_code": ClaudeCodeHarness, "codex_cli": CodexHarness}

__all__ = ["ADAPTERS", "ClaudeCodeHarness", "CodexHarness", "NativeHarness", "NativeResult"]
