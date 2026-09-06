# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools.trex._astf_stats unit tests (pure, fixture-driven)."""
import json
import pathlib

import pytest

from pyte.tools.trex import _astf_stats as st

DATA = pathlib.Path(__file__).parent / "data"


def _load(name):
    return json.loads((DATA / name).read_text())


# The 17 flow-table error counters observed on TRex 3.06
# (tests/data/astf_traffic.json's server, probed with skip_zero=False).
# Kept as a literal tuple so a bad transcription in the module shows up
# as a test failure rather than as a silent gap.
FLOW_TABLE_ERR_NAMES = (
    "err_c_nf_throttled", "err_c_tuple_err", "err_cwf", "err_dct",
    "err_defer_no_template", "err_flow_overflow",
    "err_fragments_ipv4_drop", "err_l3_cs", "err_l4_cs", "err_len_err",
    "err_no_memory", "err_no_syn", "err_no_tcp_udp", "err_no_template",
    "err_redirect_rx", "err_rx_throttled", "err_s_nf_throttled",
)


def test_flow_table_err_names_are_the_seventeen_trex_reports():
    assert st.FLOW_TABLE_ERR_NAMES == FLOW_TABLE_ERR_NAMES


def test_flow_table_errors_reports_a_counter_not_in_the_known_tuple():
    # The point of this test: FLOW_TABLE_ERR_NAMES is documentation,
    # not a filter, so a counter TRex adds later (not in the tuple
    # above) must still be reported.
    assert "err_future_counter" not in st.FLOW_TABLE_ERR_NAMES
    t = st.AstfTraffic(client={"err_future_counter": 5}, server={})
    assert t.flow_table_errors() == {"err_future_counter": 5}


def test_parse_global_reads_active_flows():
    g = st.parse_global(_load("astf_global.json"))
    assert isinstance(g.active_flows, int)
    assert g.active_flows >= 0
    assert g.tx_bps >= 0.0


def test_parse_global_reads_est_flows_from_traffic_client():
    g = st.parse_global(_load("astf_global.json"))
    assert g.est_flows == 14


def test_parse_global_est_flows_defaults_to_zero_when_absent():
    g = st.parse_global({"global": {"active_flows": 5.0}})
    assert g.est_flows == 0


def test_parse_traffic_drop_pct_is_zero_without_drops():
    t = st.AstfTraffic(client={"tcps_connattempt": 100,
                                "tcps_connects": 100, "tcps_drops": 0},
                        server={})
    assert t.connect_attempts == 100
    assert t.drops == 0
    assert t.drop_pct == 0.0


def test_parse_traffic_drop_pct_uses_attempts_as_denominator():
    t = st.AstfTraffic(client={"tcps_connattempt": 200,
                                "tcps_connects": 190, "tcps_drops": 10},
                        server={})
    assert t.drop_pct == pytest.approx(5.0)


def test_drop_pct_is_zero_when_nothing_was_attempted():
    t = st.AstfTraffic(client={}, server={})
    assert t.drop_pct == 0.0


def test_flow_table_errors_reports_only_non_zero_counters():
    t = st.AstfTraffic(client={"err_cwf": 3, "err_no_syn": 0},
                        server={"err_flow_overflow": 7})
    assert t.flow_table_errors() == {"err_cwf": 3,
                                      "err_flow_overflow": 7}


def test_flow_table_errors_excludes_cli_section_header_sentinels():
    # get_traffic_stats() mixes five always-zero, non-counter
    # section-header keys into the same dictionary. They must never
    # appear in flow_table_errors(), even though the non-zero rule
    # alone would already exclude them here.
    t = st.AstfTraffic(client={"-": 0, "Application": 0,
                                "Flow Table": 0, "TCP": 0, "UDP": 0},
                        server={})
    assert t.flow_table_errors() == {}


def test_parse_traffic_from_fixture_has_both_sides():
    t = st.parse_traffic(_load("astf_traffic.json"))
    assert isinstance(t.client, dict)
    assert isinstance(t.server, dict)


def test_parse_latency_from_fixture_reads_port_entry():
    lat = st.parse_latency(_load("astf_latency.json"), 0)
    assert lat.port == 0
    assert lat.avg > 0.0
    assert lat.min >= 0.0
    assert lat.max >= lat.min
    assert isinstance(lat.seq_errors, int)
    assert isinstance(lat.pkt_ok, int)
    assert isinstance(lat.histogram, dict)
    assert lat.histogram
    assert all(isinstance(k, int) and isinstance(v, int)
               for k, v in lat.histogram.items())


def test_percentile_lands_in_the_bucket_the_cumulative_count_crosses():
    lat = st.AstfLatency(port=0, avg=0.0, min=0.0, max=0.0, jitter=0.0,
                          seq_errors=0, pkt_ok=100,
                          histogram={0: 10, 100: 20, 200: 30, 300: 40})
    assert lat.percentile(50) == 200.0
    assert lat.percentile(95) == 300.0


def test_percentile_of_empty_histogram_is_zero():
    lat = st.AstfLatency(port=0, avg=0.0, min=0.0, max=0.0, jitter=0.0,
                          seq_errors=0, pkt_ok=0, histogram={})
    assert lat.percentile(50) == 0.0


def test_percentile_out_of_range_raises():
    lat = st.AstfLatency(port=0, avg=0.0, min=0.0, max=0.0, jitter=0.0,
                          seq_errors=0, pkt_ok=1, histogram={0: 1})
    with pytest.raises(ValueError):
        lat.percentile(-1)
    with pytest.raises(ValueError):
        lat.percentile(101)


def test_parse_tg_stats_builds_a_sorted_template_list():
    result = st.parse_tg_stats({"tg1": {"err_cwf": 1},
                                 "tg0": {"err_cwf": 2}})
    assert [t.name for t in result] == ["tg0", "tg1"]
    assert result[0].counters == {"err_cwf": 2}


def test_series_window_selects_by_time_inclusive():
    s = st.Series()
    for i in range(5):
        s.add(st.Snapshot(t=float(i), glob=_g(i), traffic=_empty()))
    assert [x.t for x in s.window(1.0, 3.0)] == [1.0, 2.0, 3.0]


def test_series_mean_over_window_ignores_samples_outside_it():
    s = st.Series()
    for i, flows in enumerate([10, 100, 200, 300, 10]):
        s.add(st.Snapshot(t=float(i), glob=_g(flows),
                           traffic=_empty()))
    assert s.mean("active_flows", 1.0, 3.0) == pytest.approx(200.0)


def test_series_median_over_window_is_the_middle_sample():
    s = st.Series()
    for i, flows in enumerate([1, 5, 100]):
        s.add(st.Snapshot(t=float(i), glob=_g(flows),
                           traffic=_empty()))
    assert s.median("active_flows", 0.0, 2.0) == pytest.approx(5.0)


def test_series_mean_of_empty_window_is_zero():
    assert st.Series().mean("active_flows", 0.0, 1.0) == 0.0


def _g(active):
    return st.AstfGlobal(active_flows=active, est_flows=active,
                          tx_bps=0.0, rx_bps=0.0, tx_pps=0.0,
                          rx_pps=0.0, cpu_util=0.0, queue_full=0)


def _empty():
    return st.AstfTraffic(client={}, server={})
