# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools.sfnt_pingpong — run sfnt-pingpong client/server from Python tests.

Pure Python over pyte.job's public API; zero shim imports. The
sfnt-pingpong binary is resolved from the agent's PATH (job program
"sfnt-pingpong"). Gate sfnt-pingpong tests with <req id="SFNT_PINGPONG"/>
and the prologue probe.

Pinned mapping (from te/lib/tapi_tool/tapi_sfnt_pingpong.{h,c})
================================================================

Server argv: none — sfnt-pingpong with no arguments
(tapi_sfnt_pingpong.c:307).

Client argv (opt-bind order, tapi_sfnt_pingpong.c:223-237; ``=``-joined
ints):

    --sizes=<csv>  --minmsg=<n>  --maxmsg=<n>  --minms=<n>  --maxms=<n>
    --miniter=<n>  --maxiter=<n>  [--spin]  --muxer=<none|poll|select|epoll>
    --timeout=<n>  [--ipv4|--ipv6]  <tcp|udp>  <server-addr>

``<proto>`` is a bare positional ``tcp``/``udp`` (NOT a flag), then the
server address positional.  Int flags use ``--name=<value>``.  ``--spin``
is presence-only.  Each ``--name=`` omitted when its value is None;
``--sizes=`` omitted when no sizes.

Report + parsing (tapi_sfnt_pingpong.c:483-523): sfnt-pingpong prints a
table; each data row is 8 whitespace-separated integers.  The C
``sscanf("%d %d %d %d %d %d %d %*d", &size,&mean,&min,&median,&max,
&percentile,&stddev)`` maps columns: ``size mean min median max %ile
stddev iter`` (8th ``iter`` ignored).  Values are in nanoseconds.
Header/comment lines are not 8-int rows and are skipped.  Parse into a
list of ``Row(size, mean, min, median, max, percentile, stddev)``;
``Report.rows`` is the tuple of rows.  Raise ``SfntError`` if no data row
is found.

MI (tapi_sfnt_pp_mi_report, tapi_sfnt_pingpong.c:599-629), per row:

    LATENCY "1/2 RTT latency"      MEAN/MIN/MEDIAN/MAX/STDEV  <field>  NANO
    LATENCY "1/2 RTT latency (99)" PERCENTILE                 percentile NANO
    (+ "Size" integer key in C)

