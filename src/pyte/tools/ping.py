# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools.ping — run ping from Python tests via pyte.job.

Pure Python over pyte.job's public API; zero shim imports. The ping
binary is resolved from the agent's PATH (the job program is "ping").
Gate ping tests with <req id="PING"/> and the prologue probe.

Pinned mappings (from te/lib/tapi_tool/tapi_ping.{h,c})
======================================================

argv (ping_binds order; each flag omitted when unset):
    -c <packet_count>   -s <packet_size>   -i <interval>
    -I <interface>      <destination>   (positional, required)

Report (parsed from the summary block):
    "(N) packets transmitted"  -> transmitted
    "(N) received"             -> received
    "(N)% packet loss"         -> lost_percentage
    "rtt ... = min/avg/max/mdev ms" -> rtt.{min,avg,max,mdev}

with_rtt: the C TAPI gates rtt parsing on packet_size >= 16
(TAPI_PING_MIN_PACKET_SIZE_FOR_RTT_STATS). pyte parses captured text, so
it derives with_rtt from whether the rtt line is present — a deliberate,
faithful-enough deviation (cf. fio's stdout/stderr inversion).

MI (tapi_ping_report_mi_log, only when with_rtt):
    RTT MIN/MEAN/MAX/STDEV in MILLI  ->  Logger.add("rtt", ..., "milli")
"""
from __future__ import annotations

import re
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyte.rpc import RpcServer

# Mirrors TAPI_PING_MIN_PACKET_SIZE_FOR_RTT_STATS (documented; pyte derives
# with_rtt from output presence rather than this threshold).
MIN_PACKET_SIZE_FOR_RTT_STATS = 16


@dataclass(frozen=True)
class Opts:
    """ping command-line options.

    Parameters
    ----------
    destination:
        Address or hostname to ping (required; positional argument).
    packet_count:
        ``-c`` count; None sends until stopped.
    packet_size:
        ``-s`` payload bytes; None uses ping's 56-byte default.
    interval:
        ``-i`` seconds between packets; None uses ping's 1s default.
    interface:
        ``-I`` source address or interface; None lets ping choose.
    """
    destination: str
    packet_count: int | None = None
    packet_size: int | None = None
    interval: float | None = None
    interface: str | None = None

    def __post_init__(self) -> None:
        if not self.destination:
            raise ValueError("Opts.destination is required")

    def to_argv(self) -> list[str]:
        """Build the ping argument list (without argv[0]).

        Mirrors ping_binds order: -c, -s, -i, -I, then destination.
        """
        argv: list[str] = []
        if self.packet_count is not None:
            argv += ["-c", str(self.packet_count)]
        if self.packet_size is not None:
            argv += ["-s", str(self.packet_size)]
        if self.interval is not None:
            argv += ["-i", str(self.interval)]
        if self.interface is not None:
            argv += ["-I", self.interface]
        argv.append(self.destination)
        return argv


@dataclass(frozen=True)
class RttStats:
    """RTT statistics (milliseconds)."""
    min: float
    avg: float
    max: float
    mdev: float


@dataclass(frozen=True)
class Report:
    """Parsed ping summary (mirrors tapi_ping_report)."""
    transmitted: int
    received: int
    lost_percentage: int
    with_rtt: bool
    rtt: RttStats | None


_RE_TRANS = re.compile(r"(\d+) packets transmitted")
_RE_RECV = re.compile(r"(\d+) received")
_RE_LOSS = re.compile(r"(\d+)% packet loss")
_RE_RTT = re.compile(
    r"rtt[^=]*=\s*"
    r"([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+)\s*ms")


def _parse_report(text: str) -> Report:
    """Parse ping's textual summary into a :class:`Report`.

    Raises :exc:`pyte.errors.PingError` if the transmitted/received/loss
    counters are absent (i.e. the text is not a ping summary).
    """
    from pyte.errors import PingError

    m_trans = _RE_TRANS.search(text)
    m_recv = _RE_RECV.search(text)
    m_loss = _RE_LOSS.search(text)
    if not (m_trans and m_recv and m_loss):
        raise PingError(
            f"cannot parse ping summary; output={text[:200]!r}")

    m_rtt = _RE_RTT.search(text)
    if m_rtt is not None:
        rtt = RttStats(
            min=float(m_rtt.group(1)),
            avg=float(m_rtt.group(2)),
            max=float(m_rtt.group(3)),
            mdev=float(m_rtt.group(4)))
    else:
        rtt = None

    return Report(
        transmitted=int(m_trans.group(1)),
        received=int(m_recv.group(1)),
        lost_percentage=int(m_loss.group(1)),
        with_rtt=rtt is not None,
        rtt=rtt)


class Ping:
    """Lifecycle manager for a running ping job.

    Normally created via :func:`run` (a context manager). All I/O happens
    over ``pco.job("ping", argv)``; the summary arrives on stdout.
    """

    def __init__(self, job, stdout_filter):
        self._job = job
        self._stdout_filter = stdout_filter
        self._report: Report | None = None
        self._closed = False

    def wait(self, timeout: float = 60.0) -> Report:
        """Wait for ping to finish, parse the summary, return a Report.

        Caches the report. Raises :exc:`pyte.errors.PingError` on a
        non-zero exit whose output is also unparseable. (A normal ping
        with 100% loss exits non-zero but still prints a parseable
        summary, so we parse first and only raise if parsing fails.)
        """
        if self._report is not None:
            return self._report

        from pyte.errors import PingError

        status = self._job.wait(timeout=timeout)
        raw = self._stdout_filter.read_all(timeout=timeout)
        try:
            self._report = _parse_report(raw)
        except PingError:
            if not status.ok:
                raise PingError(
                    f"ping exited with {status}; stdout={raw[:200]!r}")
            raise
        return self._report

    def mi_report(self, tool: str = "ping") -> None:
        """Emit MI artifacts mirroring tapi_ping_report_mi_log().

        No-op when the report has no rtt stats (matches the C TAPI, which
        returns early when !with_rtt). Requires :meth:`wait` first.
        """
        if self._report is None:
            raise RuntimeError("call wait() before mi_report()")
        rep = self._report
        if not rep.with_rtt or rep.rtt is None:
            return
        from pyte.mi import Logger
        with Logger(tool) as logger:
            logger.add("rtt", "Min RTT", "min", rep.rtt.min, "milli")
            logger.add("rtt", "Mean RTT", "mean", rep.rtt.avg, "milli")
            logger.add("rtt", "Max RTT", "max", rep.rtt.max, "milli")
            logger.add("rtt", "RTT stdev", "stdev", rep.rtt.mdev, "milli")

    def close(self) -> None:
        """Stop ping (errors tolerated) and destroy the job (idempotent)."""
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
    """Context manager: create, start, and clean up a ping job.

    Yields a :class:`Ping`; call :meth:`Ping.wait` inside the block.

    Example::

        with ping.run(pco, ping.Opts(destination="127.0.0.1",
                                     packet_count=4)) as p:
            rep = p.wait()
            print(rep.rtt.avg)
    """
    job = pco.job("ping", opts.to_argv())
    try:
        stdout_filter = job.stdout.attach_filter(
            name="ping_stdout", readable=True)
        job.stderr.log(level="ERROR")
        job.start()
    except Exception:
        job.destroy()
        raise
    ping_obj = Ping(job, stdout_filter)
    try:
        yield ping_obj
    finally:
        ping_obj.close()
