from graders.review import match_review, parse_findings
from harness.task import ReviewDefect

DEFECTS = [ReviewDefect(id="leak", file="src/client.ts", lines=(120, 124), summary="token logged"),
           ReviewDefect(id="race", file="src/client.ts", lines=(80, 95), summary="refresh not single-flight")]


def test_parse_common_formats():
    review = """# Review
- `src/client.ts:121` - the access token is interpolated into the error message.
* src/client.ts:80-95: two concurrent 401s both refresh.
1. **`src/money.ts:10`** nit: naming
- general comment without a location
"""
    findings = parse_findings(review)
    assert [(f.file, f.start, f.end) for f in findings] == [
        ("src/client.ts", 121, 121), ("src/client.ts", 80, 95), ("src/money.ts", 10, 10)]


def test_matching_with_tolerance_and_false_positives():
    review = "- `src/client.ts:127` - token leak\n- `src/client.ts:90` - race\n- `src/dates.ts:3` - style\n"
    result = match_review(review, DEFECTS, tolerance=3)
    assert sorted(result.found) == ["leak", "race"]
    assert result.missed == [] and len(result.false_positives) == 1


def test_wrong_file_or_far_line_does_not_count():
    review = "- `src/invoice.ts:121` - token leak\n- `src/client.ts:60` - race\n"
    result = match_review(review, DEFECTS, tolerance=3)
    assert sorted(result.missed) == ["leak", "race"] and len(result.false_positives) == 2
