# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools.testpmd — build dpdk-testpmd command lines.

First slice: the Opts dataclass plus the EAL/application argv builder and
the ``--cmdline-file`` text builder. testpmd is started with
``--disable-device-start`` and a command file that configures the ports,
starts them and begins forwarding.

argv layout (each optional part omitted when unset):
    --allow=<bdf>... -n <mem_channels> --file-prefix <prefix> <extra_eal>
    --lcores=<c1>,<c2>,...
    -- --disable-device-start --nb-cores N --cmdline-file F
    --forward-mode M --rxq N --txq N --rxd N --txd N --burst N
    --stats-period N [--no-lsc-interrupt] [--mbuf-size N]
    [--total-num-mbufs N] [--eth-peer <port>,<mac>]... <passthrough>
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from pyte.tools._tool import opt, opt_eq, switch


@dataclass(frozen=True)
class Opts:
    """dpdk-testpmd options (EAL part, application part, command file)."""

    allow: tuple[str, ...]
    lcores: tuple[int, ...]
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
        argv += opt("-n", self.mem_channels)
        argv += opt("--file-prefix", self.file_prefix)
        argv += self.extra_eal
        argv += opt_eq("--lcores=", ",".join(map(str, self.lcores)))
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
