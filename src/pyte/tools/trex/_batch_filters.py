# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools.trex - batch (ASTF) TRex stdout filter tables.

Data-only sibling of :mod:`pyte.tools.trex.batch`: the regex tables that
mirror TE's tapi_trex.c stdout filters. Regex strings, name tuples and
small pure functions only - no job interaction. Attaching these as real
tapi_job filters to a running TRex process is Task 6.

Pinned to te/lib/tapi_tool/tapi_trex.c (line numbers as read for this
port; they will drift with the C file, this is a snapshot reference):

- regex macros: :44-60
- optional counter table (``opt_filters[]``, TAPI_TREX_OPT_FLT /
  TAPI_TREX_OPT_FLT_ERR entries): :78-213 (101 entries)
- per-port stat types (``port_stat_types[]``): :223-256
- global stat types (``global_stat_types[]``): :258-313
- summary filters attached at job-create time (kept here as data only):
  :1515-1600 (job creation with TAPI_JOB_SIMPLE_FILTERS(...))
- unit decoding (``bin_units``): :1821-1830

DIVERGENCE (deliberate, see the task brief): SUMMARY keeps the C
summary filters' ``[0-9]{2}`` two-decimal restriction verbatim.
GLOBAL_STATS already uses (and keeps) ``[0-9]+\\.[0-9]+`` in the C
source - the two tables are not symmetric there either; this module
does not "fix" that, it just documents it.

