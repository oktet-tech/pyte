# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools.trex._batch_report unit tests (offline, hand-computed math).

Step 1-4 tests build :class:`Report` objects directly from pre-parsed
series (no stdout parsing) and hand-check the series/window math
against tapi_trex.c:2371-2560. The end-to-end test at the bottom feeds
a synthetic TRex stdout fixture through the ``_batch_filters`` regex
tables into a :class:`BatchFilters`, then :func:`build_report`.
"""
import re
import warnings

import pytest

from pyte.tools.trex import _batch_filters as flt
from pyte.tools.trex import _batch_report as rpt


# --------------------------------------------------------------------
# A hand-computed 6-sample, 2-port OBYTES series, at 1-second
# intervals, used by the window()/series_by_time() tests below.
#
#   sample:      0     1     2     3     4     5
#   time:      1.0   2.0   3.0   4.0   5.0   6.0
#   obytes p0:  100   300   750  1050  1450  2000
#   obytes p1: (irrelevant to these tests; port 0 only)
#
# rate[i] = (obytes[i] - obytes[i-1]) / (time[i] - time[i-1]), with
# sample 0 diffed against 0 at dt = time[0] (tapi_trex.c:2438-2452):
#   rate = [100, 200, 450, 300, 400, 550]
# --------------------------------------------------------------------
_TIMES = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
_OBYTES_P0 = [100.0, 300.0, 750.0, 1050.0, 1450.0, 2000.0]
_RATES_P0 = [100.0, 200.0, 450.0, 300.0, 400.0, 550.0]


def _series_report() -> rpt.Report:
    port_series = {
        rpt.PortParam.CURR_TIME: [[t, t] for t in _TIMES],
        rpt.PortParam.OBYTES: [[v, v + 1.0] for v in _OBYTES_P0],
    }
    return rpt.Report(
        avg_tx=0.0, avg_rx=0.0, avg_cps=0.0,
        tx_pkts=0, rx_pkts=0, tx_bytes=0, rx_bytes=0,
        m_traff_dur_cl=0.0, m_traff_dur_srv=0.0,
        opt_cl={}, opt_srv={},
        port_series=port_series, global_series=None,
    )


def test_time_series_is_curr_time_port_0():
    assert _series_report().time_series() == _TIMES


def test_series_by_time_first_sample_diffed_against_zero():
    rates = _series_report().series_by_time(rpt.PortParam.OBYTES, 0)
    assert rates == pytest.approx(_RATES_P0)


def test_window_in_range_no_clamp_no_warning():
    report = _series_report()
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        lo, avg, median, hi = report.window(rpt.PortParam.OBYTES, 0,
                                            2.5, 4.5)
    # window covers samples 1..3 -> rates [200, 450, 300]
    # sorted desc: [450, 300, 200]; min=200 max=450
    # avg = (450+300+200)/3 = 316.666...; median = sorted[3 // 2] = 300
    assert lo == pytest.approx(200.0)
    assert hi == pytest.approx(450.0)
    assert avg == pytest.approx(950.0 / 3)
    assert median == pytest.approx(300.0)


def test_window_out_of_range_clamps_and_warns():
    report = _series_report()
    with pytest.warns(rpt.WindowClamped):
        lo, avg, median, hi = report.window(rpt.PortParam.OBYTES, 0,
                                            0.5, 6.5)
    # clamped to the full range -> rates [100,200,450,300,400,550]
    # sorted desc: [550,450,400,300,200,100]; min=100 max=550
    # avg = 2000/6 = 333.333...; median = sorted[6 // 2] = 300
    assert lo == pytest.approx(100.0)
    assert hi == pytest.approx(550.0)
    assert avg == pytest.approx(2000.0 / 6)
    assert median == pytest.approx(300.0)


def test_window_no_port_stats_raises():
    report = rpt.Report(
        avg_tx=0.0, avg_rx=0.0, avg_cps=0.0,
        tx_pkts=0, rx_pkts=0, tx_bytes=0, rx_bytes=0,
        m_traff_dur_cl=0.0, m_traff_dur_srv=0.0,
        opt_cl={}, opt_srv={},
        port_series=None, global_series=None,
    )
    with pytest.raises(rpt.NoPortStats):
        report.window(rpt.PortParam.OBYTES, 0, 0.0, 1.0)


def test_no_port_stats_is_a_trex_batch_error():
    from pyte.errors import TrexBatchError
    assert issubclass(rpt.NoPortStats, TrexBatchError)


def test_window_clamped_is_a_warning():
    assert issubclass(rpt.WindowClamped, Warning)


def test_build_report_empty_averaging_returns_zero():
    filters = rpt.BatchFilters(
        summary={
            "tx_pkts": ["1"], "rx_pkts": ["1"],
            "tx_bytes": ["1"], "rx_bytes": ["1"],
        },
    )
    report = rpt.build_report(filters)
    # DIVERGENCE: C reads an uninitialized `num` here; we return 0.0.
    assert report.avg_tx == 0.0
    assert report.avg_rx == 0.0
    assert report.avg_cps == 0.0


def test_build_report_averages_multiple_samples():
    filters = rpt.BatchFilters(
        summary={
            "total_tx": ["10.00 M", "14.00 M"],
            "tx_pkts": ["1"], "rx_pkts": ["1"],
            "tx_bytes": ["1"], "rx_bytes": ["1"],
        },
    )
    report = rpt.build_report(filters)
    assert report.avg_tx == pytest.approx(12.0e6)


def test_build_report_port_series_none_without_port_data():
    filters = rpt.BatchFilters(
        summary={
            "tx_pkts": ["1"], "rx_pkts": ["1"],
            "tx_bytes": ["1"], "rx_bytes": ["1"],
        },
    )
    report = rpt.build_report(filters)
    assert report.port_series is None
    assert report.global_series is None


def test_opt_counters_default_to_zero_when_absent():
    filters = rpt.BatchFilters(
        summary={
            "tx_pkts": ["1"], "rx_pkts": ["1"],
            "tx_bytes": ["1"], "rx_bytes": ["1"],
        },
    )
    report = rpt.build_report(filters)
    assert report.opt_cl["tcps_connattempt"] == 0
    assert report.opt_srv["tcps_connattempt"] == 0
    assert set(report.opt_cl) == set(flt.OPT_COUNTERS)


# --------------------------------------------------------------------
# Step 5: end-to-end parse test. A synthetic TRex batch stdout fixture
# (2 ports, 3 samples of the --iom 1 per-port table, plus a final
# summary section with averaged totals, single counts, m_traffic_duration
# and two optional counters) is parsed line-by-line through the
# _batch_filters regex tables (as a real job filter would, one match
# per line) into a BatchFilters, then built into a Report.
# --------------------------------------------------------------------
_FIXTURE = """\
current time            : 1.000 sec
opackets            |      100 |      140
obytes              |     1000 |     1400
ipackets            |       90 |      130
ibytes              |      900 |     1300
ierrors             |        0 |        0
oerrors             |        0 |        0
test duration        : 20.000 sec
current time            : 2.000 sec
opackets            |      300 |      340
obytes              |     3000 |     3400
ipackets            |      270 |      310
ibytes              |     2700 |     3100
ierrors             |        0 |        1
oerrors             |        0 |        0
test duration        : 20.000 sec
current time            : 3.000 sec
opackets            |      750 |      800
obytes              |     7500 |     8000
ipackets            |      700 |      760
ibytes              |     7000 |     7600
ierrors             |        1 |        1
oerrors             |        0 |        1
test duration        : 20.000 sec
Total-Tx               :     10.00 Mbps
Total-Rx               :      8.00 Mbps
Total-CPS              :      1.00 Kcps
Total-Tx               :     14.00 Mbps
Total-Rx               :     12.00 Mbps
Total-CPS              :      3.00 Kcps
Total-tx-pkt           :      98765 pkts
Total-rx-pkt           :      87654 pkts
Total-tx-bytes         :      123456789 byte
Total-rx-bytes         :      112233445 byte
   m_traffic_duration    |    5.00 Ksec    |    6.00 Msec    |    measured traffic duration
 tcps_connattempt  | 25519 | 0 | connections initiated
 tcps_conndrops     | 3 | 0 | *embryonic connections dropped
