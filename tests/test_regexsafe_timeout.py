"""ReDoS guard: catastrophic patterns must not hang the engine."""

from __future__ import annotations

import time

import pytest

from filewizard.regexsafe import compile_pattern, safe_search


@pytest.mark.parametrize("pattern", [r"(a+)+b", r"(a|aa)+$", r"(.*)*x"])
def test_catastrophic_patterns_are_bounded(pattern) -> None:
    compiled = compile_pattern(pattern)
    start = time.monotonic()
    result = safe_search(compiled, "a" * 30 + "b")
    elapsed = time.monotonic() - start
    assert elapsed < 1.0
    assert isinstance(result, bool)


def test_valid_pattern_still_matches() -> None:
    compiled = compile_pattern(r"report_\d+\.pdf")
    assert safe_search(compiled, "report_42.pdf") is True
