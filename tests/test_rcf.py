# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Unit tests for the pure-Python parts of pyte.rcf."""

import pytest

from pyte.rcf import _grow_loop, _pick_port, _split_ta_list


def test_split_ta_list_basic():
    assert _split_ta_list(b"Agt_A\x00Agt_B\x00\x00") == ["Agt_A", "Agt_B"]


def test_split_ta_list_single():
    assert _split_ta_list(b"Agt_A\x00\x00") == ["Agt_A"]


def test_split_ta_list_empty():
    assert _split_ta_list(b"\x00") == []
    assert _split_ta_list(b"") == []


def test_split_ta_list_no_trailing_nul():
    # Defensive: used length may exclude the final terminator
    assert _split_ta_list(b"Agt_A\x00Agt_B") == ["Agt_A", "Agt_B"]


def test_pick_port_range():
    p = _pick_port()
    assert 20000 <= p <= 32000


def test_pick_port_varies():
    assert len({_pick_port() for _ in range(20)}) > 1


# -- _grow_loop tests -------------------------------------------------------

def test_grow_loop_succeeds_first_try():
    """No retry needed: call succeeds immediately."""
    def call(size):
        return 0, b"result"

    assert _grow_loop(call) == b"result"


def test_grow_loop_retries_on_smallbuf():
    """Retries once on ESMALLBUF, then succeeds with doubled size."""
    sizes = []

    def call(size):
        sizes.append(size)
        if len(sizes) == 1:
            return "ESMALLBUF", None
        return 0, b"Agt_A\x00Agt_B\x00\x00"

    data = _grow_loop(call, initial=4096)
    assert _split_ta_list(data) == ["Agt_A", "Agt_B"]
    assert sizes == [4096, 8192]


def test_grow_loop_raises_on_overflow():
    """Raises RuntimeError when buffer would exceed 1 MiB."""
    def call(size):
        return "ESMALLBUF", None

    with pytest.raises(RuntimeError, match="1 MiB"):
        _grow_loop(call, initial=4096)


def test_grow_loop_propagates_other_errors():
    """Propagates non-ESMALLBUF errors unchanged."""
    sentinel = ValueError("RCF error")

    def call(size):
        return sentinel, None

    with pytest.raises(ValueError, match="RCF error"):
        _grow_loop(call)
