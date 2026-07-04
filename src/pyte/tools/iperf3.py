# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools.iperf3 — run iperf3 client/server from Python tests.

Pure Python over pyte.job; zero shim imports. The iperf3 binary is
resolved from the agent's PATH (job program "iperf3"). Gate iperf3 tests
with <req id="IPERF3"/> and the prologue probe.

Pinned mappings (from te/lib/tapi_performance/iperf3.c, tapi_performance.*)
=========================================================================

server argv (build_server_args; bind order port, interval):
    iperf3 -s -J  [-p<port>] [-i<interval>]

client argv (build_client_args; bind order below; each omitted when unset):
    iperf3 -c <host> -J [-B<src_host>] [-p<port>] [-4|-6] [-u]
        [-b<bandwidth_bits>] [-l<length>] [-n<num_bytes>] [-t<duration>]
        [-i<interval>] [-P<streams>] [-R] [--bidir]
    Flags glue the value on (-p5201); only --bidir is long-form. -u for UDP
    only (TCP default). -4/-6 select ip version (client).

report (parsed from iperf3 JSON `end`):
    end.sum_sent.{bits_per_second,bytes,seconds,retransmits}  -> sent
    end.sum_received.{bits_per_second,bytes,seconds}          -> received
    UDP/default: end.sum.* fills both sent and received
    min(end.streams[*].sender.bits_per_second)  -> min_bps_per_stream
    top-level "error"  -> raise IperfError

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
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pyte.tools._clientserver import serve
from pyte.tools._clientserver import Endpoint  # noqa: F401  (re-exported)

if TYPE_CHECKING:
    from pyte.rpc import RpcServer

_VALID_PROTOCOLS = frozenset({"tcp", "udp"})
_VALID_IPVERSIONS = frozenset({"4", "6"})


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

    def __post_init__(self) -> None:
        if self.protocol not in _VALID_PROTOCOLS:
            raise ValueError(
                f"unknown protocol {self.protocol!r}; "
                f"valid: {sorted(_VALID_PROTOCOLS)}")
        if self.ipversion is not None and self.ipversion not in _VALID_IPVERSIONS:
            raise ValueError(
                f"unknown ipversion {self.ipversion!r}; "
                f"valid: {sorted(_VALID_IPVERSIONS)}")

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
        argv = ["-c", self.host, "-J"]
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
    """Parsed iperf3 report."""
    sent: Direction
    received: Direction
    min_bps_per_stream: float


def _direction(d: dict) -> Direction:
    return Direction(
        bits_per_second=float(d["bits_per_second"]),
        bytes=int(d["bytes"]),
        seconds=float(d["seconds"]),
        retransmits=int(d["retransmits"]) if "retransmits" in d else None)


def _parse_report(obj: dict) -> Report:
    """Parse an iperf3 ``-J`` JSON object into a :class:`Report`.

    Raises :exc:`pyte.errors.IperfError` if iperf3 reported an error or the
    expected ``end`` summary is missing.
    """
    from pyte.errors import IperfError

    err = obj.get("error")
    if err:
        raise IperfError(f"iperf3 reported error: {err}")

    end = obj.get("end")
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

    return Report(sent=sent, received=received, min_bps_per_stream=min_bps)


class Iperf3:
    """Lifecycle manager for a running iperf3 *client* job.

    Created via :func:`run`. The JSON report arrives on stdout (``-J``).
    """

    def __init__(self, job, stdout_filter, stderr_filter):
        self._job = job
        self._stdout_filter = stdout_filter
        self._stderr_filter = stderr_filter
        self._report: Report | None = None
        self._closed = False

    def wait(self, timeout: float = 60.0) -> Report:
        """Wait for the client to finish, parse JSON, return a Report.

        Caches the report. Raises :exc:`pyte.errors.IperfError` on a
        non-zero exit or unparseable output.

        The full stdout and stderr are dumped to the TE log (RING) before
        parsing, mirroring the C tapi_performance perf_app_dump_output().
        """
        if self._report is not None:
            return self._report

        from pyte import log
        from pyte.errors import IperfError

        status = self._job.wait(timeout=timeout)
        out = self._stdout_filter.read_all(timeout=timeout)
        err = self._stderr_filter.read_all(timeout=timeout)
        # Mirror perf_app_dump_output(): RING the full stdout/stderr with the
        # same "<bench> <tag> stdout|stderr:\n<...>" labelling the C uses.
        log.ring(f"iperf3 client stdout:\n{out}")
        log.ring(f"iperf3 client stderr:\n{err}")
        raw = out
        json_start = raw.find("{")
        if json_start > 0:
            raw = raw[json_start:]
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise IperfError(
                f"cannot parse iperf3 JSON: {exc}; "
                f"exit={status}; stdout={raw[:200]!r}") from exc
        report = _parse_report(obj)
        if not status.ok:
            # iperf3 prints a JSON error object and exits non-zero; the
            # parse above already raised IperfError for the "error" field,
            # so a non-zero exit with parseable non-error JSON is unusual.
            raise IperfError(
                f"iperf3 client exited with {status}")
        self._report = report
        return self._report

    def mi_report(self, tool: str = "iperf3") -> None:
        """Emit MI artifacts mirroring iperf3_report_mi_log().

        Requires :meth:`wait` first.
        """
        if self._report is None:
            raise RuntimeError("call wait() before mi_report()")
        rep = self._report
        from pyte.mi import Aggr, Logger, Meas, Mult
        with Logger(tool) as logger:
            logger.add(Meas.THROUGHPUT, "Per-stream", Aggr.MIN,
                       rep.min_bps_per_stream, Mult.PLAIN)
            logger.add(Meas.THROUGHPUT, "Transfer", Aggr.SINGLE,
                       rep.sent.bits_per_second, Mult.PLAIN)

    def close(self) -> None:
        """Stop the client (errors tolerated) and destroy the job."""
        if self._closed:
            return
        self._closed = True
        from pyte.errors import TeError
        try:
            self._job.stop()
        except TeError:
            pass
        self._job.destroy()


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
    job = pco.job("iperf3", opts.client_argv())
    try:
        # Capture stdout (the -J JSON, fed to the parser) and stderr; both are
        # dumped to the TE log by wait() to mirror perf_app_dump_output().
        stdout_filter = job.stdout.attach_filter(
            name="iperf3_stdout", readable=True)
        stderr_filter = job.stderr.attach_filter(
            name="iperf3_stderr", readable=True)
        job.start()
    except Exception:
        job.destroy()
        raise
    client = Iperf3(job, stdout_filter, stderr_filter)
    try:
        yield client
    finally:
        client.close()
