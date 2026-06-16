# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools.netperf — run netperf client/server from Python tests.

Pure Python over pyte.job's public API; zero shim imports. The netperf
and netserver binaries are resolved from the agent's PATH. Gate netperf
tests with <req id="NETPERF"/> and the prologue probe.

Pinned mapping (from te/lib/tapi_tool/tapi_netperf.{h,c})
==========================================================

Server argv (netserver_binds, tapi_netperf.c:507-512):

    netserver -L <bind_addr> -p <port> [-4|-6] -D

Client argv (netperf_binds, tapi_netperf.c:390-398):

    netperf -t <TEST> -H <host> [-4|-6] [-L <src>] [-p <port>] [-l <dur>]
            [-- <test-spec>]
    STREAM test-spec: [-m <send>] [-M <recv>] [-s <local_sock>] [-S <remote_sock>]
    RR     test-spec: [-r <req>[,<resp>]]
    (each test-spec flag omitted when its value is None; emit -- only if any
    test-spec flag is present)

Test names (-t): TCP_STREAM, UDP_STREAM, TCP_MAERTS, TCP_RR, UDP_RR.

Report + parsing (regexes on netperf's default text output,
tapi_netperf.c:425-482, 656-715):

- RR (TCP_RR/UDP_RR): r"per\\s*sec\\s*(?:\\S+\\s*){5}(\\S+)" → trps
- TCP STREAM (TCP_STREAM/TCP_MAERTS): r"bits/sec\\s*(?:\\S+\\s*){4}(\\S+)" →
  mbps_send; mbps_recv = mbps_send (C copies, tapi_netperf.c:707)
- UDP STREAM: send r"bits/sec\\s*(?:\\S+\\s*){5}(\\S+)", recv
  r"bits/sec\\s*(?:\\S+\\s*){9}(\\S+)"

MI (tapi_netperf_mi_report, tapi_netperf.c:798-833):

- STREAM: THROUGHPUT "Sending" SINGLE mbps_send MEGA and
  THROUGHPUT "Receiving" SINGLE mbps_recv MEGA
- RR: RPS "Transactions per second" SINGLE trps PLAIN

