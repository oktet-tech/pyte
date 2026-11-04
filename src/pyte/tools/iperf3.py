# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools.iperf3 — run iperf3 client/server from Python tests.

Pure Python over pyte.job; zero shim imports. The iperf3 binary is
resolved from the agent's PATH (job program "iperf3"). Gate iperf3 tests
with <req id="IPERF3"/> and the prologue probe.

Pinned mappings (from te/lib/tapi_performance/iperf3.c, tapi_performance.*)
===========================================================================

server argv (build_server_args; bind order port, interval):
    iperf3 -s -J  [-p<port>] [-i<interval>]

client argv (build_client_args; bind order below; each omitted when unset):
    iperf3 -c <host> [-J | --forceflush] [-B<src_host>] [-p<port>] [-4|-6]
    [-u] [-b<bandwidth_bits>] [-l<length>] [-n<num_bytes>] [-t<duration>]
    [-i<interval>] [-P<streams>] [-R] [--bidir]
    Flags glue the value on (-p5201); only --bidir is long-form. -u for UDP
    only (TCP default). -4/-6 select ip version (client). -J is the C
    TAPI's; --forceflush in its place is pyte only (Opts.json=False, text
    mode below): iperf3 block-buffers text into a pipe, so without it the
    interval lines reach the agent only when the client exits.

report (parsed from iperf3 JSON `end`):
    end.sum_sent.{bits_per_second,bytes,seconds,retransmits}  -> sent
    end.sum_received.{bits_per_second,bytes,seconds}          -> received
    UDP/default: end.sum.* fills both sent and received
    min(end.streams[*].sender.bits_per_second)  -> min_bps_per_stream
    top-level "error"  -> Report.error when there is an `end`
                          (an interrupted client), else raise IperfError

