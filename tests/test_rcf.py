# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Unit tests for the pure-Python parts of pyte.rcf."""

from pyte.rcf import _pick_port, _split_ta_list


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
    assert 20000 <= p <= 60000


def test_pick_port_varies():
    assert len({_pick_port() for _ in range(20)}) > 1
