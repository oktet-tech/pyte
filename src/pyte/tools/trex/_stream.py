# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""TRex STL stream / packet / TX-mode descriptors.

Pure (no shim/TE imports). Each type renders a JSON-able ``spec()`` dict
that is shipped to the agent, where pyte.tools.trex._ops rebuilds the
native trex.stl.api objects. The packet is a Scapy expression string —
the native, most direct form (TRex profiles use Scapy directly); the
field-engine VM is a list of STLVm* expression strings.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Union


@dataclass(frozen=True)
class PktBuilder:
    """A packet: a Scapy expression string plus optional VM instructions."""

    #: e.g. "Ether()/IP(dst='10.0.0.2')/UDP(dport=80)/('x'*18)"
    scapy: str
    #: Optional STLVm* expression strings (the TRex field engine).
    vm: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.scapy.strip():
            raise ValueError("empty Scapy expression")


@dataclass(frozen=True)
class TXCont:
    """Continuous transmit (≈ STLTXCont). Set exactly one rate field."""

    pps: float | None = None
    bps_l2: float | None = None
    percentage: float | None = None

    def spec(self) -> dict:
        return {"type": "continuous",
                "pps": None if self.pps is None else float(self.pps),
                "bps_l2": None if self.bps_l2 is None else float(self.bps_l2),
                "percentage": None if self.percentage is None
                else float(self.percentage)}


@dataclass(frozen=True)
class TXSingleBurst:
    """A single burst of total_pkts (≈ STLTXSingleBurst)."""

    total_pkts: int
    pps: float | None = None

    def spec(self) -> dict:
        return {"type": "single_burst", "total_pkts": int(self.total_pkts),
                "pps": None if self.pps is None else float(self.pps)}


@dataclass(frozen=True)
class TXMultiBurst:
    """count bursts of pkts_per_burst, ibg µs apart (≈ STLTXMultiBurst)."""

    pkts_per_burst: int
    count: int
    ibg: float = 0.0
    pps: float | None = None

    def spec(self) -> dict:
        return {"type": "multi_burst",
                "pkts_per_burst": int(self.pkts_per_burst),
                "count": int(self.count), "ibg": float(self.ibg),
                "pps": None if self.pps is None else float(self.pps)}


TXMode = Union[TXCont, TXSingleBurst, TXMultiBurst]


@dataclass(frozen=True)
class Stream:
    """An STL stream (≈ STLStream): a packet + a TX mode."""

    packet: PktBuilder
    mode: TXMode
    name: str | None = None
    #: per-group stats id; enables STLFlowStats when set.
    flow_stats_pgid: int | None = None
    #: when True (and pgid set) use STLFlowLatencyStats instead.
    latency: bool = False

    def spec(self) -> dict:
        return {"name": self.name, "packet": self.packet.scapy,
                "vm": list(self.packet.vm), "mode": self.mode.spec(),
                "pgid": self.flow_stats_pgid, "latency": self.latency}
