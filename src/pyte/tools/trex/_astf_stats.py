# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Typed TRex ASTF statistics and parsers for the native stats dicts.

Pure (no shim or TE imports), so the counter arithmetic is testable
offline. The native get_stats()/get_traffic_stats() return JSON-able
dictionaries; after crossing pyte.remote their integer keys arrive as
strings, so parsers index with str(...).

A Series is the record of one traffic window: snapshots taken by
Client.poll(), with window()/mean()/median() for steady-state
arithmetic. Its shape deliberately mirrors
pyte.tools.trex.batch.Report so suite code reads the same on both
drivers.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field

#: The flow-table error counters observed on TRex 3.06
#: (tests/data/astf_traffic.json's server, probed with
#: skip_zero=False). This is documentation of the known set, not a
#: filter: TRex builds its error table from server-reported metadata
#: rather than a static list, so flow_table_errors() below matches on
#: the "err_" prefix instead of this tuple. A future TRex build can
#: add or rename counters without this tuple going stale in a way
#: that silently hides them.
FLOW_TABLE_ERR_NAMES = (
    "err_c_nf_throttled", "err_c_tuple_err", "err_cwf", "err_dct",
    "err_defer_no_template", "err_flow_overflow",
    "err_fragments_ipv4_drop", "err_l3_cs", "err_l4_cs", "err_len_err",
    "err_no_memory", "err_no_syn", "err_no_tcp_udp", "err_no_template",
    "err_redirect_rx", "err_rx_throttled", "err_s_nf_throttled",
)


@dataclass(frozen=True)
class AstfGlobal:
    """TRex aggregate counters for one moment in a run."""

    active_flows: int
    est_flows: int
    tx_bps: float
    rx_bps: float
    tx_pps: float
    rx_pps: float
    cpu_util: float
    queue_full: int


@dataclass(frozen=True)
class AstfTraffic:
    """Client-side and server-side ASTF counter families.

    The counters are kept as plain dictionaries because TRex's set
    varies by version; the properties below name the few this suite
    reasons about, and everything else stays reachable.
    """

    client: dict
    server: dict

    def _c(self, name: str) -> int:
        return int(self.client.get(name, 0))

    @property
    def connect_attempts(self) -> int:
        return self._c("tcps_connattempt") + self._c("udps_connects")

    @property
    def connects(self) -> int:
        return self._c("tcps_connects") + self._c("udps_connects")

    @property
    def closes(self) -> int:
        return self._c("tcps_closed") + self._c("udps_closed")

    @property
    def drops(self) -> int:
        return self._c("tcps_drops") + self._c("udps_keepdrops")

    @property
    def drop_pct(self) -> float:
        """Dropped connections as a percentage of those attempted.

        Zero when nothing was attempted: a run that generated no
        traffic is caught by its own verdict, not by dividing by zero
        here.
        """
        attempts = self.connect_attempts
        return 100.0 * self.drops / attempts if attempts else 0.0

    def flow_table_errors(self) -> dict[str, int]:
        """The non-zero flow-table error counters, either side.

        Matches every key (from either side's dictionary) whose name
        starts with "err_", plus "rss_redirect_drops", and reports it
        if the two sides' values sum to non-zero. This is
        deliberately not filtered against FLOW_TABLE_ERR_NAMES: that
        tuple is a fixed list captured from one TRex build, and
        get_traffic_stats() also mixes in five always-zero,
        non-counter section-header keys ("-", "Application",
        "Flow Table", "TCP", "UDP") that never match the "err_"
        prefix and are excluded by construction, not by the non-zero
        check alone.
        """
        names = sorted(set(self.client) | set(self.server))
        out = {}
        for name in names:
            if name != "rss_redirect_drops" and \
                    not name.startswith("err_"):
                continue
            value = int(self.client.get(name, 0)) + \
                int(self.server.get(name, 0))
            if value:
                out[name] = value
        return out


@dataclass(frozen=True)
class AstfLatency:
    """One port's latency measurement, microseconds.

    seq_errors is TRex's one rx-check counter for sequence anomalies
    on this stream: it fires for both a lost packet and a reordered
    one, so a non-zero value means "something anomalous happened",
    not "N packets were dropped" -- this layer does not let the
    suite tell the two apart. pkt_ok is the matching count of
    latency packets received in sequence.
    """

    port: int
    avg: float
    min: float
    max: float
    jitter: float
    seq_errors: int
    pkt_ok: int
    #: TRex's raw bucketed latency histogram: bucket lower bound in
    #: microseconds mapped to the count of samples in that bucket.
    #: Not percentile ranks -- this build does not report those at
    #: this call. Use percentile() to approximate one from here.
    histogram: dict[int, int]

    def percentile(self, p: float) -> float:
        """Approximate the p-th percentile from the bucket histogram.

        Resolution is limited by TRex's bucket widths, so treat the
        result as the bucket the percentile falls in rather than an
        exact figure. Returns 0.0 for an empty histogram.
        """
        if not 0.0 <= p <= 100.0:
            raise ValueError(f"percentile out of range 0..100: {p}")
        total = sum(self.histogram.values())
        if total == 0:
            return 0.0
        target = p / 100.0 * total
        cumulative = 0
        for bucket in sorted(self.histogram):
            cumulative += self.histogram[bucket]
            if cumulative >= target:
                return float(bucket)
        return float(max(self.histogram))


