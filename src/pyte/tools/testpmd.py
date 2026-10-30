# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools.testpmd: run dpdk-testpmd and read its live statistics.

Opts builds the EAL/application argv and the ``--cmdline-file`` text.
testpmd is started with ``--disable-device-start`` and a command file
that configures the ports, starts them and begins forwarding. run()
uploads that file to the agent's tmp_dir, launches dpdk-testpmd from
the agent directory and yields a Testpmd handle whose stats() returns
the latest ``--stats-period`` counters per port without blocking.

argv layout (each optional part omitted when unset):
    --allow=<bdf>... --vdev=<spec>... [--no-pci] -n <mem_channels>
    --file-prefix <prefix> [--no-huge] [-m <mem_mb>] <extra_eal>
    --lcores=<c1>,<c2>,... | --lcores=<lcore>@<cpu>,...
    -- --disable-device-start --nb-cores N --cmdline-file F
    --forward-mode M --rxq N --txq N --rxd N --txd N --burst N
    --stats-period N [--no-lsc-interrupt] [--mbuf-size N]
    [--total-num-mbufs N] [--eth-peer <port>,<mac>]... <passthrough>
"""
from __future__ import annotations

import re
import signal
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from pyte import cfg
from pyte.errors import TestpmdError
from pyte.errors import TimeoutError as TeTimeoutError
from pyte.tools._tool import ToolHandle, launch, opt, opt_eq, running, switch

if TYPE_CHECKING:
    from pyte.rpc import RpcServer

#: --mbuf-size run() passes when Opts.mbuf_size is None
DEFAULT_MBUF_SIZE = 2176
#: wait_ports_started() poll interval, seconds
_POLL_INTERVAL = 0.5


@dataclass(frozen=True)
class Opts:
    """dpdk-testpmd options (EAL part, application part, command file)."""

    allow: tuple[str, ...] = ()
    lcores: tuple[int, ...] = ()
    #: DPDK virtual devices (--vdev), e.g. "net_af_xdp0,iface=veth1"
    vdev: tuple[str, ...] = ()
    no_pci: bool = False
    #: --no-huge: run from anonymous memory (rigs without hugepages)
    no_huge: bool = False
    #: -m: memory to preallocate, MB (needed with no_huge)
    mem_mb: int | None = None
    #: (lcore, cpu) pairs for --lcores=<lcore>@<cpu>; replaces lcores
    #: when set, so lcore ids stay 0..N even on CPUs shared with
    #: other instances
    lcore_map: tuple[tuple[int, int], ...] = ()
    mem_channels: int = 4
    file_prefix: str = "testpmd"
    extra_eal: tuple[str, ...] = ()
    nb_cores: int = 1
    forward_mode: str = "io"
    rxq: int = 1
    txq: int = 1
    rxd: int = 512
    txd: int = 512
    burst: int = 32
    stats_period: int = 1
    no_lsc_interrupt: bool = True
    mbuf_size: int | None = None
    total_num_mbufs: int | None = None
    #: (port, mac) pairs for --eth-peer
    eth_peer: tuple[tuple[int, str], ...] = ()
    txpkts: str | None = None
    mtu: int | None = None
    flow_ctrl: bool | None = None
    tx_first: int | None = None
    #: (option name with underscores, value); True = bare flag,
    #: False = skipped
    passthrough: tuple[tuple[str, str | bool], ...] = ()
    cmdline_file: str = ""

    def eal_argv(self) -> list[str]:
        """EAL arguments (before the ``--`` separator)."""
        argv = [f"--allow={bdf}" for bdf in self.allow]
        argv += [f"--vdev={spec}" for spec in self.vdev]
        argv += switch("--no-pci", self.no_pci)
        argv += opt("-n", self.mem_channels)
        argv += opt("--file-prefix", self.file_prefix)
        argv += switch("--no-huge", self.no_huge)
        argv += opt("-m", self.mem_mb)
        argv += self.extra_eal
        if self.lcore_map:
            lcores = ",".join(f"{lc}@{c}" for lc, c in self.lcore_map)
        else:
            lcores = ",".join(map(str, self.lcores))
        argv += opt_eq("--lcores=", lcores or None)
        return argv

    def app_argv(self) -> list[str]:
        """Application arguments, starting with the ``--`` separator."""
        argv = ["--", "--disable-device-start"]
        argv += opt("--nb-cores", self.nb_cores)
        argv += opt("--cmdline-file", self.cmdline_file)
        argv += opt("--forward-mode", self.forward_mode)
        argv += opt("--rxq", self.rxq)
        argv += opt("--txq", self.txq)
        argv += opt("--rxd", self.rxd)
        argv += opt("--txd", self.txd)
        argv += opt("--burst", self.burst)
        argv += opt("--stats-period", self.stats_period)
        argv += switch("--no-lsc-interrupt", self.no_lsc_interrupt)
        argv += opt("--mbuf-size", self.mbuf_size)
        argv += opt("--total-num-mbufs", self.total_num_mbufs)
        for port, mac in self.eth_peer:
            argv += ["--eth-peer", f"{port},{mac}"]
        for name, value in self.passthrough:
            flag = "--" + name.replace("_", "-")
            if value is True:
                argv.append(flag)
            elif value is not False:
                argv += [flag, str(value)]
        return argv

    def argv(self) -> list[str]:
        return self.eal_argv() + self.app_argv()

    def cmdline_text(self, nports: int) -> str:
        """Contents of the ``--cmdline-file`` for *nports* ports."""
        lines = []
        for port in range(nports):
            if self.flow_ctrl is not None:
                state = "on" if self.flow_ctrl else "off"
                lines.append(
                    f"set flow_ctrl rx {state} tx {state} {port}")
            if self.mtu is not None:
                lines.append(f"port config mtu {port} {self.mtu}")
        lines += ["port start all", "show port info all"]
        if self.txpkts is not None:
            lines.append(f"set txpkts {self.txpkts}")
        if self.tx_first is not None:
            lines.append(f"start tx_first {self.tx_first}")
        else:
            lines.append("start")
        return "".join(line + "\n" for line in lines)


def total_num_mbufs_default(nports: int, opts: Opts) -> int:
    """testpmd's default mbuf pool size estimate, floored at 2048."""
    return max(2048, nports * (opts.txq * (opts.txd + opts.burst)
                               + opts.rxq * opts.rxd)
               + 250 * opts.nb_cores)


