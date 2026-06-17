# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools.trex stream/packet/mode unit tests (offline: spec dicts)."""
import pytest

from pyte.tools.trex import (PktBuilder, Stream, TXCont, TXMultiBurst,
                             TXSingleBurst)


def test_pktbuilder_rejects_empty():
    with pytest.raises(ValueError, match="empty"):
        PktBuilder("   ")


def test_txcont_spec():
    assert TXCont(pps=1_000_000).spec() == {
        "type": "continuous", "pps": 1_000_000.0,
        "bps_l2": None, "percentage": None}


def test_txsingleburst_spec():
    assert TXSingleBurst(total_pkts=100, pps=500).spec() == {
        "type": "single_burst", "total_pkts": 100, "pps": 500.0}


def test_txmultiburst_spec():
    assert TXMultiBurst(pkts_per_burst=10, count=5, ibg=1000.0).spec() == {
        "type": "multi_burst", "pkts_per_burst": 10, "count": 5,
        "ibg": 1000.0, "pps": None}


def test_stream_spec_defaults():
    s = Stream(packet=PktBuilder("Ether()/IP()/UDP()"),
               mode=TXCont(pps=1000))
    assert s.spec() == {
        "name": None, "packet": "Ether()/IP()/UDP()", "vm": [],
        "mode": {"type": "continuous", "pps": 1000.0,
                 "bps_l2": None, "percentage": None},
        "pgid": None, "latency": False}


def test_stream_spec_with_flow_stats_and_vm():
    s = Stream(
        packet=PktBuilder("Ether()/IP()/UDP()",
                          vm=["STLVmFlowVar(name='x', min_value=0, "
                              "max_value=9, size=4, op='inc')"]),
        mode=TXCont(pps=1000), name="s1", flow_stats_pgid=7, latency=True)
    spec = s.spec()
    assert spec["name"] == "s1"
    assert spec["pgid"] == 7
    assert spec["latency"] is True
    assert spec["vm"] == ["STLVmFlowVar(name='x', min_value=0, "
                          "max_value=9, size=4, op='inc')"]
