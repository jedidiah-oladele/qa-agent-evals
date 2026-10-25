import json

from graders.rubric_judge import (
    FakeJudge,
    LLMJudge,
    blind,
    build_judge_prompt,
    cross_check_selected,
    judge_item,
    parse_verdict,
)
from harness.config import models_config
from harness.models import Usage


def test_parse_verdict_variants():
    assert parse_verdict('{"verdict": "pass", "rationale": "ok"}') == ("pass", "ok")
    assert parse_verdict('Sure.\n```json\n{"verdict": "FAIL", "rationale": "no test"}\n```') == ("fail", "no test")
    assert parse_verdict('{"verdict": "pass", "rationale": "has {braces}"')[0] == "pass"
    assert parse_verdict("I think it passes")[0] == "error"


def test_prompt_contains_only_allowed_evidence(py_task):
    item = py_task.rubric[0]
    diff = "diff --git a/x b/x\n+fixed by claude-opus-5-5 (Anthropic)\n+also GPT-6 helped\n"
    prompt = build_judge_prompt(py_task, item, diff, {"TRIAGE.md": "Root cause: rounding"})
    assert py_task.prompt.strip()[:60] in prompt and item.criterion.strip()[:60] in prompt
    assert "Root cause: rounding" in prompt
    for model in [a.model_id for a in models_config().agents] + ["claude", "Anthropic", "GPT-6", "gpt-6.1-sol"]:
        assert model.lower() not in prompt.lower(), model
    hidden = next(py_task.hidden_tests_dir.rglob("*.py")).read_text()
    assert hidden.splitlines()[-1] not in prompt


def test_blind_masks_vendor_names():
    assert blind("Claude Code and codex and gpt-6-astra") == "[model] and [model] and [model]"


def test_judge_errors_are_recorded_not_raised(py_task):
    class Broken:
        model = "broken"

        def judge(self, system, prompt):
            raise TimeoutError("no response")

    verdict = judge_item(Broken(), None, py_task, py_task.rubric[0], "diff", {})
    assert verdict.verdict == "error" and "TimeoutError" in verdict.rationale


def test_malformed_reply_is_retried_once(py_task):
    class Flaky:
        model = "flaky"
        calls = 0

        def judge(self, system, prompt):
            Flaky.calls += 1
            reply = "hmm" if Flaky.calls == 1 else json.dumps({"verdict": "fail", "rationale": "missing test"})
            return reply, Usage(10, 2)

    verdict = judge_item(Flaky(), None, py_task, py_task.rubric[0], "diff", {})
    assert verdict.verdict == "fail" and Flaky.calls == 2 and verdict.usage.input_tokens == 20


def test_llm_judge_uses_configured_model_and_mock_client(py_task):
    from types import SimpleNamespace as NS

    class Client:
        def __init__(self):
            self.responses = self
            self.body = None

        def create(self, **body):
            self.body = body
            return NS(output_text='{"verdict": "pass", "rationale": "uses round_half_up"}',
                      usage=NS(input_tokens=900, output_tokens=40, input_tokens_details=NS(cached_tokens=0)))

    client = Client()
    spec = models_config().judge.primary
    verdict = judge_item(LLMJudge(spec, client), spec.pricing, py_task, py_task.rubric[0], "diff --git a/x b/x", {})
    assert client.body["model"] == "gpt-6.1-sol"
    assert verdict.verdict == "pass" and verdict.cost_usd > 0


def test_cross_check_sample_is_about_twenty_percent_and_deterministic():
    picks = [cross_check_selected(7, 0.2, "task", "model", i, "item") for i in range(5000)]
    assert 0.17 < sum(picks) / len(picks) < 0.23
    assert picks == [cross_check_selected(7, 0.2, "task", "model", i, "item") for i in range(5000)]


def test_fake_judge_is_labelled():
    reply, _ = FakeJudge().judge("s", "## Criterion to grade\nuses rounding helper\n## Final diff\n+rounding")
    assert "dry-run fake judge" in json.loads(reply)["rationale"]