@dataclass(frozen=True)
class TemplateStats:
    """Counters attributed to one ASTF template group."""

    name: str
    counters: dict[str, int]


@dataclass(frozen=True)
class Snapshot:
    """One polled sample of a running ASTF session."""

    t: float
    glob: AstfGlobal
    traffic: AstfTraffic


@dataclass
class Series:
    """The snapshots taken during one traffic window."""

    samples: list[Snapshot] = field(default_factory=list)

    def add(self, snap: Snapshot) -> None:
        self.samples.append(snap)

    def window(self, t0: float, t1: float) -> list[Snapshot]:
        """Snapshots with t0 <= t <= t1, both bounds inclusive."""
        return [s for s in self.samples if t0 <= s.t <= t1]

    def _values(self, attr: str, t0: float, t1: float) -> list[float]:
        return [float(getattr(s.glob, attr))
                for s in self.window(t0, t1)]

    def mean(self, attr: str, t0: float, t1: float) -> float:
        """Mean of an AstfGlobal attribute over a window; 0.0 if empty."""
        vals = self._values(attr, t0, t1)
        return statistics.fmean(vals) if vals else 0.0

    def median(self, attr: str, t0: float, t1: float) -> float:
        """Median of an AstfGlobal attribute over a window; 0.0 if
        empty.
        """
        vals = self._values(attr, t0, t1)
        return statistics.median(vals) if vals else 0.0


def parse_global(raw: dict) -> AstfGlobal:
    """Build AstfGlobal from a native get_stats() dictionary.

    active_flows lives at raw['global']['active_flows'] (a single
    aggregate float); there is no sibling 'est_flows' at that level in
    the real TRex 3.06 return (tests/data/astf_global.json). The
    per-side flow-establishment counter instead lives at
    raw['traffic']['client']['m_est_flows'], beside 'm_active_flows';
    it defaults to 0 when that path is absent (e.g. a caller that
    passes only the 'global' sub-dictionary).
    """
    g = raw.get("global", raw)
    try:
        est_flows = int(raw["traffic"]["client"]["m_est_flows"])
    except (KeyError, TypeError):
        est_flows = 0
    return AstfGlobal(
        active_flows=int(g.get("active_flows", 0)),
        est_flows=est_flows,
        tx_bps=float(g.get("tx_bps", 0.0)),
        rx_bps=float(g.get("rx_bps", 0.0)),
        tx_pps=float(g.get("tx_pps", 0.0)),
        rx_pps=float(g.get("rx_pps", 0.0)),
        cpu_util=float(g.get("cpu_util", 0.0)),
        queue_full=int(g.get("queue_full", 0)))


def parse_traffic(raw: dict) -> AstfTraffic:
    """Build AstfTraffic from a native get_traffic_stats() dictionary."""
    return AstfTraffic(client=dict(raw.get("client", {})),
                        server=dict(raw.get("server", {})))


def parse_latency(raw: dict, port: int) -> AstfLatency:
    """Build AstfLatency for one port from get_latency_stats().

    The real TRex 3.06 return (tests/data/astf_latency.json) is keyed
    directly by the port number (as a string), each entry holding
    'hist' and 'stats' sub-dictionaries; there is no 'latency' or
    'err_cntrs' wrapper. 'hist' carries the running latency figures
    (microseconds) and the raw bucketed histogram ('key' = bucket
    lower bound in usec, 'val' = count in that bucket); this build
    does not report percentile ranks at this call, so 'histogram'
    keeps the raw buckets and AstfLatency.percentile() approximates a
    percentile from them. 'stats' carries the per-flow rx-check
    counters: 'm_seq_error' and 'm_pkt_ok' are the two read below (see
    AstfLatency's docstring for what 'seq_errors' does and does not
    distinguish).
    """
    entry = raw[str(port)]
    hist = entry.get("hist", {})
    stats = entry.get("stats", {})
    histogram = hist.get("histogram", [])
    return AstfLatency(
        port=port,
        avg=float(hist.get("s_avg", 0.0)),
        min=float(hist.get("min_usec", 0.0)),
        max=float(hist.get("max_usec", 0.0)),
        jitter=float(stats.get("m_jitter", 0.0)),
        seq_errors=int(stats.get("m_seq_error", 0)),
        pkt_ok=int(stats.get("m_pkt_ok", 0)),
        histogram={int(bucket["key"]): int(bucket["val"])
                   for bucket in histogram})


def parse_tg_stats(raw: dict) -> list[TemplateStats]:
    """Build per-template-group stats from get_traffic_tg_stats()."""
    return [TemplateStats(name=name, counters=dict(counters))
            for name, counters in sorted(raw.items())]
