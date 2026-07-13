# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools.ping — run ping from Python tests via pyte.job.

Pure Python over pyte.job's public API; zero shim imports. The ping
binary is resolved from the agent's PATH (the job program is "ping").
Gate ping tests with <req id="PING"/> and the prologue probe.

Pinned mappings (from te/lib/tapi_tool/tapi_ping.{h,c})
========================================================

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
    RTT MIN/MEAN/MAX/STDEV in MILLI  ->  Logger.add(Meas.RTT, ..., Mult.MILLI)
"""
from __future__ import annotations

import re
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pyte.errors import PingError
from pyte.tools import _tool

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


class Ping(_tool.ToolHandle):
    """Lifecycle manager for a running ping job.

    Normally created via :func:`run` (a context manager). All I/O happens
    over ``pco.job("ping", argv)``; the summary arrives on stdout.

    wait() is parse-first and never raises on a parseable run's exit
    status: a normal ping with 100% loss exits non-zero but still
    prints a valid summary (the ``_check_status`` no-op below).
    """

    tool = "ping"
    error_cls = PingError
    default_timeout = 60.0

    def _parse(self, raw: str) -> Report:
        return _parse_report(raw)

    def _check_status(self, status, raw) -> None:
        pass    # 100%-loss runs exit non-zero with a valid summary

    def mi_report(self, tool: str = "ping") -> None:
        """Emit MI artifacts mirroring tapi_ping_report_mi_log().

        No-op when the report has no rtt stats (matches the C TAPI,
        which returns early when !with_rtt) — no MI logger is even
        created then.
        """
        rep = self.wait()
        if not rep.with_rtt or rep.rtt is None:
            return
        super().mi_report(tool)

    def _mi(self, logger, rep: Report) -> None:
        from pyte.mi import Aggr, Meas, Mult
        logger.add(Meas.RTT, "Min RTT", Aggr.MIN, rep.rtt.min, Mult.MILLI)
        logger.add(Meas.RTT, "Mean RTT", Aggr.MEAN, rep.rtt.avg, Mult.MILLI)
        logger.add(Meas.RTT, "Max RTT", Aggr.MAX, rep.rtt.max, Mult.MILLI)
        logger.add(Meas.RTT, "RTT stdev", Aggr.STDEV, rep.rtt.mdev,
                   Mult.MILLI)


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
    def _setup(job):
        flt = job.stdout.attach_filter(name="ping_stdout", readable=True)
        job.stderr.log(level="ERROR")
        return flt

    job, flt = _tool.launch(pco, "ping", opts.to_argv(), setup=_setup)
    with _tool.running(Ping(job, flt)) as p:
        yield p
