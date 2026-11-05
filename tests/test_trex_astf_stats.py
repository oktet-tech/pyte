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


# ---------------------------------------------------------------------------
# Counter descriptors
# ---------------------------------------------------------------------------

def _desc(*items):
    """Descriptors as get_counter_desc() ships them, parsed."""
    return st.parse_counter_desc(
        [{"name": n, "help": h, "info": i} for n, h, i in items])


def test_parse_counter_desc_keys_by_name():
    d = _desc(("tcps_connects", "connections established", "info"))
    assert d["tcps_connects"].help == "connections established"
    assert d["tcps_connects"].is_error is False


def test_parse_counter_desc_marks_the_error_class():
    assert _desc(("err_no_syn", "no SYN", "error"))["err_no_syn"].is_error


def test_parse_counter_desc_drops_the_id_padding():
    """The native client pre-fills its descriptor list with zeroes and
    indexes it by counter id, so a sparse id space leaves integers
    among the dictionaries."""
    d = st.parse_counter_desc([0, {"name": "a", "help": "", "info": ""},
                               0, {"name": "", "help": "x"}])
    assert list(d) == ["a"]


def test_parse_counter_desc_of_nothing_is_empty():
    assert st.parse_counter_desc(None) == {}
    assert st.parse_counter_desc([]) == {}


# ---------------------------------------------------------------------------
# flow_table_errors() with descriptors
# ---------------------------------------------------------------------------

def test_descriptors_add_an_error_the_prefix_rule_would_miss():
    t = st.AstfTraffic(client={"tcps_rcvbadsum": 3}, server={})
    assert t.flow_table_errors() == {}
    d = _desc(("tcps_rcvbadsum", "bad checksum", "error"))
    assert t.flow_table_errors(d) == {"tcps_rcvbadsum": 3}


def test_descriptors_never_hide_an_error_the_prefix_rule_caught():
    # The union is the point: a descriptor set that classifies
    # err_no_syn as merely informational must not suppress it.
    t = st.AstfTraffic(client={"err_no_syn": 7}, server={})
    d = _desc(("err_no_syn", "no SYN", "info"))
    assert t.flow_table_errors(d) == {"err_no_syn": 7}


def test_errors_sum_both_sides():
    t = st.AstfTraffic(client={"err_cwf": 2}, server={"err_cwf": 5})
    assert t.flow_table_errors() == {"err_cwf": 7}


# ---------------------------------------------------------------------------
# format_counters()
# ---------------------------------------------------------------------------

def test_format_counters_has_a_row_per_counter_and_a_header():
    t = st.AstfTraffic(client={"tcps_connects": 5},
                       server={"tcps_accepts": 4})
    out = st.format_counters(t)
    assert "client" in out.splitlines()[0]
    assert "server" in out.splitlines()[0]
    rows = [ln for ln in out.splitlines() if "tcps_" in ln]
    assert len(rows) == 2


def test_format_counters_shows_a_counter_absent_from_one_side_as_zero():
    t = st.AstfTraffic(client={"tcps_connects": 5}, server={})
    row = [ln for ln in st.format_counters(t).splitlines()
           if "tcps_connects" in ln][0]
    assert row.split("|")[1].strip() == "5"
    assert row.split("|")[2].strip() == "0"


def test_format_counters_skips_zero_rows_by_default():
    t = st.AstfTraffic(client={"tcps_connects": 5, "tcps_drops": 0},
                       server={})
    out = st.format_counters(t)
    assert "tcps_connects" in out
    assert "tcps_drops" not in out


def test_format_counters_keeps_zero_rows_when_asked():
    t = st.AstfTraffic(client={"tcps_drops": 0}, server={})
    assert "tcps_drops" in st.format_counters(t, skip_zero=False)


def test_format_counters_always_shows_a_zero_error_counter():
    """A zero error counter is the evidence that the error did not
    happen; a zero data counter is noise."""
    t = st.AstfTraffic(client={"err_no_syn": 0, "tcps_drops": 0},
                       server={})
    out = st.format_counters(t, _desc(("err_no_syn", "no SYN", "error")))
    assert "err_no_syn" in out
    assert "tcps_drops" not in out