#: Per-port statistics header (same regex as the C TAPI tapi_dpdk.c).
STATS_HEADER_RE = r"(?m)^[ #]+ NIC statistics for port ([0-9]+) [ #]+$"
_STATS_CLOSE_RE = re.compile(r"(?m)^[ ]*#+[ ]*$")
_STATS_FIELDS = (
    ("rx_packets", r"RX-packets:\s*([0-9]+)"),
    ("rx_missed", r"RX-missed:\s*([0-9]+)"),
    ("rx_bytes", r"RX-bytes:\s*([0-9]+)"),
    ("rx_errors", r"RX-errors:\s*([0-9]+)"),
    ("tx_packets", r"TX-packets:\s*([0-9]+)"),
    ("tx_errors", r"TX-errors:\s*([0-9]+)"),
    ("tx_bytes", r"TX-bytes:\s*([0-9]+)"),
    ("rx_pps", r"Rx-pps:\s*([0-9]+)"),
    ("tx_pps", r"Tx-pps:\s*([0-9]+)"),
)


@dataclass(frozen=True)
class PortStats:
    """One port's counters from a periodic testpmd statistics dump."""

    port: int
    rx_packets: int
    rx_bytes: int
    rx_missed: int
    rx_errors: int
    tx_packets: int
    tx_bytes: int
    tx_errors: int
    rx_pps: int
    tx_pps: int


class StatsParser:
    """Incremental parser of ``--stats-period`` output.

    Feed arbitrary chunks of testpmd stdout; complete blocks (header
    through the closing ``####`` line) are returned in order, a trailing
    partial block stays buffered until the rest arrives.
    """

    def __init__(self) -> None:
        self._buf = ""

    def feed(self, text: str) -> list[PortStats]:
        self._buf += text
        out = []
        while True:
            head = re.search(STATS_HEADER_RE, self._buf)
            if head is None:
                # keep only the last (possibly partial header) line
                self._buf = self._buf[self._buf.rfind("\n") + 1:]
                return out
            close = _STATS_CLOSE_RE.search(self._buf, head.end())
            if close is None:
                self._buf = self._buf[head.start():]
                return out
            body = self._buf[head.end():close.start()]
            self._buf = self._buf[close.end():]
            out.append(self._parse(int(head.group(1)), body))

    @staticmethod
    def _parse(port: int, body: str) -> PortStats:
        vals = {}
        for name, pattern in _STATS_FIELDS:
            m = re.search(pattern, body)
            vals[name] = int(m.group(1)) if m else 0
        return PortStats(port=port, **vals)


