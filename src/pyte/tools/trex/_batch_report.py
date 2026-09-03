# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools.trex._batch_report - batch (ASTF) TRex report model + series math.

Port of te/lib/tapi_tool/tapi_trex.c's report-building and series/window
math. Pinned to the same tapi_trex.c snapshot as ``_batch_filters``:

- unit list + averaging (``get_avg_from_filter``): :1821-1890
- single-value readers (``get_single_str/uint64/uint64_opt/double``):
  :1892-2017
- per-port stat report fill (``tapi_trex_get_report_port_stat``):
  :2037-2122
- global stat report fill (``tapi_trex_get_report_global_stat``):
  :2124-2210
- optional-counter report fill (``tapi_trex_optional_flts_process``):
  :2212-2248
- ``tapi_trex_get_report``: :2250-2309
- derived per-port series (``tapi_trex_port_stat_param_series_get`` and
  the ``_time_series_get`` / ``_series_by_time_get`` inline wrappers in
  tapi_trex.h:1052-1084): tapi_trex.c:2371-2457
- windowed stats (``tapi_trex_port_stat_data_get``): :2474-2560

This module does not talk to any job or filter: it consumes plain,
already-matched string lists (:class:`BatchFilters`) and produces a
:class:`Report`.  Attaching real ``tapi_job`` filters and feeding this
container from them is Task 6's job; :class:`BatchFilters` is designed
so it can be built either from a hand-written test fixture (as done in
this module's tests) or from live job filter reads, without either
producer caring about the other.
"""
from __future__ import annotations

import dataclasses
import enum
import sys
import warnings

from pyte import log
from pyte.errors import TrexBatchError
from pyte.tools.trex import _batch_filters as _flt

# Matches C's DBL_EPSILON tolerance in tapi_trex_port_stat_data_get
# (tapi_trex.c:2501-2512) for the "is time_start/time_end inside this
# sample interval" comparisons.
_EPS = sys.float_info.epsilon


class PortParam(enum.Enum):
    """Per-port statistics parameter (tapi_trex_port_stat_enum).

    Member values are the exact row names used by ``_batch_filters``'
    ``PORT_STAT_ROWS``/``PORT_TIME_ROWS`` tables, so callers can go
    from one to the other without a second lookup table.
    """
    OPKTS = "opackets"
    OBYTES = "obytes"
    IPKTS = "ipackets"
    IBYTES = "ibytes"
    IERRS = "ierrors"
    OERRS = "oerrors"
    CURR_TIME = "current time"
    TEST_DUR = "test duration"


# The two groups port_series is assembled from: PORT_STAT_ROWS members
# read one raw string per port per sample; PORT_TIME_ROWS members read
# one raw string per sample (see the DIVERGENCE note on
# _build_port_series below).
_PORT_STAT_PARAMS = (PortParam.OPKTS, PortParam.OBYTES, PortParam.IPKTS,
                     PortParam.IBYTES, PortParam.IERRS, PortParam.OERRS)
_PORT_TIME_PARAMS = (PortParam.CURR_TIME, PortParam.TEST_DUR)


class NoPortStats(TrexBatchError):
    """No per-port statistics available (C TE_ENODATA equivalent).

    Raised by :meth:`Report.time_series`, :meth:`Report.series_by_time`
    and :meth:`Report.window` when ``port_series`` is ``None`` - i.e.
    the batch run was not started with ``--iom 1`` (tapi_trex.c:2490-
    2496 checks the same condition via the time series being empty).
    """


class WindowClamped(Warning):
    """A :meth:`Report.window` time bound falls outside the sampled range.

    Mirrors the C TE_ERANGE path (tapi_trex.c:2514-2527): rather than
    failing, the out-of-range bound is clamped to the first/last
    sample and a warning is issued.
    """


@dataclasses.dataclass
class BatchFilters:
    """Pre-parsed TRex batch stdout messages, grouped like the regex tables.

    Each field holds plain strings exactly as a ``tapi_job`` filter
    would deliver them (the raw regex capture groups, not yet
    converted to numbers) - conversion is :func:`build_report`'s job.
    Fields are keyed the same way as the corresponding table in
    :mod:`pyte.tools.trex._batch_filters`, so building one from a set
    of filter reads is a direct name-for-name transcription.

    :ivar summary:
        ``_batch_filters.SUMMARY`` name -> list of raw captures, in
        encounter order. ``total_tx``/``total_rx``/``total_cps`` are
        periodic (one entry per sample, averaged by
        :func:`build_report`); ``tx_pkts``/``rx_pkts``/``tx_bytes``/
        ``rx_bytes`` occur once (only the last entry is used).
    :ivar m_traff_dur:
        one ``(client_raw, server_raw)`` tuple per
        ``_batch_filters.M_TRAFF_DUR`` match, in encounter order (only
        the last is used - mirrors ``get_single_double``).
    :ivar opt_counters:
        ``_batch_filters.OPT_COUNTERS`` name -> list of
        ``(client_raw, server_raw)`` tuples, in encounter order (only
        the last is used).  A name never observed defaults to
        ``(0, 0)`` in the built report, matching
        ``get_single_uint64_opt``'s eos-only-means-zero path.
    :ivar port_stat:
        ``_batch_filters.PORT_STAT_ROWS`` name -> list of per-sample
        tuples of raw per-port strings (one tuple per periodic
        sample, one string per port).
    :ivar port_time:
        ``_batch_filters.PORT_TIME_ROWS`` name -> list of raw strings,
        one per periodic sample.  DIVERGENCE: the C code attaches
        ``n_ports`` identical filters for CURRENT_TIME/TEST_DURATION
        and reads the same line ``n_ports`` times per sample
        (tapi_trex.c:1364-1411); here it is collected once per sample
        and broadcast across ports when the series is built.
    :ivar global_stats:
        ``_batch_filters.GLOBAL_STATS`` name -> list of raw strings,
        one per periodic sample.
    """
    summary: dict[str, list[str]] = dataclasses.field(default_factory=dict)
    m_traff_dur: list[tuple[str, str]] = dataclasses.field(
        default_factory=list)
    opt_counters: dict[str, list[tuple[str, str]]] = dataclasses.field(
        default_factory=dict)
    port_stat: dict[str, list[tuple[str, ...]]] = dataclasses.field(
        default_factory=dict)
    port_time: dict[str, list[str]] = dataclasses.field(default_factory=dict)
    global_stats: dict[str, list[str]] = dataclasses.field(
        default_factory=dict)


@dataclasses.dataclass
class Report:
    """A parsed TRex batch (ASTF) run report (mirrors tapi_trex_report)."""
    avg_tx: float
    avg_rx: float
    avg_cps: float
    tx_pkts: int
    rx_pkts: int
    tx_bytes: int
    rx_bytes: int
    m_traff_dur_cl: float
    m_traff_dur_srv: float
    opt_cl: dict[str, int]
    opt_srv: dict[str, int]
    # [sample][port] floats, keyed by PortParam; None unless the run
    # used --iom 1 (tapi_trex.c:1644-1650 gates both per-port and
    # global stat filters on the same condition).
    port_series: dict[PortParam, list[list[float]]] | None
    global_series: dict[str, list[float]] | None

    def time_series(self) -> list[float]:
        """The sample times (CURR_TIME, port 0) (tapi_trex.h:1059-1066).

        Port 0 is used arbitrarily: CURR_TIME is collected once per
        sample and broadcast to every port when the series is built,
        so any port index gives the same values.

        :raises NoPortStats: ``port_series`` is ``None``.
        """
        if self.port_series is None:
            raise NoPortStats(
                "no per-port statistics (was --iom 1 used?)")
        return [sample[0] for sample in self.port_series[PortParam.CURR_TIME]]

    def series_by_time(self, param: PortParam, port: int) -> list[float]:
        """The rate-of-change series for ``param`` at ``port``.

        First differences of the raw per-sample values, divided by the
        time delta between samples (tapi_trex.c:2413-2452,
        ``absolute_value=False, by_time=True``). Sample 0 is diffed
        against an implicit zero value at an implicit time of zero, so
        its "delta" time is simply its own CURR_TIME.

        :raises NoPortStats: ``port_series`` is ``None``.
        """
        if self.port_series is None:
            raise NoPortStats(
                "no per-port statistics (was --iom 1 used?)")
        values = self.port_series[param]
        times = self.time_series()

        rates: list[float] = []
        prev_val = 0.0
        prev_time = 0.0
        for val, time in zip((sample[port] for sample in values), times):
            rates.append(_rate(val - prev_val, time - prev_time))
            prev_val = val
            prev_time = time
        return rates

    def window(self, param: PortParam, port: int, t0: float,
               t1: float) -> tuple[float, float, float, float]:
        """(min, avg, median, max) of the rate series inside [t0, t1].

        Mirrors ``tapi_trex_port_stat_data_get`` (tapi_trex.c:2474-
        2560): the window is found in the *time* series and applied to
        the *rate* series (:meth:`series_by_time`), sorted
        descending, then::

            min    = last element (smallest)
            max    = first element (largest)
            avg    = arithmetic mean
            median = sorted[len // 2]

        DIVERGENCE note: that ``median`` is C's ``qsort`` + integer
        division on the descending array, not a mathematically proper
        median - reproduced verbatim, not "fixed".

        A ``t0``/``t1`` bound that falls outside the sampled range
        warns (:class:`WindowClamped`, via ``warnings.warn`` and
        ``pyte.log.warn``) and clamps to the first/last sample instead
        of failing.

        :raises NoPortStats: ``port_series`` is ``None``.
        """
        if self.port_series is None:
            raise NoPortStats(
                "no per-port statistics (was --iom 1 used?)")
        assert t0 < t1, "window() requires t0 < t1"

        times = self.time_series()
        n = len(times)
        if n == 0:
            raise NoPortStats("no periodic samples available")

        i_start = None
        i_end = None
        for i in range(n - 1):
            if t0 - times[i] > -_EPS and times[i + 1] - t0 > _EPS:
                i_start = i
            if t1 - times[i] > -_EPS and times[i + 1] - t1 > _EPS:
                i_end = i

        if i_start is None:
            msg = (f"window(): cannot find start time > {t0}, "
                   "using first element")
            log.warn(msg)
            warnings.warn(msg, WindowClamped)
            i_start = 0
        if i_end is None:
            msg = (f"window(): cannot find end time > {t1}, "
                   "using last element")
            log.warn(msg)
            warnings.warn(msg, WindowClamped)
            i_end = n - 1

        # DIVERGENCE: C asserts n_meds < n_vals here (tapi_trex.c:2533),
        # which would abort on a full-range window (i_start == 0 and
        # i_end == n - 1, so n_meds == n_vals) - a debug-only sanity
        # check, not a real invariant, deliberately not reproduced.
        # Without it a full-range window is simply a safe superset.
        rates = self.series_by_time(param, port)
        vals = sorted(rates[i_start:i_end + 1], reverse=True)
        n_vals = len(vals)
        lo = vals[n_vals - 1]
        hi = vals[0]
        avg = sum(vals) / n_vals
        median = vals[n_vals // 2]
        return lo, avg, median, hi


def _rate(diff: float, dt: float) -> float:
    """``diff / dt`` with C's IEEE-754 float-division semantics.

    DIVERGENCE: C leaves a same-timestamp sample (``dt == 0``) as
    plain float division, producing +-inf or nan silently; Python
    raises ZeroDivisionError for the same operation, so it is
    special-cased here instead of letting it propagate.
    """
    if dt == 0.0:
        if diff == 0.0:
            return float("nan")
        return float("inf") if diff > 0 else float("-inf")
    return diff / dt


def _avg(raw: list[str]) -> float:
    """Arithmetic mean of KMGT-scaled tokens (``get_avg_from_filter``).

    DIVERGENCE: fewer than one sample returns 0.0 explicitly; the C
    code leaves its running total divided by an uninitialized counter
    in that case (tapi_trex.c:1861-1889 -- ``bufs_n < 2`` warns and
    jumps to ``cleanup`` where ``num`` was never assigned).
    """
    if not raw:
        return 0.0
    return sum(_flt.parse_units(v) for v in raw) / len(raw)


def _single_uint(raw: list[str]) -> int:
    """The single (last-seen) integer value (``get_single_uint64``)."""
    if not raw:
        return 0
    return int(raw[-1])


def _build_port_series(
        filters: BatchFilters) -> dict[PortParam, list[list[float]]] | None:
    has_data = (any(filters.port_stat.values())
                or any(filters.port_time.values()))
    if not has_data:
        return None

    n_ports = 1
    for rows in filters.port_stat.values():
        if rows:
            n_ports = len(rows[0])
            break

    series: dict[PortParam, list[list[float]]] = {}
    for param in _PORT_STAT_PARAMS:
        rows = filters.port_stat.get(param.value, [])
        series[param] = [[float(v) for v in row] for row in rows]
    for param in _PORT_TIME_PARAMS:
        # DIVERGENCE: collected once per sample, broadcast across all
        # ports here rather than read n_ports times as in C (see the
        # BatchFilters.port_time docstring).
        raw = filters.port_time.get(param.value, [])
        series[param] = [[float(v)] * n_ports for v in raw]
    return series


def _build_global_series(
        filters: BatchFilters) -> dict[str, list[float]] | None:
    if not any(filters.global_stats.values()):
        return None

    series: dict[str, list[float]] = {}
    for name in _flt.GLOBAL_STATS:
        raw = filters.global_stats.get(name, [])
        if name in ("current time", "test duration"):
            series[name] = [float(v) for v in raw]
        else:
            series[name] = [_flt.parse_units(v) for v in raw]
    return series


def build_report(filters: BatchFilters) -> Report:
    """Build a :class:`Report` from pre-parsed stdout messages.

    Mirrors ``tapi_trex_get_report`` (tapi_trex.c:2250-2309).
    """
    avg_tx = _avg(filters.summary.get("total_tx", []))
    avg_rx = _avg(filters.summary.get("total_rx", []))
    avg_cps = _avg(filters.summary.get("total_cps", []))

    tx_pkts = _single_uint(filters.summary.get("tx_pkts", []))
    rx_pkts = _single_uint(filters.summary.get("rx_pkts", []))
    tx_bytes = _single_uint(filters.summary.get("tx_bytes", []))
    rx_bytes = _single_uint(filters.summary.get("rx_bytes", []))

    if filters.m_traff_dur:
        cl_raw, srv_raw = filters.m_traff_dur[-1]
        m_traff_dur_cl = _flt.parse_units(cl_raw)
        m_traff_dur_srv = _flt.parse_units(srv_raw)
    else:
        m_traff_dur_cl = 0.0
        m_traff_dur_srv = 0.0

    opt_cl: dict[str, int] = {}
    opt_srv: dict[str, int] = {}
    for name in _flt.OPT_COUNTERS:
        pairs = filters.opt_counters.get(name)
        if pairs:
            cl_raw, srv_raw = pairs[-1]
            opt_cl[name] = int(cl_raw)
            opt_srv[name] = int(srv_raw)
        else:
            opt_cl[name] = 0
            opt_srv[name] = 0

    return Report(
        avg_tx=avg_tx, avg_rx=avg_rx, avg_cps=avg_cps,
        tx_pkts=tx_pkts, rx_pkts=rx_pkts,
        tx_bytes=tx_bytes, rx_bytes=rx_bytes,
        m_traff_dur_cl=m_traff_dur_cl, m_traff_dur_srv=m_traff_dur_srv,
        opt_cl=opt_cl, opt_srv=opt_srv,
        port_series=_build_port_series(filters),
        global_series=_build_global_series(filters),
    )
