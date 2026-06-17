# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools.trex stats parsing unit tests (offline: pinned fixtures)."""
import json
from pathlib import Path

import pytest

from pyte.tools.trex import GlobalStats, LatencyStats, PortStats
from pyte.tools.trex._stats import (parse_global_stats, parse_latency_stats,
                                    parse_port_stats)

DATA = Path(__file__).parent / "data"


def test_parse_port_stats():
    raw = json.loads((DATA / "trex_stats.json").read_text())
    ps = parse_port_stats(raw, 0)
    assert isinstance(ps, PortStats)
    assert ps.tx_pkts == 1000
    assert ps.rx_pkts == 998
    assert ps.tx_bps == pytest.approx(256000.0)
    assert ps.loss_pkts == 2
    assert ps.loss_pct == pytest.approx(0.2)


def test_parse_port_stats_zero_tx_no_div():
    raw = {"0": {"opackets": 0, "ipackets": 0, "obytes": 0, "ibytes": 0,
                 "tx_pps": 0.0, "rx_pps": 0.0, "tx_bps": 0.0, "rx_bps": 0.0}}
    ps = parse_port_stats(raw, 0)
    assert ps.loss_pct == 0.0


def test_parse_global_stats():
    raw = json.loads((DATA / "trex_stats.json").read_text())
    gs = parse_global_stats(raw)
    assert isinstance(gs, GlobalStats)
    assert gs.tx_bps == pytest.approx(511488.0)
    assert gs.cpu_util == pytest.approx(12.5)
    assert gs.queue_full == 3


def test_parse_latency_stats():
    raw = json.loads((DATA / "trex_pgid_stats.json").read_text())
    ls = parse_latency_stats(raw, 7)
    assert isinstance(ls, LatencyStats)
    assert ls.pg_id == 7
    assert ls.avg == pytest.approx(35.2)
    assert ls.min == pytest.approx(20.0)
    assert ls.max == pytest.approx(80.0)
    assert ls.jitter == pytest.approx(4.1)
    assert ls.dropped == 2
    assert ls.out_of_order == 1
