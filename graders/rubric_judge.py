"""LLM judge for rubric items: one call per item, JSON verdict plus rationale.

What the judge sees: the task prompt, one rubric criterion, the agent's final
diff, and TRIAGE.md / REVIEW.md if present. It never sees the model or harness
name, the trajectory, or hidden tests. As an extra guard, vendor and model
names are masked in everything it reads (an agent may sign its work).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Protocol

from harness.config import JudgeModel, models_config
from harness.models import Usage, cost_usd
from harness.task import RubricItem, Task

MAX_DIFF_CHARS = 60_000

JUDGE_SYSTEM = """You grade one rubric criterion for a software engineering task.
Decide from the evidence alone whether the criterion is met. Be strict: if the
evidence does not clearly show the criterion is met, the verdict is "fail".
Do not reward effort, intent or explanations that the code does not back up.
Reply with a single JSON object and nothing else:
{"verdict": "pass" | "fail", "rationale": "<one to three sentences citing the evidence>"}"""


def _masked_terms() -> list[str]:
    config = models_config()
    terms = {a.model_id for a in [*config.agents, *config.fake_agents]}
    terms |= {config.judge.primary.model_id, config.judge.cross_check.model_id}
    terms |= {h.key for h in config.native_harnesses}
    return sorted(terms, key=len, reverse=True)


_VENDOR = re.compile(r"\b(claude(?: code)?|anthropic|openai|chatgpt|gpt-?\d[\w.-]*|codex|opus|sonnet|gemini)\b",
                     re.IGNORECASE)


def blind(text: str) -> str:
    for term in _masked_terms():
        text = text.replace(term, "[model]")
    return _VENDOR.sub("[model]", text)


def build_judge_prompt(task: Task, item: RubricItem, diff: str, artifacts: dict[str, str]) -> str:
    shown = diff if len(diff) <= MAX_DIFF_CHARS else (
        diff[:MAX_DIFF_CHARS] + f"\n[diff truncated: {len(diff) - MAX_DIFF_CHARS} more characters not shown]")
    parts = [
        "## Task given to the engineer\n" + task.prompt.strip(),
        "## Criterion to grade\n" + item.criterion.strip(),
        "## Final diff\n```diff\n" + (shown.strip() or "(no changes)") + "\n```",
    ]
    for name in ("TRIAGE.md", "REVIEW.md"):
        if name in artifacts:
            parts.append(f"## {name}\n```markdown\n{artifacts[name].strip()}\n```")
    return blind("\n\n".join(parts))


@dataclass
class Verdict:
    verdict: str  # pass | fail | error
    rationale: str
    model: str
    usage: Usage = field(default_factory=Usage)
    cost_usd: float | None = 0.0

    def to_dict(self) -> dict:
        return {"verdict": self.verdict, "rationale": self.rationale, "model": self.model,
                "usage": self.usage.to_dict(), "cost_usd": self.cost_usd}


def parse_verdict(text: str) -> tuple[str, str]:
    """Extract (verdict, rationale) from a judge reply; ("error", reason) if impossible."""
    for candidate in re.findall(r"\{.*?\}", text, re.DOTALL) + [text]:
        try:
            data = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, dict) and str(data.get("verdict", "")).lower() in ("pass", "fail"):
            return str(data["verdict"]).lower(), str(data.get("rationale", "")).strip()
    match = re.search(r'"verdict"\s*:\s*"(pass|fail)"', text, re.IGNORECASE)
    if match:
        return match.group(1).lower(), "(rationale not parseable)"
    return "error", f"unparseable judge reply: {text[:200]!r}"


class Judge(Protocol):
    model: str

    def judge(self, system: str, prompt: str) -> tuple[str, Usage]: ...


class LLMJudge:
    """Calls the configured judge model through the same provider adapters as agents."""

    def __init__(self, spec: JudgeModel, client: object | None = None) -> None:
        from harness.models import complete_text

        self.spec = spec
        self.model = spec.model_id
        self._client = client
        self._complete = complete_text

    def judge(self, system: str, prompt: str) -> tuple[str, Usage]:
        return self._complete(self.spec.provider, self.spec.model_id, system, prompt,
                              max_tokens=self.spec.max_output_tokens, client=self._client)


class FakeJudge:
    """Dry-run judge. Deterministic, makes no network call, and says so in every rationale.

    Rule: an item passes when the evidence is non-empty and the diff (or written
    artifact) mentions at least one distinctive word from the criterion. The
    ``disagree_rate`` lets a second fake judge disagree on a fixed slice of
    items so the cross-check agreement code path is exercised; ``error_rate``
    makes it return a malformed reply on a fixed slice so the judge-error
    path (and grader-error attribution) is exercised.
    """

    def __init__(self, model: str = "fake-judge", disagree_rate: float = 0.0, error_rate: float = 0.0) -> None:
        self.model = model
        self.disagree_rate = disagree_rate
        self.error_rate = error_rate

    def judge(self, system: str, prompt: str) -> tuple[str, Usage]:
        criterion = prompt.split("## Criterion to grade\n", 1)[-1].split("\n## ", 1)[0].lower()
        evidence = prompt.split("## Final diff\n", 1)[-1].lower()
        words = {w for w in re.findall(r"[a-z_]{6,}", criterion)} - {"should", "explains", "change", "changes",
                                                                       "explain", "states", "correctly"}
        has_evidence = "(no changes)" not in evidence
        verdict = "pass" if has_evidence and any(w in evidence for w in words) else "fail"
        digest = int(hashlib.sha256((self.model + prompt).encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
        if digest > 1 - self.error_rate:
            # Simulates a judge that ignores the output format, so the
            # unparseable-verdict path (retry, then "error") is exercised.
            return "[dry-run fake judge: simulated malformed reply]", Usage(len(prompt) // 4, 10)
        if digest < self.disagree_rate:
            verdict = "fail" if verdict == "pass" else "pass"
        reply = json.dumps({"verdict": verdict, "rationale": f"[dry-run fake judge {self.model}: keyword "
                                                              f"heuristic, not an LLM verdict]"})
        return reply, Usage(input_tokens=len(prompt) // 4, output_tokens=40)


def judge_item(judge: Judge, spec_pricing, task: Task, item: RubricItem, diff: str,
               artifacts: dict[str, str]) -> Verdict:
    prompt = build_judge_prompt(task, item, diff, artifacts)
    try:
        reply, usage = judge.judge(JUDGE_SYSTEM, prompt)
    except Exception as exc:  # network/API failure: recorded, attributed as grader error
        return Verdict("error", f"judge call failed: {type(exc).__name__}: {exc}"[:300], judge.model)
    verdict, rationale = parse_verdict(reply)
    if verdict == "error":
        try:
            reply, usage2 = judge.judge(JUDGE_SYSTEM, prompt + "\n\nReply with the JSON object only.")
            usage = usage + usage2
            verdict, rationale = parse_verdict(reply)
        except Exception as exc:
            rationale = f"judge retry failed: {exc}"[:300]
    return Verdict(verdict, rationale, judge.model, usage, cost_usd(usage, spec_pricing))


def cross_check_selected(seed: int, rate: float, *key_parts: object) -> bool:
    """Deterministic ~``rate`` sample of rubric judgements for the second judge."""
    digest = hashlib.sha256(":".join(map(str, (seed, *key_parts))).encode()).hexdigest()
    return int(digest[:8], 16) / 0xFFFFFFFF < rate
