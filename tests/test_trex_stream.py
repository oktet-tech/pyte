# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools.trex stream/packet/mode unit tests (offline: spec dicts)."""
import base64

import pytest
from scapy.all import IP, UDP, Ether

from pyte.tools.trex import (PktBuilder, Stream, TXCont, TXMultiBurst,
                             TXSingleBurst)


def test_pktbuilder_rejects_string():
    with pytest.raises(TypeError, match="Scapy packet"):
        PktBuilder("Ether()/IP()/UDP()")


def test_pktbuilder_spec_ships_wire_bytes():
    pkt = Ether() / IP() / UDP()
    spec = PktBuilder(pkt).spec()
    assert base64.b64decode(spec["pkt_b64"]) == bytes(pkt)
    assert spec["len"] == len(bytes(pkt))
    assert spec["vm"] == []
    assert spec["summary"] == pkt.summary()


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
    pkt = Ether() / IP() / UDP()
    s = Stream(packet=PktBuilder(pkt), mode=TXCont(pps=1000))
    spec = s.spec()
    assert spec["name"] is None
    assert base64.b64decode(spec["pkt_b64"]) == bytes(pkt)
    assert spec["len"] == len(bytes(pkt))
    assert spec["vm"] == []
    assert spec["mode"] == {"type": "continuous", "pps": 1000.0,
                            "bps_l2": None, "percentage": None}
    assert spec["pgid"] is None
    assert spec["latency"] is False


def test_stream_spec_with_flow_stats_and_vm():
    pkt = Ether() / IP() / UDP()
    s = Stream(
        packet=PktBuilder(pkt,
                          vm=["STLVmFlowVar(name='x', min_value=0, "
                              "max_value=9, size=4, op='inc')"]),
        mode=TXCont(pps=1000), name="s1", flow_stats_pgid=7, latency=True)
    spec = s.spec()
    assert spec["name"] == "s1"
    assert spec["pgid"] == 7
    assert spec["latency"] is True
    assert spec["vm"] == ["STLVmFlowVar(name='x', min_value=0, "
                          "max_value=9, size=4, op='inc')"]