text mode (Opts.json=False; pyte only, the C TAPI always passes -J):
    -J prints nothing until the end, so a client that has to show
    progress while it runs prints text, flushed per line.  Written
    against iperf 3.18 output.  Its summary block feeds the same
    Report:
    [SUM] (or the one stream with -P 1) "sender" row   -> sent
    [SUM] (or the one stream with -P 1) "receiver" row -> received
        Transfer -> bytes (K/M/G/TBytes: powers of 1024),
        Bitrate -> bits_per_second (K/M/G/Tbits/sec: powers of 1000),
        interval end - start -> seconds, TCP sender Retr -> retransmits
    --bidir: the [TX-C] rows, as end.sum_sent/sum_received in JSON
    min(numbered-stream "sender" rows' Bitrate) -> min_bps_per_stream
    "iperf3: error - ..." / "iperf3: interrupt - ..." (stderr)
        -> Report.error after a summary, else raise IperfError

progress (text mode; Iperf3.progress()):
    numbered-stream interval lines "[  5]  0.00-1.00 sec 11.8 GBytes ..."
    (any role tag) -> (lines that moved data, sum of their Transfer in
    bytes); "0.00 Bytes" lines (a blocked stream), the [SUM] lines and
    the sender/receiver summary rows do not count

MI (iperf3_report_mi_log):
    THROUGHPUT "Per-stream" MIN    min_bps_per_stream  PLAIN
    THROUGHPUT "Transfer"   SINGLE bits_per_second      PLAIN

Deliberate deviations (vs the C TAPI):
  * protocol defaults to "tcp" here (C tapi_perf_opts_init defaults to UDP);
    the conventional iperf default. Set protocol explicitly when needed.
  * the report reads end.sum_* directly instead of summing intervals.
"""
from __future__ import annotations

import json
import re
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pyte.errors import IperfError
from pyte.tools import _tool
from pyte.tools._clientserver import serve
from pyte.tools._tool import check_ipversion
from pyte.tools._clientserver import Endpoint  # noqa: F401  (re-exported)

if TYPE_CHECKING:
    from pyte.rpc import RpcServer

_VALID_PROTOCOLS = frozenset({"tcp", "udp"})


@dataclass(frozen=True)
class Opts:
    """iperf3 options (shared by the server and client argv builders).

    Parameters
    ----------
    host:
        Client target (``-c``); required for :meth:`client_argv`, ignored
        by :meth:`server_argv`.
    src_host:
        Client source bind address (``-B``).
    port:
        ``-p`` port (both sides). None lets iperf3 use its default (5201).
    protocol:
        ``"tcp"`` (default, no flag) or ``"udp"`` (``-u``).
    ipversion:
        ``"4"`` or ``"6"`` (client only; ``-4``/``-6``). None: iperf3 default.
    bandwidth_bits:
        ``-b`` target bitrate in bits/s (UDP or `-b` on TCP).
    length:
        ``-l`` buffer/read-write length in bytes.
    num_bytes:
        ``-n`` bytes to transfer (instead of time).
    duration:
        ``-t`` seconds to run.
    interval:
        ``-i`` periodic report interval (both sides).
    streams:
        ``-P`` number of parallel client streams.
    reverse:
        ``-R`` server sends, client receives.
    dual:
        ``--bidir`` bidirectional.
    json:
        Client only: ``-J`` JSON output (default).  False runs the
        client in text mode with ``--forceflush`` in place of ``-J``:
        interval reports arrive while it runs
        (:meth:`Iperf3.progress`) and :meth:`Iperf3.wait` parses the
        text summary into the same :class:`Report`.
    """
    host: str | None = None
    src_host: str | None = None
    port: int | None = None
    protocol: str = "tcp"
    ipversion: str | None = None
    bandwidth_bits: int | None = None
    length: int | None = None
    num_bytes: int | None = None
    duration: int | None = None
    interval: int | None = None
    streams: int | None = None
    reverse: bool = False
    dual: bool = False
    json: bool = True

    def __post_init__(self) -> None:
        if self.protocol not in _VALID_PROTOCOLS:
            raise ValueError(
                f"unknown protocol {self.protocol!r}; "
                f"valid: {sorted(_VALID_PROTOCOLS)}")
        check_ipversion(self.ipversion)

    def server_argv(self) -> list[str]:
        """Build the iperf3 server argument list (without argv[0])."""
        argv = ["-s", "-J"]
        if self.port is not None:
            argv.append(f"-p{self.port}")
        if self.interval is not None:
            argv.append(f"-i{self.interval}")
        return argv

    def client_argv(self) -> list[str]:
        """Build the iperf3 client argument list (without argv[0]).

        Mirrors build_client_args bind order.
        """
        if not self.host:
            raise ValueError("Opts.host is required for the client")
        # Text into a pipe is block-buffered: flush each interval line.
        argv = ["-c", self.host, "-J" if self.json else "--forceflush"]
        if self.src_host:
            argv.append(f"-B{self.src_host}")
        if self.port is not None:
            argv.append(f"-p{self.port}")
        if self.ipversion is not None:
            argv.append(f"-{self.ipversion}")
        if self.protocol == "udp":
            argv.append("-u")
        if self.bandwidth_bits is not None:
            argv.append(f"-b{self.bandwidth_bits}")
        if self.length is not None:
            argv.append(f"-l{self.length}")
        if self.num_bytes is not None:
            argv.append(f"-n{self.num_bytes}")
        if self.duration is not None:
            argv.append(f"-t{self.duration}")
        if self.interval is not None:
            argv.append(f"-i{self.interval}")
        if self.streams is not None:
            argv.append(f"-P{self.streams}")
        if self.reverse:
            argv.append("-R")
        if self.dual:
            argv.append("--bidir")
        return argv


@dataclass(frozen=True)
class Direction:
    """One direction's summary (mirrors iperf3 end.sum_sent/sum_received)."""
    bits_per_second: float
    bytes: int
    seconds: float
    retransmits: int | None = None


@dataclass(frozen=True)
class Report:
    """Parsed iperf3 report.

    ``error`` is iperf3's own error text when it printed one next to
    the summary: a client stopped with SIGINT reports what ran so far
    and "interrupt - the client has terminated".
    """
    sent: Direction
    received: Direction
    min_bps_per_stream: float
    error: str | None = None


def _direction(d: dict) -> Direction:
    return Direction(
        bits_per_second=float(d["bits_per_second"]),
        bytes=int(d["bytes"]),
        seconds=float(d["seconds"]),
        retransmits=int(d["retransmits"]) if "retransmits" in d else None)


def _parse_report(obj: dict) -> Report:
    """Parse an iperf3 ``-J`` JSON object into a :class:`Report`.

    An ``error`` next to an ``end`` summary (an interrupted client)
    goes to Report.error.  Raises :exc:`pyte.errors.IperfError` if
    iperf3 reported an error and no summary, or the summary is
    missing or malformed.
    """
    from pyte.errors import IperfError

    err = obj.get("error") or None
    end = obj.get("end")
    if err and not isinstance(end, dict):
        raise IperfError(f"iperf3 reported error: {err}")
    if not isinstance(end, dict):
        raise IperfError(f"iperf3 JSON has no 'end' summary: {str(obj)[:200]!r}")

    if "sum_sent" in end and "sum_received" in end:
        sent = _direction(end["sum_sent"])
        received = _direction(end["sum_received"])
    elif "sum" in end:
        both = _direction(end["sum"])
        sent = received = both
    else:
        raise IperfError(
            f"iperf3 'end' has neither sum_sent/sum_received nor sum: "
            f"{str(end)[:200]!r}")

    bps = []
    for st in end.get("streams", []):
        side = st.get("sender") or st.get("udp") or st.get("receiver")
        if side and "bits_per_second" in side:
            bps.append(float(side["bits_per_second"]))
    min_bps = min(bps) if bps else sent.bits_per_second

    return Report(sent=sent, received=received, min_bps_per_stream=min_bps,
                  error=None if err is None else str(err))


#: Byte sizes as iperf3 prints them ("11.8 GBytes"): powers of 1024.
_BYTE_UNITS = {"": 1, "K": 1 << 10, "M": 1 << 20, "G": 1 << 30,
               "T": 1 << 40}
#: Bit rates ("101 Gbits/sec"): powers of 1000.
_BIT_UNITS = {"": 1.0, "K": 1e3, "M": 1e6, "G": 1e9, "T": 1e12}

#: A numbered-stream report line and its Transfer; read alike by the
#: agent's PCRE2 multiline filter and by Python re.  [SUM] lines do
#: not match (``\d+`` stream id); the per-stream sender/receiver
#: summary rows do and progress() drops them by their last word.
#: Matching to the end of the line keeps a line cut between two
#: reads in the filter until the rest arrives.
_INTERVAL_REGEX = (
    r"^\[[ \t]*\d+\](?:\[[TR]X-[CS]\])?[ \t]+[\d.]+-[\d.]+[ \t]+sec"
    r"[ \t]+([\d.]+)[ \t]+([KMGT]?)Bytes([^\n]*)$")
_INTERVAL_RE = re.compile(_INTERVAL_REGEX, re.MULTILINE)

_SUMMARY_RE = re.compile(
    r"^\[[ \t]*(?P<id>\d+|SUM)\](?:\[(?P<role>[TR]X-[CS])\])?"
    r"[ \t]+(?P<start>[\d.]+)-(?P<end>[\d.]+)[ \t]+sec"
    r"[ \t]+(?P<size>[\d.]+)[ \t]+(?P<size_unit>[KMGT]?)Bytes"
    r"[ \t]+(?P<rate>[\d.]+)[ \t]+(?P<rate_unit>[KMGT]?)bits/sec"
    r"(?P<extra>[^\n]*?)[ \t]+(?P<side>sender|receiver)[ \t]*$",
    re.MULTILINE)

_TEXT_ERROR_RE = re.compile(
    r"^iperf3: ((?:error|interrupt) - [^\n]*)$", re.MULTILINE)


def _bytes(size: str, unit: str) -> int:
    return round(float(size) * _BYTE_UNITS[unit])


def _bps(row: re.Match) -> float:
    return float(row["rate"]) * _BIT_UNITS[row["rate_unit"]]


def _text_direction(row: re.Match) -> Direction:
    # TCP sender rows print Retr after the bitrate; UDP rows print
    # jitter and loss there, receiver rows nothing.
    extra = row["extra"].split()
    retr = int(extra[0]) if len(extra) == 1 and extra[0].isdigit() else None
    return Direction(
        bits_per_second=_bps(row),
        bytes=_bytes(row["size"], row["size_unit"]),
        seconds=float(row["end"]) - float(row["start"]),
        retransmits=retr)


def _parse_text_report(text: str) -> Report:
    """Parse iperf3 client text output (no ``-J``) into a :class:`Report`.

    *text* is the client's stdout followed by its stderr, where
    iperf3 prints its error line.  The summary block gives sent and
    received: the [SUM] sender/receiver rows, or the stream's own
    with one stream (``-P 1`` prints no [SUM]); with ``--bidir`` the
    [TX-C] rows.  An error line next to a summary (an interrupted
    client) goes to Report.error.  Raises
    :exc:`pyte.errors.IperfError` on an error without a summary, or
    when there is no summary at all.
    """
    m_err = _TEXT_ERROR_RE.search(text)
    err = m_err.group(1).strip() if m_err else None
    rows = list(_SUMMARY_RE.finditer(text))
    if not rows:
        if err:
            raise IperfError(f"iperf3 reported error: {err}")
        raise IperfError(
            f"iperf3 text output has no summary: {text[:200]!r}")

    forward = [r for r in rows if r["role"] in (None, "TX-C")]
    total = [r for r in forward if r["id"] == "SUM"] or forward
    sides = {r["side"]: r for r in total}
    if len({r["id"] for r in total}) != 1 or len(sides) != 2:
        raise IperfError(
            "iperf3 text summary has no single sender/receiver pair: "
            f"{[r.group(0) for r in total]!r}")

    sent = _text_direction(sides["sender"])
    received = _text_direction(sides["receiver"])
    bps = [_bps(r) for r in rows if r["id"] != "SUM" and r["side"] == "sender"]
    return Report(sent=sent, received=received,
                  min_bps_per_stream=min(bps) if bps else sent.bits_per_second,
                  error=err)


class Iperf3(_tool.ToolHandle):
    """Lifecycle manager for a running iperf3 *client* job.

    Created via :func:`run`. The JSON report arrives on stdout (``-J``);
    both streams are dumped to the TE log (RING) before parsing,
    mirroring the C tapi_performance perf_app_dump_output().  A
    non-zero exit raises even when the JSON parsed, unless iperf3
    itself put an error next to its summary: a client stopped with
    SIGINT prints both and exits 1, and wait() then returns the
    report with Report.error set.  A JSON error object without a
    summary is rejected by the parse.

    In text mode (``Opts(json=False)``) run() also hands in
    *intervals*, a grep filter over the interval report lines:
    :meth:`progress` counts them while the client runs, and wait()
    parses the text summary (stdout, then the error line from
    stderr) into the same Report, with the same exit-status rules.
    """

    tool = "iperf3 client"
    error_cls = IperfError
    default_timeout = 60.0

    def __init__(self, job, stdout_filter, stderr_filter, intervals=None):
        super().__init__(job, stdout_filter)
        self._stderr_filter = stderr_filter
        self._intervals = intervals
        self._text = intervals is not None
        self._n_intervals = 0
        self._interval_bytes = 0
        self._parsed: Report | None = None

    def progress(self) -> tuple[int, int]:
        """(intervals that moved data, their bytes) so far; never blocks.

        Drains the interval lines queued since the last call and adds
        them to the totals: one line per stream per ``-i`` interval
        (both directions with ``--bidir``), bytes summed from their
        Transfer column.  A line with a zero Transfer does not count:
        a blocked stream (link down, peer stopped) keeps printing
        "0.00 Bytes" lines every interval, and counting them would
        make a stalled client look alive.  [SUM] lines and the end
        summary do not count either.  After close() the job and its
        filter are gone: the last totals are returned as they are.
        Needs text mode: raises RuntimeError for a ``-J`` client,
        which prints nothing until it ends.
        """
        if not self._text:
            raise RuntimeError(
                "iperf3 progress() needs Opts(json=False): with -J the "
                "client prints nothing until it ends")
        if not self._job_destroyed:
            for msg in self._intervals.drain():
                for m in _INTERVAL_RE.finditer(msg.data):
                    if m.group(3).rstrip().endswith(("sender", "receiver")):
                        continue
                    moved = _bytes(m.group(1), m.group(2))
                    if moved > 0:
                        self._n_intervals += 1
                        self._interval_bytes += moved
        return self._n_intervals, self._interval_bytes

    def _read_output(self, timeout: float) -> str:
        from pyte import log
        out = self._stdout_filter.read_all(timeout=timeout)
        err = self._stderr_filter.read_all(timeout=timeout)
        log.ring(f"iperf3 client stdout:\n{out}")
        log.ring(f"iperf3 client stderr:\n{err}")
        if self._text and err:
            return f"{out}\n{err}"     # the error line is on stderr
        return out

    def _parse(self, raw: str) -> Report:
        if self._text:
            self._parsed = _parse_text_report(raw)
            return self._parsed
        # iperf3 may print diagnostics before the JSON: strip the prefix.
        json_start = raw.find("{")
        if json_start > 0:
            raw = raw[json_start:]
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise IperfError(
                f"cannot parse iperf3 JSON: {exc}; "
                f"stdout={raw[:200]!r}") from exc
        self._parsed = _parse_report(obj)
        return self._parsed

    def _check_status(self, status, raw) -> None:
        """Accept iperf3's exit 1 after a summary with an error."""
        from pyte.job import StatusKind
        if (status.kind is StatusKind.EXITED and self._parsed is not None
                and self._parsed.error is not None):
            return
        super()._check_status(status, raw)

    def _mi(self, logger, rep: Report) -> None:
        """Emit MI artifacts mirroring iperf3_report_mi_log()."""
        from pyte.mi import Aggr, Meas, Mult
        logger.add(Meas.THROUGHPUT, "Per-stream", Aggr.MIN,
                   rep.min_bps_per_stream, Mult.PLAIN)
        logger.add(Meas.THROUGHPUT, "Transfer", Aggr.SINGLE,
                   rep.sent.bits_per_second, Mult.PLAIN)

    def mi_report(self, tool: str = "iperf3") -> None:
        super().mi_report(tool)


@contextmanager
def server(pco: "RpcServer", opts: "Opts | None" = None, *,
           host: str = "127.0.0.1", ready_delay: float = 1.0):
    """Context manager: run an iperf3 server for the block's duration.

    Yields an :class:`pyte.tools._clientserver.Endpoint`. ``host`` is the
    address the client should target (the server binds all interfaces);
    the port comes from ``opts.port`` (default iperf3 port 5201 when unset).

    Example::

        with iperf3.server(pco, iperf3.Opts(port=5201)) as ep:
            with iperf3.run(pco, iperf3.Opts(host=ep.host, port=ep.port,
                                             duration=2)) as c:
                rep = c.wait()
    """
    opts = opts or Opts()
    port = opts.port if opts.port is not None else 5201
    with serve(pco, "iperf3", opts.server_argv(),
               host=host, port=port, ready_delay=ready_delay) as ep:
        yield ep


@contextmanager
def run(pco: "RpcServer", opts: Opts):
    """Context manager: run an iperf3 *client*; yield an :class:`Iperf3`."""
    def _setup(job):
        # Capture stdout (the -J JSON or the text summary, fed to the
        # parser) and stderr; both are dumped to the TE log by wait()
        # to mirror perf_app_dump_output().  Text mode also greps the
        # interval lines for progress().
        out = job.stdout.attach_filter(name="iperf3_stdout", readable=True)
        err = job.stderr.attach_filter(name="iperf3_stderr", readable=True)
        intervals = (None if opts.json else
                     job.stdout.grep(_INTERVAL_REGEX,
                                     name="iperf3_intervals"))
        return out, err, intervals

    job, (out, err, intervals) = _tool.launch(
        pco, "iperf3", opts.client_argv(), setup=_setup)
    with _tool.running(Iperf3(job, out, err, intervals=intervals)) as c:
        yield c
