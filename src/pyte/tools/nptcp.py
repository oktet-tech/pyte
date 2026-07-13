# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools.nptcp — run NPtcp (NetPIPE) client/server from Python tests.

Pure Python over pyte.job; zero shim imports. The NPtcp binary is
resolved from the agent's PATH (job program "NPtcp"). Gate NPtcp tests
with <req id="NPTCP"/> and the prologue probe.

Pinned mappings (from te/lib/tapi_tool/tapi_nptcp.{h,c})
=========================================================

argv (tapi_nptcp.c:48-71; receiver omits -h, transmitter includes -h
<host>; ints are TAPI_JOB_OPT_UINT_OMITTABLE = separate tokens)::

    -b <tcp_buffer_size>   [-h <host>]   [-I]   -l <starting_msg_size>
    -n <nrepeats>   -O <offsets>   -o <output_filename>   -p <perturbation_size>
    [-r]   [-s]   -u <upper_bound>   [-2]

-I/-r/-s/-2 are presence-only bools (invalidate_cache, reset_sockets,
streaming_mode, bi_directional_mode). Each value flag is omitted when
the option is None/False.

Report + parsing (tapi_nptcp.c:120-154, 481-501): NetPIPE prints, on
stderr (not stdout), one row per message size of the form:

    <n>: <bytes> bytes  <times> times  -->  <throughput> Mbps in <rtt> usec

Each entry: number (int), bytes (int), times (int), throughput (float,
Mbps), rtt (float, usec). Raise NptcpError if no entry row is found.

Row regex: r"(\\d+):\\s+(\\d+)\\s+bytes\\s+(\\d+)\\s+times.*?([\\d.]+)\\s+Mbps.*?([\\d.]+)\\s+usec"

MI (tapi_nptcp_report_mi_log, tapi_nptcp.c:504-514), per entry:
    THROUGHPUT NULL SINGLE throughput MEBI
    LATENCY    NULL SINGLE rtt        MICRO

→ pyte: per entry emit throughput (single, mebi, value as-is — already
Mbps) and latency (single, micro, rtt as-is — already usec). pyte.mi has
no NULL-name/key API, so the message size is embedded in the measurement
name (documented deviation).