mbps_* are already in Mbit/s — pass as-is with mega multiplier.
trps → rps/single/plain.
"""
from __future__ import annotations

import re
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pyte.tools._clientserver import serve
from pyte.tools._clientserver import Endpoint  # noqa: F401  (re-exported)

if TYPE_CHECKING:
    from pyte.rpc import RpcServer

_VALID_TESTS = frozenset({"TCP_STREAM", "UDP_STREAM", "TCP_MAERTS",
                           "TCP_RR", "UDP_RR"})
_VALID_IPVERSIONS = frozenset({"4", "6"})


@dataclass(frozen=True)
class Opts:
    """netperf options (shared by the server and client argv builders).

    Parameters
    ----------
    host:
        Client target (``-H``); required for :meth:`client_argv`, ignored
        by :meth:`server_argv`.
    test_name:
        Netperf test type (``-t``): one of TCP_STREAM, UDP_STREAM,
        TCP_MAERTS, TCP_RR, UDP_RR.
    src_host:
        Client source bind address (``-L``).
    port:
        ``-p`` port (both sides). None uses netperf's default (12865).
    ipversion:
        ``"4"`` or ``"6"`` (``-4``/``-6``). None: netperf default.
    duration:
        ``-l`` seconds to run.
    buffer_send:
        STREAM test-spec ``-m`` local send buffer size in bytes.
    buffer_recv:
        STREAM test-spec ``-M`` remote recv buffer size in bytes.
    local_sock_buf:
        STREAM test-spec ``-s`` local socket buffer size in bytes.
    remote_sock_buf:
        STREAM test-spec ``-S`` remote socket buffer size in bytes.
    request_size:
        RR test-spec ``-r`` request message size in bytes.
    response_size:
        RR test-spec ``-r`` response message size in bytes (appended as
        ``,resp``).
    """
    host: str | None = None
    test_name: str = "TCP_STREAM"
    src_host: str | None = None
    port: int | None = None
    ipversion: str | None = None
    duration: int | None = None
    buffer_send: int | None = None
    buffer_recv: int | None = None
    local_sock_buf: int | None = None
    remote_sock_buf: int | None = None
    request_size: int | None = None
    response_size: int | None = None

    def __post_init__(self) -> None:
        if self.test_name not in _VALID_TESTS:
            raise ValueError(
                f"unknown test_name {self.test_name!r}; "
                f"valid: {sorted(_VALID_TESTS)}")
        if self.ipversion is not None and self.ipversion not in _VALID_IPVERSIONS:
            raise ValueError(
                f"unknown ipversion {self.ipversion!r}; "
                f"valid: {sorted(_VALID_IPVERSIONS)}")

    def server_argv(self, bind: str) -> list[str]:
        """Build the netserver argument list (without argv[0]).

        Mirrors netserver_binds order: -L, -p, [-4|-6], -D.
        """
        argv = ["-L", bind]
        if self.port is not None:
            argv += ["-p", str(self.port)]
        if self.ipversion is not None:
            argv.append(f"-{self.ipversion}")
        argv.append("-D")
        return argv

    def client_argv(self) -> list[str]:
        """Build the netperf client argument list (without argv[0]).

        Mirrors netperf_binds order. Appends ``-- <test-spec>`` only if
        any test-spec flag is present.
        """
        if not self.host:
            raise ValueError("Opts.host is required for the client")
        argv = ["-t", self.test_name, "-H", self.host]
        if self.ipversion is not None:
            argv.append(f"-{self.ipversion}")
        if self.src_host:
            argv += ["-L", self.src_host]
        if self.port is not None:
            argv += ["-p", str(self.port)]
        if self.duration is not None:
            argv += ["-l", str(self.duration)]

        # Build test-spec list.
        test_spec: list[str] = []
        if self.test_name in {"TCP_RR", "UDP_RR"}:
            if self.request_size is not None or self.response_size is not None:
                if self.request_size is not None and self.response_size is not None:
                    rr_val = f"{self.request_size},{self.response_size}"
                elif self.request_size is not None:
                    rr_val = f"{self.request_size}"
                else:
                    rr_val = f",{self.response_size}"
                test_spec += ["-r", rr_val]
        else:
            # STREAM tests
            if self.buffer_send is not None:
                test_spec += ["-m", str(self.buffer_send)]
            if self.buffer_recv is not None:
                test_spec += ["-M", str(self.buffer_recv)]
            if self.local_sock_buf is not None:
                test_spec += ["-s", str(self.local_sock_buf)]
            if self.remote_sock_buf is not None:
                test_spec += ["-S", str(self.remote_sock_buf)]

        if test_spec:
            argv += ["--"] + test_spec
        return argv


@dataclass(frozen=True)
class Report:
    """Parsed netperf report."""
    test_name: str
    test_type: str          # "stream" or "rr"
    mbps_send: float | None
    mbps_recv: float | None
    trps: float | None


# Compiled regexes (pinned to tapi_netperf.c:425-482, 656-715).
_RE_RR = re.compile(r"per\s*sec\s*(?:\S+\s*){5}(\S+)")
_RE_TCP_STREAM = re.compile(r"bits/sec\s*(?:\S+\s*){4}(\S+)")
_RE_UDP_SEND = re.compile(r"bits/sec\s*(?:\S+\s*){5}(\S+)")
_RE_UDP_RECV = re.compile(r"bits/sec\s*(?:\S+\s*){9}(\S+)")


def _parse_report(text: str, test_name: str) -> Report:
    """Parse netperf's text output into a :class:`Report`.

    Branches by *test_name*:

    - ``*_RR`` → :data:`_RE_RR` → ``trps``
    - ``UDP_STREAM`` → :data:`_RE_UDP_SEND` + :data:`_RE_UDP_RECV`
    - ``TCP_STREAM`` / ``TCP_MAERTS`` → :data:`_RE_TCP_STREAM`
      (``mbps_recv = mbps_send``)

    Raises :exc:`pyte.errors.NetperfError` when the expected metric is not
    found in *text*.
    """
    from pyte.errors import NetperfError

    if test_name.endswith("_RR"):
        m = _RE_RR.search(text)
        if not m:
            raise NetperfError(
                f"cannot parse netperf RR output; "
                f"test={test_name!r}; text={text[:200]!r}")
        return Report(test_name=test_name, test_type="rr",
                      mbps_send=None, mbps_recv=None,
                      trps=float(m.group(1)))

    if test_name == "UDP_STREAM":
        m_send = _RE_UDP_SEND.search(text)
        m_recv = _RE_UDP_RECV.search(text)
        if not m_send or not m_recv:
            raise NetperfError(
                f"cannot parse netperf UDP_STREAM output; "
                f"text={text[:200]!r}")
        return Report(test_name=test_name, test_type="stream",
                      mbps_send=float(m_send.group(1)),
                      mbps_recv=float(m_recv.group(1)),
                      trps=None)

    # TCP_STREAM / TCP_MAERTS
    m = _RE_TCP_STREAM.search(text)
    if not m:
        raise NetperfError(
            f"cannot parse netperf {test_name} output; "
            f"text={text[:200]!r}")
    v = float(m.group(1))
    return Report(test_name=test_name, test_type="stream",
                  mbps_send=v, mbps_recv=v, trps=None)


class Netperf:
    """Lifecycle manager for a running netperf *client* job.

    Created via :func:`run`. The text report arrives on stdout.
    """

    def __init__(self, job, stdout_filter, test_name: str):
        self._job = job
        self._stdout_filter = stdout_filter
        self._test_name = test_name
        self._report: Report | None = None
        self._closed = False

    def wait(self, timeout: float = 60.0) -> Report:
        """Wait for the client to finish, parse output, return a Report.

        Caches the report. Raises :exc:`pyte.errors.NetperfError` on a
        non-zero exit or unparseable output.
        """
        if self._report is not None:
            return self._report

        from pyte.errors import NetperfError

        status = self._job.wait(timeout=timeout)
        raw = self._stdout_filter.read_all(timeout=timeout)
        report = _parse_report(raw, self._test_name)
        if not status.ok:
            raise NetperfError(
                f"netperf client exited with {status}")
        self._report = report
        return self._report

    def mi_report(self, tool: str = "netperf") -> None:
        """Emit MI artifacts mirroring tapi_netperf_mi_report().

        STREAM: throughput "Sending"/"Receiving" single mbps_* mega.
        RR:     rps "Transactions per second" single trps plain.

        Requires :meth:`wait` first.
        """
        if self._report is None:
            raise RuntimeError("call wait() before mi_report()")
        rep = self._report
        from pyte.mi import Logger
        with Logger(tool) as logger:
            if rep.test_type == "stream":
                logger.add("throughput", "Sending", "single",
                           rep.mbps_send, "mega")
                logger.add("throughput", "Receiving", "single",
                           rep.mbps_recv, "mega")
            else:
                logger.add("rps", "Transactions per second", "single",
                           rep.trps, "plain")

    def close(self) -> None:
        """Stop netperf (errors tolerated) and destroy the job (idempotent)."""
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
           bind: str = "127.0.0.1", ready_delay: float = 1.0):
    """Context manager: run a netserver for the block's duration.

    Yields an :class:`pyte.tools._clientserver.Endpoint`. ``bind`` is the
    address the server listens on and what the client should target;
    the port comes from ``opts.port`` (default 12865 when unset).

    Example::

        with netperf.server(pco, netperf.Opts(port=12865)) as ep:
            with netperf.run(pco, netperf.Opts(host=ep.host, port=ep.port,
                                               duration=2)) as c:
                rep = c.wait()
    """
    opts = opts or Opts()
    port = opts.port if opts.port is not None else 12865
    with serve(pco, "netserver", opts.server_argv(bind=bind),
               host=bind, port=port, ready_delay=ready_delay) as ep:
        yield ep


@contextmanager
def run(pco: "RpcServer", opts: Opts):
    """Context manager: run a netperf *client*; yield a :class:`Netperf`."""
    job = pco.job("netperf", opts.client_argv())
    try:
        stdout_filter = job.stdout.attach_filter(
            name="netperf_stdout", readable=True)
        job.stderr.log(level="WARN")
        job.start()
    except Exception:
        job.destroy()
        raise
    client = Netperf(job, stdout_filter, opts.test_name)
    try:
        yield client
    finally:
        client.close()
