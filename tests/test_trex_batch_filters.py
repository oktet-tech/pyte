# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools.trex._batch_filters unit tests (data module, no job I/O)."""
import re

from pyte.tools.trex import _batch_filters as flt

# The 16 flow-table error counters the suite reads off OPT_COUNTERS,
# transcribed from tapi_trex.c:78-213 (opt_filters[], "Flow table."
# section) - kept here as a literal list so a bad transcription in the
# module shows up as a test failure, not a silent gap.
FLOW_TABLE_ERR_NAMES = (
    "rss_redirect_drops", "err_cwf", "err_no_syn", "err_len_err",
    "err_fragments_ipv4_drop", "err_no_template", "err_no_memory",
    "err_dct", "err_l3_cs", "err_l4_cs", "err_redirect_rx",
    "err_c_nf_throttled", "err_c_tuple_err", "err_s_nf_throttled",
    "err_flow_overflow", "err_defer_no_template",
)


def test_parse_units_mega():
    assert flt.parse_units("12.34 M") == 12.34e6


def test_parse_units_no_unit_scale_1000_not_1024():
    # scale is 1000 (decimal), not 1024 - a space unit char is a no-op
    # multiplier of 1, so this must stay exactly 7.0.
    assert flt.parse_units("7.00  ") == 7.0


def test_parse_units_kilo_and_giga():
    assert flt.parse_units("1.50 K") == 1500.0
    assert flt.parse_units("2.00 G") == 2e9


def test_port_stat_re_matches_sample_row_per_port_columns():
    m = re.match(flt.port_stat_re("obytes", 2), "obytes | 123 | 456 | 579")
    assert m is not None
    assert m.groups() == ("123", "456")


def test_port_time_re_matches_sample_row():
    m = re.search(flt.port_time_re("current time"),
                   "current time            : 12.345 sec")
    assert m is not None
    assert m.group(1) == "12.345"


def test_opt_counter_re_matches_sample_row():
    row = " tcps_connattempt  | 25519 | 0 | connections initiated"
    m = re.search(flt.OPT_COUNTER_RE("tcps_connattempt", False), row)
    assert m is not None
    assert m.groups() == ("25519", "0")


def test_opt_counter_re_err_row_needs_asterisk_prefix():
    row = " tcps_conndrops     | 3 | 0 | *embryonic connections dropped"
    m = re.search(flt.OPT_COUNTER_RE("tcps_conndrops", True), row)
    assert m is not None
    assert m.groups() == ("3", "0")


def test_flow_table_error_names_present_in_opt_counters():
    for name in FLOW_TABLE_ERR_NAMES:
        assert name in flt.OPT_COUNTERS, f"missing {name}"


def test_flow_table_error_names_classified_as_err():
    for name in FLOW_TABLE_ERR_NAMES:
        assert name in flt.OPT_COUNTERS_ERR, f"{name} not classified err"


def test_opt_counters_no_duplicates():
    assert len(flt.OPT_COUNTERS) == len(set(flt.OPT_COUNTERS))


def test_summary_total_tx_matches_sample():
    regex, group = flt.SUMMARY["total_tx"]
    m = re.search(regex, "Total-Tx               :     12.34 Mbps")
    assert m is not None
    assert m.group(group) == "12.34 M"


def test_global_stats_total_tx_matches_sample():
    m = re.search(flt.GLOBAL_STATS["Total-Tx"],
                   "Total-Tx          :      12.345 Mbps")
    assert m is not None
    assert m.group(1) == "12.345 M"


def test_m_traff_dur_matches_sample_both_groups():
    row = ("   m_traffic_duration    |    5.00 Ksec    |    6.00 Msec"
           "    |    measured traffic duration")
    m = re.search(flt.M_TRAFF_DUR, row)
    assert m is not None
    assert m.groups() == ("5.00 K", "6.00 M")
