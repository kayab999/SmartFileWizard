"""Property-based tests for fsmove no-overwrite invariant (Hypothesis)."""

from __future__ import annotations

import pytest

try:
    from hypothesis import given, settings
    from hypothesis import strategies as st
except ImportError:  # pragma: no cover
    pytest.skip("hypothesis not installed", allow_module_level=True)

from filewizard.fsmove import DestinationExistsError, move_noreplace


@given(
    src_content=st.binary(min_size=1, max_size=64),
    dst_content=st.binary(min_size=1, max_size=64),
)
@settings(max_examples=50, deadline=None)
def test_property_move_never_overwrites_existing_destination(
    tmp_path_factory, src_content, dst_content
) -> None:
    base = tmp_path_factory.mktemp("prop")
    src = base / "src.txt"
    dst = base / "dst.txt"
    src.write_bytes(src_content)
    dst.write_bytes(dst_content)
    with pytest.raises(DestinationExistsError):
        move_noreplace(src, dst)
    assert dst.read_bytes() == dst_content
    assert src.read_bytes() == src_content


@given(content=st.binary(min_size=1, max_size=64))
@settings(max_examples=50, deadline=None)
def test_property_free_destination_move_round_trips(
    tmp_path_factory, content
) -> None:
    base = tmp_path_factory.mktemp("prop2")
    src = base / "src.txt"
    dst = base / "out" / "dst.txt"
    dst.parent.mkdir()
    src.write_bytes(content)
    move_noreplace(src, dst)
    assert dst.read_bytes() == content
    assert not src.exists()
    assert not list(dst.parent.glob(".dst.txt.fwtmp-*"))