Readiness deviation: the C tapi waits for the receiver's stderr line
"Send and receive buffers are" before starting the transmitter; pyte
uses a settle delay via _clientserver.serve(ready_delay=...) instead
(the showcase gates out on the dev host, and loopback NPtcp startup is
fast). Documented deviation.
"""
from __future__ import annotations

import re
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pyte.errors import NptcpError
from pyte.tools import _tool
from pyte.tools._clientserver import serve
from pyte.tools._clientserver import Endpoint  # noqa: F401  (re-exported)

if TYPE_CHECKING:
    from pyte.rpc import RpcServer


@dataclass(frozen=True)
class Opts:
    """NPtcp command-line options.

    Parameters
    ----------
    host:
        Transmitter target host (``-h``); required for :meth:`client_argv`,
        ignored by :meth:`server_argv`.
    tcp_buffer_size:
        ``-b`` TCP buffer size in bytes.
    invalidate_cache:
        ``-I`` invalidate cache between measurements.
    starting_msg_size:
        ``-l`` starting message size in bytes.
    nrepeats:
        ``-n`` number of repeats per message size.
    offsets:
        ``-O`` cache alignment offsets string.
    output_filename:
        ``-o`` output filename for raw data.
    perturbation_size:
        ``-p`` perturbation size in bytes.
    reset_sockets:
        ``-r`` reset sockets between measurements.
    streaming_mode:
        ``-s`` streaming (one-way) mode.
    upper_bound:
        ``-u`` upper bound for message sizes in bytes.
    bi_directional_mode:
        ``-2`` bidirectional mode.
    """
    host: str | None = None
    tcp_buffer_size: int | None = None
    invalidate_cache: bool = False
    starting_msg_size: int | None = None
    nrepeats: int | None = None
    offsets: str | None = None
    output_filename: str | None = None
    perturbation_size: int | None = None
    reset_sockets: bool = False
    streaming_mode: bool = False
    upper_bound: int | None = None
    bi_directional_mode: bool = False

    def _build(self, include_host: bool) -> list[str]:
        """Build argv in the pinned tapi_nptcp.c bind order."""
        argv: list[str] = []
        if self.tcp_buffer_size is not None:
            argv += ["-b", str(self.tcp_buffer_size)]
        if include_host and self.host:
            argv += ["-h", self.host]
        if self.invalidate_cache:
            argv.append("-I")
        if self.starting_msg_size is not None:
            argv += ["-l", str(self.starting_msg_size)]
        if self.nrepeats is not None:
            argv += ["-n", str(self.nrepeats)]
        if self.offsets is not None:
            argv += ["-O", self.offsets]
        if self.output_filename is not None:
            argv += ["-o", self.output_filename]
        if self.perturbation_size is not None:
            argv += ["-p", str(self.perturbation_size)]
        if self.reset_sockets:
            argv.append("-r")
        if self.streaming_mode:
            argv.append("-s")
        if self.upper_bound is not None:
            argv += ["-u", str(self.upper_bound)]
        if self.bi_directional_mode:
            argv.append("-2")
        return argv

    def server_argv(self) -> list[str]:
        """Build the NPtcp receiver argument list (without argv[0])."""
        return self._build(include_host=False)

    def client_argv(self) -> list[str]:
        """Build the NPtcp transmitter argument list (without argv[0]).

        Raises :exc:`ValueError` if :attr:`host` is not set.
        """
        if not self.host:
            raise ValueError("Opts.host is required for the client (transmitter)")
        return self._build(include_host=True)


@dataclass(frozen=True)
class Entry:
    """One NetPIPE message-size row."""
    number: int
    bytes: int
    times: int
    throughput: float
    rtt: float


@dataclass(frozen=True)
class Report:
    """Parsed NPtcp results table."""
    entries: tuple[Entry, ...]


_RE_ENTRY = re.compile(
    r"(\d+):\s+(\d+)\s+bytes\s+(\d+)\s+times.*?([\d.]+)\s+Mbps.*?([\d.]+)\s+usec")


def _parse_report(text: str) -> Report:
    """Parse a NetPIPE stderr table into a :class:`Report`.

    Raises :exc:`pyte.errors.NptcpError` if no entry rows are found.
    """
    from pyte.errors import NptcpError

    entries = []
    for m in _RE_ENTRY.finditer(text):
        entries.append(Entry(
            number=int(m.group(1)),
            bytes=int(m.group(2)),
            times=int(m.group(3)),
            throughput=float(m.group(4)),
            rtt=float(m.group(5)),
        ))
    if not entries:
        raise NptcpError(
            f"cannot parse NPtcp table; no entry rows found in output: "
            f"{text[:200]!r}")
    return Report(entries=tuple(entries))


class Nptcp(_tool.ToolHandle):
    """Lifecycle manager for a running NPtcp *transmitter* job.

    Created via :func:`run`. The results table arrives on **stderr**
    (NetPIPE writes its output table there), so the readable stderr
    filter is what feeds ``_parse``.  wait() is parse-first
    (ping-style dual-path).
    """

    tool = "NPtcp transmitter"
    error_cls = NptcpError
    default_timeout = 300.0

    def _parse(self, raw: str) -> Report:
        return _parse_report(raw)

    def _check_status(self, status, raw) -> None:
        pass    # a parseable table is a result, whatever the exit status

    def mi_report(self, tool: str = "nptcp") -> None:
        """Emit MI artifacts mirroring tapi_nptcp_report_mi_log().

        Per entry: one throughput (single, mebi) + one latency (single,
        micro).  The message size is embedded in the measurement name
        (deviation from the C TAPI which uses NULL; pyte.mi has no
        NULL-name API).  One Logger per entry, so the base's
        single-logger mi_report() is overridden wholesale.
        """
        rep = self.wait()
        from pyte.mi import Aggr, Logger, Meas, Mult
        for e in rep.entries:
            name = f"[{e.bytes} bytes]"
            with Logger(tool) as logger:
                logger.add(Meas.THROUGHPUT, name, Aggr.SINGLE,
                           e.throughput, Mult.MEBI)
                logger.add(Meas.LATENCY, name, Aggr.SINGLE,
                           e.rtt, Mult.MICRO)


@contextmanager
def server(pco: "RpcServer", opts: "Opts | None" = None, *,
           host: str = "127.0.0.1", ready_delay: float = 2.0):
    """Context manager: run an NPtcp receiver for the block's duration.

    Yields a :class:`pyte.tools._clientserver.Endpoint`. ``host`` is the
    address the transmitter should target; The Endpoint's port is None: NPtcp picks its own
    port and does not report it (BREAKING: the fake ``port`` kwarg is
    gone). Uses a 2-second settle delay instead of the C TAPI's
    stderr-line readiness wait (documented deviation).

    Example::

        with nptcp.server(pco, nptcp.Opts(upper_bound=8192)) as ep:
            with nptcp.run(pco, nptcp.Opts(host=ep.host,
                                           upper_bound=8192)) as c:
                rep = c.wait()
    """
    opts = opts or Opts()
    with serve(pco, "NPtcp", opts.server_argv(),
               host=host, port=None, ready_delay=ready_delay) as ep:
        yield ep


@contextmanager
def run(pco: "RpcServer", opts: Opts):
    """Context manager: run an NPtcp *transmitter*; yield a :class:`Nptcp`.

    The results table is on **stderr** — a readable filter is attached
    there and handed to the handle as its output filter. Stdout is
    logged at RING level.
    """
    def _setup(job):
        flt = job.stderr.attach_filter(name="nptcp_stderr", readable=True)
        job.stdout.log(level="RING")
        return flt

    job, flt = _tool.launch(pco, "NPtcp", opts.client_argv(),
                            setup=_setup)
    with _tool.running(Nptcp(job, flt)) as c:
        yield c