def program_path(ta: str) -> str:
    """dpdk-testpmd installed in the agent directory of *ta*."""
    return cfg.get(f"/agent:{ta}/dir:") + "/dpdk-testpmd"


def cmdline_path(ta: str, file_prefix: str) -> str:
    """Where run() puts the ``--cmdline-file`` on *ta*."""
    return (cfg.get(f"/agent:{ta}/tmp_dir:")
            + f"/{file_prefix}_testpmd_commands")


class Testpmd(ToolHandle):
    """A running dpdk-testpmd job (from run()).

    testpmd forwards until stopped, so there is no report to wait()
    for: stats() reads whatever ``--stats-period`` output has arrived
    so far and returns at once.
    """

    tool = "testpmd"
    error_cls = TestpmdError
    default_timeout = 60.0

    def __init__(self, job, stdout_filter, opts: Opts, nports: int):
        super().__init__(job, stdout_filter)
        self._opts = opts
        self._nports = nports
        self._parser = StatsParser()
        self._stats: dict[int, PortStats] = {}
        #: the job's exit status, once alive() has seen it exit
        self._exit_status = None

    def alive(self) -> bool:
        """True while dpdk-testpmd is still running; never blocks.

        A forwarder that dies mid-run otherwise only shows up as
        counters that stop moving.  False once the job has exited or
        the handle was closed.
        """
        if self._exit_status is not None or self._job_destroyed:
            return False
        try:
            self._exit_status = self._job.wait(timeout=0)
        except TeTimeoutError:
            return True
        return False

    def stats(self) -> dict[int, PortStats]:
        """Latest PortStats per port seen so far; never blocks.

        Drains the queued stdout messages and keeps the newest block
        of each port, so ports stay in the result between calls even
        when nothing new arrived.  Empty until the first block.  After
        close() the job and its filter are gone: the last counters
        seen are returned as they are.
        """
        if not self._job_destroyed:
            for msg in self._stdout_filter.drain():
                for st in self._parser.feed(msg.data):
                    self._stats[st.port] = st
        return dict(self._stats)

    def wait_ports_started(self, timeout: float) -> None:
        """Wait until each of the run's ports has printed statistics.

        A port's first stats block means testpmd has started it and
        is forwarding.  Raises TestpmdError after *timeout* seconds,
        or at once when testpmd has exited.
        """
        want = set(range(self._nports))
        deadline = time.monotonic() + timeout
        while True:
            missing = want - set(self.stats())
            if not missing:
                return
            if not self.alive():
                raise TestpmdError(
                    f"testpmd exited ({self._exit_status}) before ports "
                    f"{sorted(missing)} printed statistics")
            left = deadline - time.monotonic()
            if left <= 0:
                raise TestpmdError(
                    f"testpmd ports {sorted(missing)} printed no "
                    f"statistics within {timeout} s")
            time.sleep(min(_POLL_INTERVAL, left))

    def _stop_for_close(self) -> None:
        """SIGINT first (testpmd stops forwarding and closes the
        ports), SIGKILL after Job.stop's default timeout."""
        self._job.stop(signal=signal.SIGINT)


@contextmanager
def run(pco: RpcServer, opts: Opts, *,
        nports: int | None = None) -> Iterator[Testpmd]:
    """Start dpdk-testpmd on *pco*; yields Testpmd; close() on exit.

    *nports* (default: one per opts.allow and opts.vdev entry) sizes
    the command file and the default mbuf pool, and is the number of
    ports wait_ports_started() waits for.  The command file is written
    to cmdline_path(); unset mbuf_size / total_num_mbufs get
    DEFAULT_MBUF_SIZE / total_num_mbufs_default().
    """
    nports = nports or len(opts.allow) + len(opts.vdev)
    path = cmdline_path(pco.ta, opts.file_prefix)
    pco.file_put(path, opts.cmdline_text(nports).encode())
    opts = replace(
        opts, cmdline_file=path,
        total_num_mbufs=(total_num_mbufs_default(nports, opts)
                         if opts.total_num_mbufs is None
                         else opts.total_num_mbufs),
        mbuf_size=(DEFAULT_MBUF_SIZE if opts.mbuf_size is None
                   else opts.mbuf_size))

    def _setup(job):
        flt = job.stdout.attach_filter(name="testpmd-out", readable=True)
        job.stderr.log(level="WARN")
        return flt

    job, flt = launch(pco, program_path(pco.ta), opts.argv(), setup=_setup)
    with running(Testpmd(job, flt, opts, nports)) as h:
        yield h
