# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Typed TRex STL statistics + parsers for the native get_stats() dicts.

Pure (no shim/TE imports). The native get_stats()/get_pgid_stats() return
JSON-able dicts; after crossing pyte.remote their integer port/pg_id keys
arrive as strings, so parsers index with str(...).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PortStats:
    """One TRex port's counters."""

    tx_pkts: int
    rx_pkts: int
    tx_bytes: int
    rx_bytes: int
    tx_pps: float
    rx_pps: float
    tx_bps: float
    rx_bps: float

    @property
    def loss_pkts(self) -> int:
        return max(self.tx_pkts - self.rx_pkts, 0)

    @property
    def loss_pct(self) -> float:
        return 100.0 * self.loss_pkts / self.tx_pkts if self.tx_pkts else 0.0


@dataclass(frozen=True)
class GlobalStats:
    """TRex aggregate counters."""

    tx_bps: float
    rx_bps: float
    tx_pps: float
    rx_pps: float
    cpu_util: float
    queue_full: int


@dataclass(frozen=True)
class LatencyStats:
    """Per-pg_id latency + error counters (STLFlowLatencyStats)."""

    pg_id: int
    avg: float
    min: float
    max: float
    jitter: float
    dropped: int
    out_of_order: int


def parse_port_stats(stats: dict, port: int) -> PortStats:
    """Build PortStats for ``port`` from a native get_stats() dict."""
    p = stats[str(port)]
    return PortStats(
        tx_pkts=int(p["opackets"]), rx_pkts=int(p["ipackets"]),
        tx_bytes=int(p["obytes"]), rx_bytes=int(p["ibytes"]),
        tx_pps=float(p["tx_pps"]), rx_pps=float(p["rx_pps"]),
        tx_bps=float(p["tx_bps"]), rx_bps=float(p["rx_bps"]))


def parse_global_stats(stats: dict) -> GlobalStats:
    """Build GlobalStats from the ``global`` entry of a get_stats() dict."""
    g = stats["global"]
    return GlobalStats(
        tx_bps=float(g["tx_bps"]), rx_bps=float(g["rx_bps"]),
        tx_pps=float(g["tx_pps"]), rx_pps=float(g["rx_pps"]),
        cpu_util=float(g.get("cpu_util", 0.0)),
        queue_full=int(g.get("queue_full", 0)))


def parse_latency_stats(pgid_stats: dict, pg_id: int) -> LatencyStats:
    """Build LatencyStats for ``pg_id`` from a get_pgid_stats() dict."""
    entry = pgid_stats["latency"][str(pg_id)]
    lat = entry["latency"]
    err = entry.get("err_cntrs", {})
    return LatencyStats(
        pg_id=pg_id, avg=float(lat["average"]),
        min=float(lat["total_min"]), max=float(lat["total_max"]),
        jitter=float(lat["jitter"]), dropped=int(err.get("dropped", 0)),
        out_of_order=int(err.get("out_of_order", 0)))
