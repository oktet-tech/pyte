# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools.wrk — run wrk HTTP benchmark from Python tests via pyte.job.

Pure Python over pyte.job's public API; zero shim imports. The wrk binary
is resolved from the agent's PATH (the job program is "wrk").
Gate wrk tests with <req id="WRK"/> and the prologue probe.

Pinned mappings (from te/lib/tapi_tool/tapi_wrk.{h,c})
=======================================================

argv (wrk opt-bind order; each flag omitted when unset/zero):
    --connections <n>   --threads <n>   --duration <n>s   [--latency]
    <url>  (positional, required)
    [--header "<H>" ...]   [--script <path>]
    [--rate <n>]   [--affinity <list>]   [<script_arg> ...]

Note: timeout_ms exists in the C struct but is not emitted (wrk has no
CLI timeout flag) — pyte omits it too. --duration carries an 's' suffix.

Report (tapi_wrk_report), parsed from wrk's stdout. Unit scales mirror
the C parse_unit tables:

- time → microseconds: us=1, ms=1e3, s=1e6, m=60e6, h=3600e6
- metric (req counts) → base, scale 1000: ""=1, k=1e3, M=1e6, G=1e9, T=1e12, P=1e15
- binary (bytes) → base, scale 1024: ""=1, K=1024, M=1024^2, G=1024^3, T, P
- percent: strip trailing %

Regexes + targets (tapi_wrk.c:227-292):

    r"(\\d+) requests in"                       → req_count (int)
    r"Transfer/sec:\\s*(\\S+)B"                  → bps (binary-unit float, bytes/s)
    r"Requests/sec:\\s*(\\S+)"                   → req_per_sec (plain float)
    r"Latency\\s+(.*%)"                         → thread_latency: 4 tokens
                                                  mean,stdev,max (time µs) + within_stdev (%)
    r"Req/Sec\\s+(.*%)"                         → thread_req_per_sec: 4 tokens
                                                  mean,stdev,max (metric) + within_stdev (%)
    "Latency Distribution" block, lines "<p>% <lat>" → lat_distr (4 entries:
                                                  percentile %, latency µs)  [only with --latency]
    r"Non-2xx or 3xx responses:\\s*(\\d+)"       → unexpected_resp (int)  [absent → 0]
    r"Socket errors:\\s*connect (-?\\d+), read (-?\\d+), write (-?\\d+), timeout (-?\\d+)"
                                               → socket_errors c/r/w/t (int) [absent → all 0]

MI (tapi_wrk_report_mi_log, tapi_wrk.c:571-580):

    THROUGHPUT NULL        MEAN  bps*8.0                  MEGA
    RPS        NULL        MEAN  req_per_sec              PLAIN
    LATENCY    "per-thread" MEAN thread_latency.mean      MICRO
    LATENCY    "per-thread" MAX  thread_latency.max       MICRO
    LATENCY    "per-thread" STDEV thread_latency.stdev    MICRO
    RPS        "per-thread" MEAN thread_req_per_sec.mean  PLAIN
    RPS        "per-thread" MAX  thread_req_per_sec.max   PLAIN
    RPS        "per-thread" STDEV thread_req_per_sec.stdev PLAIN
