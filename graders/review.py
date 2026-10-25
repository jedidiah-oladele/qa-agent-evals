"""Parse REVIEW.md findings and match them to seeded defects (code_review tasks).

Agents are asked to list each finding as a bullet that starts with a location:

    - `src/shopcore/inventory.py:88` - reserved units are never released when ...
    - src/client.ts:120-131: the token is logged in plain text ...

A finding *matches* a seeded defect when it names the same file and its line
(or range) overlaps the defect's range widened by ``line_tolerance``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from harness.task import ReviewDefect

_FINDING = re.compile(
    r"^\s*(?:[-*+]|\d+[.)])\s+(?:\*\*)?`?(?P<file>[\w./-]+\.(?:py|ts|tsx|js|json|toml|ya?ml))"
    r"(?::|#L| line |, line )(?P<start>\d+)(?:\s*[-–]\s*L?(?P<end>\d+))?`?(?:\*\*)?"
)


@dataclass(frozen=True)
class Finding:
    file: str
    start: int
    end: int
    text: str


def parse_findings(review: str) -> list[Finding]:
    findings = []
    for line in review.splitlines():
        match = _FINDING.match(line)
        if not match:
            continue
        start = int(match.group("start"))
        end = int(match.group("end") or start)
        findings.append(Finding(match.group("file").removeprefix("./"), min(start, end), max(start, end),
                                line.strip()))
    return findings


def matches(finding: Finding, defect: ReviewDefect, tolerance: int) -> bool:
    low, high = defect.lines[0] - tolerance, defect.lines[1] + tolerance
    same_file = finding.file == defect.file or defect.file.endswith("/" + finding.file)
    return same_file and finding.start <= high and finding.end >= low


@dataclass
class ReviewMatch:
    found: dict[str, list[str]]
    missed: list[str]
    false_positives: list[str]
    findings: int

    def to_dict(self) -> dict:
        return {"found": self.found, "missed": self.missed, "false_positives": self.false_positives,
                "findings": self.findings}


def match_review(review: str, defects: list[ReviewDefect], tolerance: int) -> ReviewMatch:
    findings = parse_findings(review)
    found: dict[str, list[str]] = {}
    false_positives = []
    for finding in findings:
        hit = [d.id for d in defects if matches(finding, d, tolerance)]
        for defect_id in hit:
            found.setdefault(defect_id, []).append(finding.text[:200])
        if not hit:
            false_positives.append(finding.text[:200])
    missed = [d.id for d in defects if d.id not in found]
    return ReviewMatch(found, missed, false_positives, len(findings))
