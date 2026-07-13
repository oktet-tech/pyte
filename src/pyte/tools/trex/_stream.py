# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""TRex STL stream / packet / TX-mode descriptors.

No shim/TE imports. Each type renders a JSON-able ``spec()`` dict shipped
to the agent, where pyte.tools.trex._ops rebuilds the native trex.stl.api
objects. The packet is a real Scapy packet built on the engine (pyte
depends on Scapy); ``spec()`` ships its wire bytes (base64) so the agent
needs no Scapy and never evaluates packet-describing code. The
field-engine VM is the one exception: STLVm* has no engine
representation (it lives only in the bundled trex lib), so it stays a
list of expression strings evaluated agent-side — restricted to
``STLVm*`` constructors in the trex.stl.api namespace with no builtins
(see ``_ops.add_streams``). In wire-bytes mode its packet offsets must
be numeric.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Union

if TYPE_CHECKING:
    from scapy.packet import Packet


@dataclass(frozen=True)
class PktBuilder:
    """A packet: an engine-built Scapy packet plus optional VM instructions."""

    #: A Scapy packet, e.g. ``Ether()/IP(dst="10.0.0.2")/UDP(dport=80)/("x"*18)``
    pkt: "Packet"
    #: Optional STLVm* expression strings (TRex field engine, agent-side).
    #: With wire-bytes packets, VM packet offsets must be numeric.
    vm: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if isinstance(self.pkt, (str, bytes)):
            raise TypeError(
                "PktBuilder.pkt must be a Scapy packet object, not a "
                "string; build it with scapy (e.g. Ether()/IP()/UDP())")

    def wire_bytes(self) -> bytes:
        """The packet's wire bytes (what gets shipped to the agent)."""
        return bytes(self.pkt)

    def summary(self) -> str:
        """Scapy's one-line packet summary (for logging)."""
        return self.pkt.summary()

    def spec(self) -> dict:
        raw = bytes(self.pkt)
        return {"pkt_b64": base64.b64encode(raw).decode("ascii"),
                "summary": self.pkt.summary(), "len": len(raw),
                "vm": list(self.vm)}


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
        pkt = self.packet.spec()
        return {"name": self.name, "pkt_b64": pkt["pkt_b64"],
                "summary": pkt["summary"], "len": pkt["len"],
                "vm": pkt["vm"], "mode": self.mode.spec(),
                "pgid": self.flow_stats_pgid, "latency": self.latency}