parse_units() mirrors ``bin_units`` (tapi_trex.c:1821-1830): TRex
prints its own counters with a decimal (scale 1000) unit suffix, NOT
the binary/1024 one - do not "correct" this.
"""
from __future__ import annotations

# --- Summary counters --------------------------------------------------
# name -> (regex, extract group), attached as TAPI_JOB_SIMPLE_FILTERS at
# job-create time in the C code (tapi_trex.c:1515-1600).
SUMMARY: dict[str, tuple[str, int]] = {
    "total_tx": (r"Total\-Tx\s+\:\s+([0-9]+\.[0-9]{2}\s.)bps", 1),
    "total_rx": (r"Total\-Rx\s+\:\s+([0-9]+\.[0-9]{2}\s.)bps", 1),
    "total_cps": (r"Total\-CPS\s+\:\s+([0-9]+\.[0-9]{2}\s.)cps", 1),
    "tx_pkts": (r"Total-tx-pkt\s+:\s+([0-9]+)\s+pkts", 1),
    "rx_pkts": (r"Total-rx-pkt\s+:\s+([0-9]+)\s+pkts", 1),
    "tx_bytes": (r"Total-tx-bytes\s+:\s+([0-9]+)\s+byte", 1),
    "rx_bytes": (r"Total-rx-bytes\s+:\s+([0-9]+)\s+byte", 1),
}

# TAPI_TREX_M_TRAFF_DUR_FLT (tapi_trex.c:51-53): one regex, applied twice
# with a different extract group - group 1 is the client duration,
# group 2 is the server duration.
M_TRAFF_DUR = (
    r"\s+m_traffic_duration\s+\|\s+([0-9]+\.[0-9]{2}\s[ KMGT])sec\s+\|"
    r"\s+([0-9]+\.[0-9]{2}\s[ KMGT])sec\s+\|\s+measured traffic duration"
)

# --- Optional counter table (tapi_trex.c:78-213, opt_filters[]) --------
# (name, description, is_err); transcribed mechanically from the C
# table, in the same order, keeping the err/non-err classification
# (TAPI_TREX_OPT_FLT vs TAPI_TREX_OPT_FLT_ERR).
_OPT_FLT_TABLE: tuple[tuple[str, str, bool], ...] = (
    # TCP counters
    ("tcps_connattempt", "connections initiated", False),
    ("tcps_accepts", "connections accepted", False),
    ("tcps_connects", "connections established", False),
    ("tcps_closed", "conn. closed (includes drops)", False),
    ("tcps_segstimed", "segs where we tried to get rtt", False),
    ("tcps_rttupdated", "times we succeeded", False),
    ("tcps_delack", "delayed acks sent", False),
    ("tcps_sndtotal", "total packets sent", False),
    ("tcps_sndpack", "data packets sent", False),
    ("tcps_sndbyte", "data bytes sent by application", False),
    ("tcps_sndbyte_ok", "data bytes sent by tcp", False),
    ("tcps_sndctrl", "control (SYN|FIN|RST) packets sent", False),
    ("tcps_sndacks", "ack-only packets sent", False),
    ("tcps_rcvtotal", "total packets received", False),
    ("tcps_rcvpack", "packets received in sequence", False),
    ("tcps_rcvbyte", "bytes received in sequence", False),
    ("tcps_rcvackpack", "rcvd ack packets", False),
    ("tcps_rcvackbyte", "tx bytes acked by rcvd acks", False),
    ("tcps_rcvackbyte_of",
     "tx bytes acked by rcvd acks - overflow acked", False),
    ("tcps_rcvoffloads", "receive offload packets by software", False),
    ("tcps_preddat", "times hdr predict ok for data pkts", False),
    ("tcps_drops", "connections dropped", False),
    ("tcps_conndrops", "embryonic connections dropped", True),
    ("tcps_timeoutdrop", "conn. dropped in rxmt timeout", True),
    ("tcps_rexmttimeo", "retransmit timeouts", True),
    ("tcps_rexmttimeo_syn", "retransmit SYN timeouts", True),
    ("tcps_persisttimeo", "persist timeouts", True),
    ("tcps_keeptimeo", "keepalive timeouts", True),
    ("tcps_keepprobe", "keepalive probes sent", True),
    ("tcps_keepdrops", "connections dropped in keepalive", True),
    ("tcps_testdrops",
     "connections dropped by user at timeout (no-close flag --nc)", False),
    ("tcps_sndrexmitpack", "data packets retransmitted", True),
    ("tcps_sndrexmitbyte", "data bytes retransmitted", True),
    ("tcps_sndprobe", "window probes sent", True),
    ("tcps_sndurg", "packets sent with URG only", True),
    ("tcps_sndwinup", "window update-only packets sent", False),
    ("tcps_rcvbadsum", "packets received with ccksum errs", True),
    ("tcps_rcvbadoff", "packets received with bad offset", True),
    ("tcps_rcvshort", "packets received too short", True),
    ("tcps_rcvduppack", "duplicate-only packets received", True),
    ("tcps_rcvdupbyte", "duplicate-only bytes received", True),
    ("tcps_rcvpartduppack", "packets with some duplicate data", True),
    ("tcps_rcvpartdupbyte", "dup. bytes in part-dup. packets", True),
    ("tcps_rcvoopackdrop", "OOO packet drop due to queue len", True),
    ("tcps_rcvoobytesdrop", "OOO bytes drop due to queue len", True),
    ("tcps_rcvoopack", "out-of-order packets received", True),
    ("tcps_rcvoobyte", "out-of-order bytes received", True),
    ("tcps_rcvpackafterwin", "packets with data after window", True),
    ("tcps_rcvbyteafterwin", "bytes rcvd after window", True),
    ("tcps_rcvafterclose", "packets rcvd after close", True),
    ("tcps_rcvwinprobe", "rcvd window probe packets", True),
    ("tcps_rcvdupack", "rcvd duplicate acks", True),
    ("tcps_rcvacktoomuch", "rcvd acks for unsent data", True),
    ("tcps_rcvwinupd", "rcvd window update packets", True),
    ("tcps_pawsdrop", "segments dropped due to PAWS", True),
    ("tcps_predack", "times hdr predict ok for acks", False),
    ("tcps_persistdrop", "timeout in persist state", True),
    ("tcps_badsyn", "bogus SYN e.g. premature ACK", True),
    ("tcps_reasalloc", "allocate tcp reasembly ctx", True),
    ("tcps_reasfree", "free tcp reasembly ctx", True),
    ("tcps_reas_hist_4", "count of max queue <= 4", True),
    ("tcps_reas_hist_16", "count of max queue <= 16", True),
    ("tcps_reas_hist_100", "count of max queue <= 100", True),
    ("tcps_reas_hist_other", "count of max queue > 100", True),
    ("tcps_nombuf", "no mbuf for tcp - drop the packets", True),
    ("tcps_sack_recovery_episode", "SACK recovery episodes", True),
    ("tcps_sack_rexmits", "SACK rexmit segments", True),
    ("tcps_sack_rexmit_bytes", "SACK rexmit bytes", True),
    ("tcps_sack_rcv_blocks", "SACK blocks (options) received", True),
    ("tcps_sack_send_blocks", "SACK blocks (options) sent", True),
    ("tcps_sack_sboverflow", "times scoreboard overflowed", True),
    ("tcps_ecn_ce", "ECN Congestion Experienced", False),
    ("tcps_ecn_ect0", "ECN Capable Transport", False),
    ("tcps_ecn_ect1", "ECN Capable Transport", False),
    ("tcps_ecn_shs", "ECN successful handshakes", False),
    ("tcps_ecn_rcwnd", "times ECN reduced the cwnd", False),

    # Flow table.
    ("rss_redirect_rx", "rss rx packets redirected", False),
    ("rss_redirect_tx", "rss tx packets redirected", False),
    ("rss_redirect_drops", "rss packets to redirect dropped", True),
    ("rss_redirect_queue_full", "rss tx queue full", False),
    ("ignored_macs", "ignored macs addr", False),
    ("ignored_ips", "ignored ips addr", False),
    ("err_cwf", "client pkt without flow", True),
    ("err_no_syn", "server first flow packet with no SYN", True),
    ("err_len_err", "pkt with length error", True),
    ("err_fragments_ipv4_drop", "fragments_ipv4_drop", True),
    ("err_no_tcp_udp", "no tcp/udp packet", False),
    ("err_no_template", "server can't match L7 template", True),
    ("err_no_memory", "No heap memory for allocating flows", True),
    ("err_dct", "duplicate flow - more clients require", True),
    ("err_l3_cs", "ip checksum error", True),
    ("err_l4_cs", "tcp/udp checksum error", True),
    ("err_redirect_rx", "redirect to rx error", True),
    ("redirect_rx_ok", "redirect to rx OK", False),
    ("err_rx_throttled", "rx thread was throttled", False),
    ("err_c_nf_throttled", "client new flow throttled", True),
    ("err_c_tuple_err", "client new flow, not enough clients", True),
    ("err_s_nf_throttled", "server new flow throttled", True),
    ("err_flow_overflow", "too many flows errors", True),
    ("defer_template",
     "tcp L7 template matching deferred (by l7_map)", False),
    ("err_defer_no_template",
     "server can't match L7 template (deferred by l7_map)", True),
)

OPT_COUNTERS: tuple[str, ...] = tuple(name for name, _, _ in _OPT_FLT_TABLE)
"""All optional-counter names from tapi_trex.c:78-213, in table order."""

OPT_COUNTERS_ERR: frozenset[str] = frozenset(
    name for name, _, is_err in _OPT_FLT_TABLE if is_err)
"""Names classified TAPI_TREX_OPT_FLT_ERR in the C table."""

_OPT_FLT_DESCR: dict[str, str] = {
    name: descr for name, descr, _ in _OPT_FLT_TABLE}


def OPT_COUNTER_RE(name: str, err: bool) -> str:
    """Two-column optional-counter row regex for ``name``.

    Mirrors TAPI_TREX_OPT_FLT_TEMPLATE (tapi_trex.c:56-57): the
    description looked up from the transcribed C table is substituted
    into the row regex the same way the C code's sprintf-style %s does
    (unescaped). For an err counter, like TAPI_TREX_OPT_FLT_ERR
    (tapi_trex.c:75-76), the description is prefixed with a literal
    ``*`` (escaped for the regex engine).
    """
    descr = _OPT_FLT_DESCR[name]
    if err:
        descr = r"\*" + descr
    return (r"\s+" + name + r"\s+\|\s+([0-9]+)\s+\|\s+([0-9]+)\s+\|\s+"
            + descr)


# --- Per-port stats (tapi_trex.c:223-256, port_stat_types[]) -----------
PORT_STAT_ROWS = ("opackets", "obytes", "ipackets", "ibytes",
                   "ierrors", "oerrors")
PORT_TIME_ROWS = ("current time", "test duration")

# TAPI_TREX_PORT_STAT_ONE_COUNTER_FLT (tapi_trex.c:59): one column per
# port, repeated n_ports times after the row name.
_PORT_STAT_ONE_COUNTER = r"\s+\|\s+([0-9]+)"

# TAPI_TREX_PORT_STAT_TIME_FLT (tapi_trex.c:60).
_PORT_STAT_TIME = r"\s+:\s+([0-9]+\.[0-9]+)\s+sec"


def port_stat_re(name: str, n_ports: int) -> str:
    """Per-port counter row regex: ``name`` + one group per port."""
    return name + _PORT_STAT_ONE_COUNTER * n_ports


def port_time_re(name: str) -> str:
    """Per-port time row regex (current time / test duration)."""
    return name + _PORT_STAT_TIME


# --- Global stats (tapi_trex.c:258-313, global_stat_types[]) -----------
# name -> regex; unlike SUMMARY these already use [0-9]+\.[0-9]+ (not
# {2}) in the C source, kept as-is here.
GLOBAL_STATS: dict[str, str] = {
    "current time": r"\s+:\s+([0-9]+\.[0-9]+)\s+sec",
    "test duration": r"\s+:\s+([0-9]+\.[0-9]+)\s+sec",
    "Total-Tx": r"\s+:\s+([0-9]+\.[0-9]+\s.)bps",
    "Total-Rx": r"\s+:\s+([0-9]+\.[0-9]+\s.)bps",
    "Total-PPS": r"\s+:\s+([0-9]+\.[0-9]+\s.)pps",
    "Total-CPS": r"\s+:\s+([0-9]+\.[0-9]+\s.)cps",
    "Expected-PPS": r"\s+:\s+([0-9]+\.[0-9]+\s.)pps",
    "Expected-CPS": r"\s+:\s+([0-9]+\.[0-9]+\s.)cps",
    "Expected-L7-BPS": r"\s+:\s+([0-9]+\.[0-9]+\s.)bps",
}

# --- Unit decoding (tapi_trex.c:1821-1830, bin_units) -------------------
# TRex's own scale for these counters is 1000 (decimal), not 1024. Unit
# chars index into this string; a space means "no scale" (multiplier
# 1000**0 == 1).
_UNITS = " KMGT"
_SCALE = 1000


def parse_units(token: str) -> float:
    """Parse a "<number> <unit>" token captured by a *_KMGT filter.

    ``token`` is what the ``([0-9]+\\.[0-9]{2}\\s[ KMGT])`` (or the
    two-decimal-free GLOBAL_STATS equivalent) capture group returns:
    a number, one whitespace separator, then exactly one unit
    character - one of " KMGT" (space = no scale). Mirrors ``bin_units``
    (tapi_trex.c:1821-1830): scale 1000, NOT 1024.

    >>> parse_units("12.34 M")
    12340000.0
    """
    unit = token[-1]
    number = float(token[:-1].strip())
    return number * (_SCALE ** _UNITS.index(unit))
