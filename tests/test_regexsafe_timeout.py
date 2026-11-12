"""ReDoS guard: catastrophic patterns must not hang the engine."""

from __future__ import annotations

import threading
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



def test_catastrophic_pattern_bounded_on_worker_thread() -> None:
    """ReDoS guard must hold outside the main thread (GUI workers)."""
    from filewizard.regexsafe import compile_pattern, engine_name, safe_search

    if engine_name() != "regex":
        pytest.skip("stdlib fallback has no effective timeout off main thread")

    compiled = compile_pattern(r"(a|aa)+$")
    result_box: dict[str, object] = {}

    def worker() -> None:
        start = time.monotonic()
        result_box["result"] = safe_search(compiled, "a" * 40, timeout=0.05)
        result_box["elapsed"] = time.monotonic() - start

    t = threading.Thread(target=worker)
    t.start()
    t.join(timeout=5.0)
    assert not t.is_alive(), "worker thread hung on catastrophic regex"
    assert isinstance(result_box["result"], bool)
    assert float(result_box["elapsed"]) < 1.0  # type: ignore[arg-type]
