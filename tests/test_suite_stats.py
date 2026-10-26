"""The README snapshot has to match what the code computes."""

from pathlib import Path

from tools.suite_stats import END, README, START, render_snapshot


def test_readme_snapshot_matches_the_code():
    text = Path(README).read_text(encoding="utf-8")
    assert START in text and END in text
    committed = text.split(START, 1)[1].split(END, 1)[0].strip()
    assert committed == render_snapshot().strip()