"""


def _parse_fixture(text: str, n_ports: int) -> rpt.BatchFilters:
    """Feed ``text`` through the _batch_filters tables, line by line.

    Mirrors how a real tapi_job filter sees one already-split line per
    message; this is a stand-in for Task 6's job-filter wiring.
    """
    filters = rpt.BatchFilters()
    lines = text.splitlines()

    for name, (regex, group) in flt.SUMMARY.items():
        for line in lines:
            m = re.search(regex, line)
            if m:
                filters.summary.setdefault(name, []).append(m.group(group))

    for line in lines:
        m = re.search(flt.M_TRAFF_DUR, line)
        if m:
            filters.m_traff_dur.append(m.groups())

    for name in flt.OPT_COUNTERS:
        regex = flt.OPT_COUNTER_RE(name, name in flt.OPT_COUNTERS_ERR)
        for line in lines:
            m = re.search(regex, line)
            if m:
                filters.opt_counters.setdefault(name, []).append(m.groups())

    for name in flt.PORT_STAT_ROWS:
        regex = flt.port_stat_re(name, n_ports)
        for line in lines:
            m = re.search(regex, line)
            if m:
                filters.port_stat.setdefault(name, []).append(m.groups())

    for name in flt.PORT_TIME_ROWS:
        regex = flt.port_time_re(name)
        for line in lines:
            m = re.search(regex, line)
            if m:
                filters.port_time.setdefault(name, []).append(m.group(1))

    return filters


def test_end_to_end_parse_and_build_report():
    filters = _parse_fixture(_FIXTURE, n_ports=2)
    report = rpt.build_report(filters)

    assert report.avg_tx == pytest.approx(12.0e6)
    assert report.avg_rx == pytest.approx(10.0e6)
    assert report.avg_cps == pytest.approx(2.0e3)

    assert report.tx_pkts == 98765
    assert report.rx_pkts == 87654
    assert report.tx_bytes == 123456789
    assert report.rx_bytes == 112233445

    assert report.m_traff_dur_cl == pytest.approx(5000.0)
    assert report.m_traff_dur_srv == pytest.approx(6_000_000.0)

    assert report.opt_cl["tcps_connattempt"] == 25519
    assert report.opt_srv["tcps_connattempt"] == 0
    assert report.opt_cl["tcps_conndrops"] == 3
    assert report.opt_srv["tcps_conndrops"] == 0
    # Never observed in the fixture -> defaults to 0/0.
    assert report.opt_cl["tcps_accepts"] == 0
    assert report.opt_srv["tcps_accepts"] == 0

    assert report.port_series is not None
    assert report.time_series() == [1.0, 2.0, 3.0]
    assert report.port_series[rpt.PortParam.OBYTES] == [
        [1000.0, 1400.0], [3000.0, 3400.0], [7500.0, 8000.0],
    ]
    # DIVERGENCE: current time / test duration collected once and
    # broadcast to both ports, not read n_ports times as in C.
    assert report.port_series[rpt.PortParam.TEST_DUR] == [
        [20.0, 20.0], [20.0, 20.0], [20.0, 20.0],
    ]

    rates_p0 = report.series_by_time(rpt.PortParam.OBYTES, 0)
    assert rates_p0 == pytest.approx([1000.0, 2000.0, 4500.0])
