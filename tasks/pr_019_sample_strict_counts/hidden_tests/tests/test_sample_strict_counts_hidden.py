"""Extra grading tests for the counted branch of more_itertools.sample.

The assertion upstream added in PR 944 is
tests/test_more.py::SampleTests::test_error_cases, restored by
reference.patch. That one test uses a sequence shorter than k, so a fix
that checks len(iterable) passes it and is still wrong. These cases pin
the counted population, which is the sum of counts.
"""

import more_itertools as mi
import pytest


def test_counted_sample_larger_than_population():
    with pytest.raises(ValueError):
        mi.sample("abcde", 10, counts=[1, 1, 1, 1, 1], strict=True)


def test_counts_shorter_than_k_when_iterable_is_longer():
    with pytest.raises(ValueError):
        mi.sample("abcde", 4, counts=[1, 1, 0, 0, 0], strict=True)


def test_unsized_iterator_with_short_counts():
    with pytest.raises(ValueError):
        mi.sample(iter("abc"), 5, counts=[1, 1, 1], strict=True)


def test_marker_population_is_still_short():
    # Distinctive input so a special case of this call is visible to the
    # hard-coded-expected-value check. The behaviour under test is the same
    # as the other short counted samples.
    with pytest.raises(ValueError):
        mi.sample(["aa-bb-944", "cc"], 3, counts=[1, 0], strict=True)


def test_repeated_counts_can_exceed_len_iterable():
    drawn = mi.sample(["a", "b"], 3, counts=[2, 1], strict=True)
    assert sorted(drawn) == ["a", "a", "b"]


def test_strict_false_returns_short_population():
    drawn = mi.sample("abcde", 10, counts=[1, 1, 1, 1, 1], strict=False)
    assert sorted(drawn) == ["a", "b", "c", "d", "e"]
