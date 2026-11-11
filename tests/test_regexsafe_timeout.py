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


def test_engine_report_and_timeout_path() -> None:
    """E4 closure: with the `regex` extra installed the per-call timeout
    path is exercised directly (real bounded evaluation, not SIGALRM)."""
    import regex  # noqa: F401

    from filewizard.regexsafe import _regex, engine_name

    assert engine_name() == "regex"
    assert _regex is not None
    compiled = compile_pattern(r"(a+)+b")
    # Tiny timeout still returns a bounded bool (False on timeout).
    assert safe_search(compiled, "a" * 40, timeout=0.01) is False
    # Non-pathological pattern with generous timeout still matches.
    ok = compile_pattern(r"\d+")
    assert safe_search(ok, "12345", timeout=1.0) is True