pyte deviation: pyte.mi.Logger has no key API, so the size is embedded
in the measurement name suffix (e.g. "1/2 RTT latency [size=64]").
"""
from __future__ import annotations

import re
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pyte.errors import SfntError
from pyte.tools import _tool
from pyte.tools._clientserver import serve
from pyte.tools._tool import check_ipversion
from pyte.tools._clientserver import Endpoint  # noqa: F401  (re-exported)

if TYPE_CHECKING:
    from pyte.rpc import RpcServer

_VALID_PROTO = frozenset({"tcp", "udp"})
_VALID_MUXER = frozenset({"none", "poll", "select", "epoll"})


@dataclass(frozen=True)
class Opts:
    """sfnt-pingpong options (shared by the server and client argv builders).

    Parameters
    ----------
    server:
        Client target server address (positional); required for
        :meth:`client_argv`, ignored by :meth:`server_argv`.
    proto:
        Transport protocol: ``"udp"`` (default) or ``"tcp"`` (bare
        positional in the client argv).
    ipversion:
        ``"4"`` or ``"6"`` (``--ipv4``/``--ipv6``). None: sfnt-pingpong
        default.
    min_msg:
        ``--minmsg=<n>`` minimum message size.
    max_msg:
        ``--maxmsg=<n>`` maximum message size.
    min_ms:
        ``--minms=<n>`` minimum measurement duration (ms).
    max_ms:
        ``--maxms=<n>`` maximum measurement duration (ms).
    min_iter:
        ``--miniter=<n>`` minimum iterations.
    max_iter:
        ``--maxiter=<n>`` maximum iterations.
    spin:
        ``--spin`` busy-wait flag.
    muxer:
        ``--muxer=<m>`` multiplexer: ``"none"``, ``"poll"``,
        ``"select"``, or ``"epoll"``.
    timeout_ms:
        ``--timeout=<n>`` timeout in milliseconds.
    sizes:
        ``--sizes=<csv>`` explicit message sizes to measure.
    """
    server: str | None = None
    proto: str = "udp"
    ipversion: str | None = None
    min_msg: int | None = None
    max_msg: int | None = None
    min_ms: int | None = None
    max_ms: int | None = None
    min_iter: int | None = None
    max_iter: int | None = None
    spin: bool = False
    muxer: str | None = None
    timeout_ms: int | None = None
    sizes: list[int] | None = None

    def __post_init__(self) -> None:
        if self.proto not in _VALID_PROTO:
            raise ValueError(
                f"unknown proto {self.proto!r}; "
                f"valid: {sorted(_VALID_PROTO)}")
        if self.muxer is not None and self.muxer not in _VALID_MUXER:
            raise ValueError(
                f"unknown muxer {self.muxer!r}; "
                f"valid: {sorted(_VALID_MUXER)}")
        check_ipversion(self.ipversion)

    def server_argv(self) -> list[str]:
        """Build the sfnt-pingpong server argument list (without argv[0]).

        sfnt-pingpong takes no arguments as server (tapi_sfnt_pingpong.c:307).
        """
        return []

    def client_argv(self) -> list[str]:
        """Build the sfnt-pingpong client argument list (without argv[0]).

        Mirrors opt-bind order from tapi_sfnt_pingpong.c:223-237.
        """
        if not self.server:
            raise ValueError("Opts.server is required for the client")
        argv: list[str] = []
        if self.sizes:
            argv.append(f"--sizes={','.join(str(s) for s in self.sizes)}")
        if self.min_msg is not None:
            argv.append(f"--minmsg={self.min_msg}")
        if self.max_msg is not None:
            argv.append(f"--maxmsg={self.max_msg}")
        if self.min_ms is not None:
            argv.append(f"--minms={self.min_ms}")
        if self.max_ms is not None:
            argv.append(f"--maxms={self.max_ms}")
        if self.min_iter is not None:
            argv.append(f"--miniter={self.min_iter}")
        if self.max_iter is not None:
            argv.append(f"--maxiter={self.max_iter}")
        if self.spin:
            argv.append("--spin")
        if self.muxer is not None:
            argv.append(f"--muxer={self.muxer}")
        if self.timeout_ms is not None:
            argv.append(f"--timeout={self.timeout_ms}")
        if self.ipversion is not None:
            argv.append(f"--ipv{self.ipversion}")
        argv.append(self.proto)
        argv.append(self.server)
        return argv


@dataclass(frozen=True)
class Row:
    """One row of sfnt-pingpong output (all values in nanoseconds)."""
    size: int
    mean: int
    min: int
    median: int
    max: int
    percentile: int
    stddev: int


@dataclass(frozen=True)
class Report:
    """Parsed sfnt-pingpong report: a tuple of per-message-size rows."""
    rows: tuple[Row, ...]


# Matches a data row: 8 whitespace-separated integers (header/comment lines
# have non-digit chars and never match).
_RE_ROW = re.compile(r"^[ \t]*(\d+(?:[ \t]+\d+){7})[ \t]*$", re.MULTILINE)


def _parse_report(text: str) -> Report:
    """Parse sfnt-pingpong's tabular output into a :class:`Report`.

    Each data row is 8 whitespace-separated integers mapping to:
    ``size mean min median max %ile stddev iter`` (8th ``iter`` dropped).

    Raises :exc:`pyte.errors.SfntError` if no data row is found.
    """
    from pyte.errors import SfntError

    matches = _RE_ROW.findall(text)
    if not matches:
        raise SfntError(
            f"cannot parse sfnt-pingpong table; "
            f"no data rows found in output={text[:200]!r}")
    rows = []
    for m in matches:
        parts = m.split()
        nums = [int(p) for p in parts]
        # Columns: size(0) mean(1) min(2) median(3) max(4) percentile(5) stddev(6) iter(7)
        rows.append(Row(
            size=nums[0],
            mean=nums[1],
            min=nums[2],
            median=nums[3],
            max=nums[4],
            percentile=nums[5],
            stddev=nums[6],
        ))
    return Report(rows=tuple(rows))


class SfntPingpong(_tool.ToolHandle):
    """Lifecycle manager for a running sfnt-pingpong *client* job.

    Created via :func:`run`. The latency table arrives on stdout.
    wait() is parse-first (ping-style dual-path) and does not judge
    the exit status of a run whose table parsed.
    """

    tool = "sfnt-pingpong client"
    error_cls = SfntError
    default_timeout = 120.0

    def _parse(self, raw: str) -> Report:
        return _parse_report(raw)

    def _check_status(self, status, raw) -> None:
        pass    # a parseable table is a result, whatever the exit status

    def mi_report(self, tool: str = "sfnt-pingpong") -> None:
        """Emit MI artifacts mirroring tapi_sfnt_pp_mi_report().

        Per row emits six LATENCY measurements with multiplier ``nano``:
        mean, min, median, max, stdev, and percentile (99th).  The size
        is embedded in the measurement name since pyte.mi has no key API
        (documented deviation).  One Logger per row, so the base's
        single-logger mi_report() is overridden wholesale.
        """
        rep = self.wait()
        from pyte.mi import Aggr, Logger, Meas, Mult
        for row in rep.rows:
            name = f"1/2 RTT latency [size={row.size}]"
            name99 = f"1/2 RTT latency (99) [size={row.size}]"
            with Logger(tool) as logger:
                logger.add(Meas.LATENCY, name, Aggr.MEAN,
                           row.mean, Mult.NANO)
                logger.add(Meas.LATENCY, name, Aggr.MIN,
                           row.min, Mult.NANO)
                logger.add(Meas.LATENCY, name, Aggr.MEDIAN,
                           row.median, Mult.NANO)
                logger.add(Meas.LATENCY, name, Aggr.MAX,
                           row.max, Mult.NANO)
                logger.add(Meas.LATENCY, name, Aggr.STDEV,
                           row.stddev, Mult.NANO)
                logger.add(Meas.LATENCY, name99, Aggr.PERCENTILE,
                           row.percentile, Mult.NANO)


@contextmanager
def server(pco: "RpcServer", opts: "Opts | None" = None, *,
           host: str = "127.0.0.1", port: int = 0,
           ready_delay: float = 1.0):
    """Context manager: run an sfnt-pingpong server for the block's duration.

    Yields an :class:`pyte.tools._clientserver.Endpoint`. ``host`` is the
    address the client should target (the server binds all interfaces).
    ``port`` is informational (sfnt-pingpong picks its own port).

    Example::

        with sfnt_pingpong.server(pco, sfnt_pingpong.Opts()) as ep:
            copts = sfnt_pingpong.Opts(server=ep.host, proto="tcp")
            with sfnt_pingpong.run(pco, copts) as c:
                rep = c.wait()
    """
    opts = opts or Opts()
    with serve(pco, "sfnt-pingpong", opts.server_argv(),
               host=host, port=port, ready_delay=ready_delay) as ep:
        yield ep


@contextmanager
def run(pco: "RpcServer", opts: Opts):
    """Context manager: run an sfnt-pingpong *client*; yield a
    :class:`SfntPingpong`."""
    def _setup(job):
        flt = job.stdout.attach_filter(name="sfnt_pingpong_stdout",
                                       readable=True)
        job.stderr.log(level="WARN")
        return flt

    job, flt = _tool.launch(pco, "sfnt-pingpong", opts.client_argv(),
                            setup=_setup)
    with _tool.running(SfntPingpong(job, flt)) as c:
        yield c
