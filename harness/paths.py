"""Repository locations used across the harness."""

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TARGET = REPO / "target"
TASKS = REPO / "tasks"
CONFIG = REPO / "config"
RESULTS = REPO / "results"
RUNS = RESULTS / "runs"
SCRATCH = REPO / ".scratch"

CODEBASES = {"python": "shopcore", "typescript": "ledgerkit"}

# Never copied into an agent workspace, never shown in diffs.
WORKSPACE_IGNORES = (
    ".git",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".qa_grader",
    "*.pyc",
    "*.tsbuildinfo",
)