"""
from __future__ import annotations

import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyte.rpc import RpcServer

# ---------------------------------------------------------------------------
# Unit-scale dictionaries (mirror tapi_wrk.c parse_unit tables)
# ---------------------------------------------------------------------------

from pyte.tools._units import (BINARY as _BINARY,  # noqa: E402
                               METRIC as _METRIC,
                               PERCENT as _PERCENT,
                               TIME_US as _TIME_US,
                               parse_unit as _parse_unit)


# ---------------------------------------------------------------------------
# Frozen report dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ThreadStats:
    """Stats for one wrk thread-stats line (Latency or Req/Sec)."""
    mean: float
    stdev: float
    max: float
    within_stdev: float


@dataclass(frozen=True)
class LatencyPercentile:
    """One entry from the Latency Distribution block."""
    percentile: float   # e.g. 50.0, 75.0, 90.0, 99.0
    latency: float      # µs


@dataclass(frozen=True)
class SocketErrors:
    """Socket error counters."""
    connect: int
    read: int
    write: int
    timeout: int


@dataclass(frozen=True)
class Report:
    """Parsed wrk output (mirrors tapi_wrk_report)."""
    thread_latency: ThreadStats
    thread_req_per_sec: ThreadStats
    lat_distr: tuple[LatencyPercentile, ...]
    req_count: int
    req_per_sec: float
    bps: float
    unexpected_resp: int
    socket_errors: SocketErrors


# ---------------------------------------------------------------------------
# Options dataclass
# ---------------------------------------------------------------------------

@dataclass
class Opts:
    """wrk command-line options.

    Parameters
    ----------
    url:
        Target URL (required; positional argument).
    connections:
        ``--connections`` count; None omits the flag.
    threads:
        ``--threads`` count; None omits the flag.
    duration:
        ``--duration <n>s`` seconds; None omits the flag.
    latency:
        ``--latency`` flag; False omits it.
    headers:
        ``--header H`` repeated flags; empty list omits them.
    script:
        ``--script <path>``; None omits it.
    rate:
        ``--rate <n>``; None omits it.
    affinity:
        ``--affinity <list>``; None omits it.
    script_args:
        Positional script arguments appended last.
    """
    url: str
    connections: int | None = None
    threads: int | None = None
    duration: int | None = None
    latency: bool = False
    headers: list[str] = field(default_factory=list)
    script: str | None = None
    rate: int | None = None
    affinity: str | None = None
    script_args: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.url:
            raise ValueError("Opts.url is required")

    def to_argv(self) -> list[str]:
        """Build the wrk argument list (without argv[0]).

        Mirrors wrk opt-bind order:
        --connections, --threads, --duration Ns, --latency, <url>,
        --header H (repeated), --script, --rate, --affinity,
        then script_args.
        """
        argv: list[str] = []
        if self.connections is not None:
            argv += ["--connections", str(self.connections)]
        if self.threads is not None:
            argv += ["--threads", str(self.threads)]
        if self.duration is not None:
            argv += ["--duration", f"{self.duration}s"]
        if self.latency:
            argv.append("--latency")
        argv.append(self.url)
        for h in self.headers:
            argv += ["--header", h]
        if self.script is not None:
            argv += ["--script", self.script]
        if self.rate is not None:
            argv += ["--rate", str(self.rate)]
        if self.affinity is not None:
            argv += ["--affinity", self.affinity]
        argv.extend(self.script_args)
        return argv


# ---------------------------------------------------------------------------
# Compiled regexes
# ---------------------------------------------------------------------------

_RE_REQ_COUNT = re.compile(r"(\d+) requests in")
_RE_TRANSFER  = re.compile(r"Transfer/sec:\s*(\S+)B")
_RE_REQ_SEC   = re.compile(r"Requests/sec:\s*(\S+)")
_RE_LATENCY   = re.compile(r"Latency\s+(.*%)")
_RE_REQSEC    = re.compile(r"Req/Sec\s+(.*%)")
_RE_NON2XX    = re.compile(r"Non-2xx or 3xx responses:\s*(\d+)")
_RE_SOCKERR   = re.compile(
    r"Socket errors:\s*"
    r"connect (-?\d+), read (-?\d+), write (-?\d+), timeout (-?\d+)")
_RE_LAT_DISTR_ENTRY = re.compile(r"\s*([\d.]+)%\s+([\d.]+\w+)")


def _parse_thread_stats(line_group: str, time_scale: bool) -> ThreadStats:
    """Parse the 4-token stats group from a Latency or Req/Sec match.

    Parameters
    ----------
    line_group:
        The ``(.*)%`` capture group from the Latency/Req-Sec regex.
    time_scale:
        If True, parse mean/stdev/max with :data:`_TIME_US`;
        if False, parse with :data:`_METRIC`.
    """
    tokens = line_group.split()
    # tokens: [mean, stdev, max, within_stdev%]
    scale = _TIME_US if time_scale else _METRIC
    mean   = _parse_unit(tokens[0], scale)
    stdev  = _parse_unit(tokens[1], scale)
    max_   = _parse_unit(tokens[2], scale)
    within = _parse_unit(tokens[3], _PERCENT)  # percent: suffix stripped
    return ThreadStats(mean=mean, stdev=stdev, max=max_, within_stdev=within)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def _parse_report(text: str) -> Report:
    """Parse wrk's textual output into a :class:`Report`.

    Raises :exc:`pyte.errors.WrkError` if the ``(\\d+) requests in`` line
    is absent (i.e. the text is not a wrk summary).
    """
    from pyte.errors import WrkError

    m_req_count = _RE_REQ_COUNT.search(text)
    if not m_req_count:
        raise WrkError(
            f"cannot parse wrk output; text={text[:200]!r}")

    req_count = int(m_req_count.group(1))

    m_transfer = _RE_TRANSFER.search(text)
    bps = _parse_unit(m_transfer.group(1), _BINARY) if m_transfer else 0.0

    m_req_sec = _RE_REQ_SEC.search(text)
    req_per_sec = _parse_unit(m_req_sec.group(1), _METRIC) if m_req_sec else 0.0

    m_lat = _RE_LATENCY.search(text)
    thread_latency = (_parse_thread_stats(m_lat.group(1), time_scale=True)
                      if m_lat
                      else ThreadStats(0.0, 0.0, 0.0, 0.0))

    m_rps = _RE_REQSEC.search(text)
    thread_req_per_sec = (_parse_thread_stats(m_rps.group(1), time_scale=False)
                          if m_rps
                          else ThreadStats(0.0, 0.0, 0.0, 0.0))

    # Latency Distribution block (optional)
    lat_distr: list[LatencyPercentile] = []
    if "Latency Distribution" in text:
        block_start = text.index("Latency Distribution")
        # Find the end of the block: stop at the first line that doesn't
        # contain a percentile entry (e.g. the "requests in" line).
        block_text = text[block_start:]
        for m in _RE_LAT_DISTR_ENTRY.finditer(block_text):
            if len(lat_distr) >= 4:
                break
            pct = float(m.group(1))
            lat = _parse_unit(m.group(2), _TIME_US)
            lat_distr.append(LatencyPercentile(percentile=pct, latency=lat))

    m_non2xx = _RE_NON2XX.search(text)
    unexpected_resp = int(m_non2xx.group(1)) if m_non2xx else 0

    m_sockerr = _RE_SOCKERR.search(text)
    if m_sockerr:
        socket_errors = SocketErrors(
            connect=int(m_sockerr.group(1)),
            read=int(m_sockerr.group(2)),
            write=int(m_sockerr.group(3)),
            timeout=int(m_sockerr.group(4)),
        )
    else:
        socket_errors = SocketErrors(connect=0, read=0, write=0, timeout=0)

    return Report(
        thread_latency=thread_latency,
        thread_req_per_sec=thread_req_per_sec,
        lat_distr=tuple(lat_distr),
        req_count=req_count,
        req_per_sec=req_per_sec,
        bps=bps,
        unexpected_resp=unexpected_resp,
        socket_errors=socket_errors,
    )


# ---------------------------------------------------------------------------
# Wrk handle
# ---------------------------------------------------------------------------

class Wrk:
    """Lifecycle manager for a running wrk job.

    Normally created via :func:`run` (a context manager). All I/O happens
    over ``pco.job("wrk", argv)``; the output arrives on stdout.
    """

    def __init__(self, job, stdout_filter):
        self._job = job
        self._stdout_filter = stdout_filter
        self._report: Report | None = None
        self._closed = False

    def wait(self, timeout: float = 120.0) -> Report:
        """Wait for wrk to finish, parse the output, return a Report.

        Caches the report. Raises :exc:`pyte.errors.WrkError` if the
        process exits with an error and the output is also unparseable.
        """
        if self._report is not None:
            return self._report

        from pyte.errors import WrkError

        status = self._job.wait(timeout=timeout)
        raw = self._stdout_filter.read_all(timeout=timeout)
        try:
            self._report = _parse_report(raw)
        except WrkError:
            if not status.ok:
                raise WrkError(
                    f"wrk exited with {status}; stdout={raw[:200]!r}")
            raise
        return self._report

    def mi_report(self, tool: str = "wrk") -> None:
        """Emit MI artifacts mirroring tapi_wrk_report_mi_log().

        Requires :meth:`wait` first.
        """
        if self._report is None:
            raise RuntimeError("call wait() before mi_report()")
        from pyte.mi import Aggr, Logger, Meas, Mult
        rep = self._report
        with Logger(tool) as logger:
            logger.add(Meas.THROUGHPUT, "", Aggr.MEAN,
                       rep.bps * 8.0 / 1e6, Mult.MEGA)
            logger.add(Meas.RPS, "", Aggr.MEAN, rep.req_per_sec, Mult.PLAIN)
            logger.add(Meas.LATENCY, "per-thread", Aggr.MEAN,
                       rep.thread_latency.mean, Mult.MICRO)
            logger.add(Meas.LATENCY, "per-thread", Aggr.MAX,
                       rep.thread_latency.max, Mult.MICRO)
            logger.add(Meas.LATENCY, "per-thread", Aggr.STDEV,
                       rep.thread_latency.stdev, Mult.MICRO)
            logger.add(Meas.RPS, "per-thread", Aggr.MEAN,
                       rep.thread_req_per_sec.mean, Mult.PLAIN)
            logger.add(Meas.RPS, "per-thread", Aggr.MAX,
                       rep.thread_req_per_sec.max, Mult.PLAIN)
            logger.add(Meas.RPS, "per-thread", Aggr.STDEV,
                       rep.thread_req_per_sec.stdev, Mult.PLAIN)

    def close(self) -> None:
        """Stop wrk (errors tolerated) and destroy the job (idempotent)."""
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
def run(pco: "RpcServer", opts: Opts):
    """Context manager: create, start, and clean up a wrk job.

    Yields a :class:`Wrk`; call :meth:`Wrk.wait` inside the block.

    Example::

        with wrk.run(pco, wrk.Opts(url="http://127.0.0.1:8080/",
                                    connections=4, threads=2,
                                    duration=10, latency=True)) as w:
            rep = w.wait(timeout=30.0)
            print(rep.req_per_sec)
    """
    job = pco.job("wrk", opts.to_argv())
    try:
        stdout_filter = job.stdout.attach_filter(
            name="wrk_stdout", readable=True)
        job.stderr.log(level="ERROR")
        job.start()
    except Exception:
        job.destroy()
        raise
    wrk_obj = Wrk(job, stdout_filter)
    try:
        yield wrk_obj
    finally:
        wrk_obj.close()
