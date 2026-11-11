"""Fuzz: random patterns must never hang the engine."""

from __future__ import annotations

import string
import time

import pytest

try:
    from hypothesis import given, settings
    from hypothesis import strategies as st
except ImportError:  # pragma: no cover
    pytest.skip("hypothesis not installed", allow_module_level=True)

from filewizard.regexsafe import compile_pattern, safe_search

_ALPHABET = string.ascii_letters + string.digits + r".*+?()[]{}^$\\|/"


@given(
    pattern=st.text(alphabet=_ALPHABET, min_size=0, max_size=80),
    text=st.text(alphabet="ab", min_size=0, max_size=32),
)
@settings(max_examples=200, deadline=None)
def test_fuzz_random_patterns_do_not_hang(pattern, text) -> None:
    try:
        compiled = compile_pattern(pattern)
    except Exception:
        return  # invalid pattern: rejected at compile time
    start = time.monotonic()
    result = safe_search(compiled, text, timeout=0.05)
    assert time.monotonic() - start < 1.0
    assert isinstance(result, bool)