def test_format_counters_marks_error_rows():
    t = st.AstfTraffic(client={"err_no_syn": 3, "tcps_connects": 1},
                       server={})
    out = st.format_counters(t, _desc(("err_no_syn", "no SYN", "error"),
                                      ("tcps_connects", "est", "info")))
    marked = [ln for ln in out.splitlines() if ln.startswith("!")]
    assert len(marked) == 1
    assert "err_no_syn" in marked[0]


def test_format_counters_appends_the_help_text():
    t = st.AstfTraffic(client={"tcps_connattempt": 9}, server={})
    out = st.format_counters(
        t, _desc(("tcps_connattempt", "connections initiated", "info")))
    assert out.rstrip().endswith("connections initiated")


def test_format_counters_without_descriptors_drops_the_help_column():
    """An unexpected TRex still gets a readable table."""
    t = st.AstfTraffic(client={"tcps_connattempt": 9}, server={})
    row = [ln for ln in st.format_counters(t).splitlines()
           if "tcps_connattempt" in ln][0]
    assert row.rstrip().endswith("|")
    assert not row.startswith("!")


def test_format_counters_excludes_the_section_header_keys():
    """get_traffic_stats() mixes in always-zero separator keys that
    are not counters at all."""
    t = st.AstfTraffic(client={"TCP": 0, "-": 0, "Flow Table": 0,
                               "tcps_connects": 1}, server={})
    out = st.format_counters(t, skip_zero=False)
    assert "tcps_connects" in out
    for key in st.NON_COUNTER_KEYS:
        assert not any(ln.strip().startswith(key + " ")
                       for ln in out.splitlines())


def test_format_counters_groups_the_families_in_order():
    t = st.AstfTraffic(
        client={"m_active_flows": 1, "tcps_connects": 1,
                "udps_connects": 1, "err_cwf": 1, "redirect_rx_ok": 1},
        server={})
    seen = [ln.split("|")[0].strip() for ln in
            st.format_counters(t).splitlines()[1:] if ln.strip()]
    assert seen == ["m_active_flows", "tcps_connects", "udps_connects",
                    "err_cwf", "redirect_rx_ok"]


def test_format_counters_separates_families_with_a_blank_line():
    t = st.AstfTraffic(client={"m_active_flows": 1, "tcps_connects": 1},
                       server={})
    assert "" in st.format_counters(t).splitlines()


def test_format_counters_renders_floats_with_two_decimals():
    """The m_ family is bandwidths and rates, which round to a
    useless 0 or 100 as integers."""
    t = st.AstfTraffic(client={"m_tx_bw_l7_r": 51525.74257425742},
                       server={})
    assert "51525.74" in st.format_counters(t)


def test_format_counters_of_nothing_is_empty():
    assert st.format_counters(st.AstfTraffic(client={}, server={})) == ""
    assert st.format_counters(
        st.AstfTraffic(client={"tcps_drops": 0}, server={})) == ""


def test_format_counters_columns_line_up():
    t = st.AstfTraffic(client={"m_active_flows": 1, "tcps_connects": 1000},
                       server={"tcps_connects": 2})
    lines = [ln for ln in st.format_counters(t).splitlines() if ln.strip()]
    positions = {tuple(i for i, ch in enumerate(ln) if ch == "|")
                 for ln in lines}
    assert len(positions) == 1


def test_format_counters_renders_the_real_trex_capture():
    """End to end on the TRex 3.06 fixture rather than on hand-made
    dictionaries."""
    t = st.parse_traffic(_load("astf_traffic.json"))
    out = st.format_counters(t)
    assert "tcps_connattempt" in out
    assert "m_active_flows" in out
    # 136 client connection attempts, no server-side ones.
    row = [ln for ln in out.splitlines() if "tcps_connattempt" in ln][0]
    assert row.split("|")[1].strip() == "136"
    assert row.split("|")[2].strip() == "0"
