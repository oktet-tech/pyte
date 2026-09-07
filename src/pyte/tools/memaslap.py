# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools.memaslap — drive the memaslap memcached load generator.

Pinned mapping (te/lib/tapi_tool/tapi_memaslap.{h,c})
=====================================================
argv (memaslap_binds :37-76, in order): --servers=H:P,... --threads=U
--concurrency=U --conn_sock=U --execute_number=U --time=Us --win_size=Uk
--fixed_size=U --verify=F --division=U --stat_freq=Us --exp_verify=F
--overwrite=F --reconnect --udp --facebook --binary --tps=Uk --rep_write=U
--cfg_cmd=PATH --verbose
Cfg file (:227-240): "key\\n{kmin} {kmax} 1\\nvalue\\n{vmin} {vmax} 1\\n
cmd\\n0    {set:.2f}\\n1    {1-set:.2f}\\n"; limits (:25-28) key 16..250,
value 1..1048576, min<=max. The temp cfg file is created on the agent
(tapi_file_create_ta :245) and removed on destroy (:415-427).
Report filters: "TPS:\\s*([0-9]+)\\s" and "Net_rate:\\s*([0-9]+.[0-9]+)M"
(:284,291); net_rate is MiB/s in output, x8 to Mibit/s (:531).
MI (:557-571): tool "memaslap", RPS "TPS" single plain, THROUGHPUT
"Net_rate" single mebi, comment "command" = argv joined.
"""
from __future__ import annotations

import re
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from pyte._cleanup import cleanup_all
from pyte.errors import MemaslapError
from pyte.tools import _tool

if TYPE_CHECKING:
    from pyte.rpc import RpcServer

__all__ = ["CfgOpts", "Opts", "Report", "Memaslap", "run", "replace"]

_RE_TPS = re.compile(r"TPS:\s*([0-9]+)\s")
_RE_NET_RATE = re.compile(r"Net_rate:\s*([0-9]+.[0-9]+)M")  # unescaped '.' mirrors tapi_memaslap.c:291 verbatim (kept for parity)


@dataclass(frozen=True)
class CfgOpts:
    """memaslap configuration-file contents (tapi_memaslap_cfg_opt)."""
    key_len_min: int = 64
    key_len_max: int = 64
    value_len_min: int = 1024
    value_len_max: int = 1024
    set_share: float = 0.1

    def __post_init__(self):
        # cfg_opts_check_lens (tapi_memaslap.c:113-161)
        if not (16 <= self.key_len_min <= self.key_len_max <= 250):
            raise ValueError(f"key_len out of range: "
                             f"{self.key_len_min}..{self.key_len_max}")
        if not (1 <= self.value_len_min <= self.value_len_max <= 1048576):
            raise ValueError(f"value_len out of range: "
                             f"{self.value_len_min}..{self.value_len_max}")

    def render(self) -> str:
        return (f"key\n{self.key_len_min} {self.key_len_max} 1\n"
                f"value\n{self.value_len_min} {self.value_len_max} 1\n"
                f"cmd\n0    {self.set_share:.2f}\n"
                f"1    {1.0 - self.set_share:.2f}\n")


def _addr(v) -> str:
    """AddrLike -> the "host:port" form memaslap's -s wants."""
    from pyte.tools._tool import addr_host_port
    host, port = addr_host_port(v)
    return f"{host}:{port}"


def _pick_last(values: list[str], what: str) -> str:
    """Return the last element of *values*; raise MemaslapError if empty."""
    if not values:
        from pyte.errors import MemaslapError
        raise MemaslapError(f"memaslap output lacks {what}")
    return values[-1]


@dataclass(frozen=True)
class Opts:
    servers: tuple = ()               # of (host, port) | pyte.env.Addr
    threads: int | None = None
    concurrency: int | None = None
    conn_sock: int | None = None
    execute_number: int | None = None
    time: int | None = None           # seconds ("s" suffix)
    win_size_kb: int | None = None    # emitted with "k" suffix
    fixed_size: int | None = None
    verify: float | None = None
    division: int | None = None
    stat_freq: int | None = None      # seconds ("s" suffix)
    expire_verify: float | None = None
    overwrite: float | None = None
    reconnect: bool = False
    udp: bool = False
    facebook: bool = False
    bin_protocol: bool = False
    #: THOUSANDS of transactions/sec (emitted as --tps=<N>k);
    #: the unit is in the name (was expected_tps, silently x1000)
    expected_ktps: int | None = None
    rep_write: int | None = None
    cfg_cmd: str | None = None        # set by run() when cfg_opts given
    verbose: bool = False
    memaslap_path: str = "memaslap"

    def to_argv(self) -> list[str]:
        a: list[str] = []
        if self.servers:
            a.append("--servers=" +
                     ",".join(_addr(s) for s in self.servers))
        for flag, v, sfx in (("--threads=", self.threads, ""),
                             ("--concurrency=", self.concurrency, ""),
                             ("--conn_sock=", self.conn_sock, ""),
                             ("--execute_number=", self.execute_number, ""),
                             ("--time=", self.time, "s"),
                             ("--win_size=", self.win_size_kb, "k"),
                             ("--fixed_size=", self.fixed_size, ""),
                             ("--verify=", self.verify, ""),
                             ("--division=", self.division, ""),
                             ("--stat_freq=", self.stat_freq, "s"),
                             ("--exp_verify=", self.expire_verify, ""),
                             ("--overwrite=", self.overwrite, "")):
            if v is not None:
                a.append(f"{flag}{v}{sfx}")
        for flag, v in (("--reconnect", self.reconnect),
                        ("--udp", self.udp),
                        ("--facebook", self.facebook),
                        ("--binary", self.bin_protocol)):
            if v:
                a.append(flag)
        if self.expected_ktps is not None:
            a.append(f"--tps={self.expected_ktps}k")
        if self.rep_write is not None:
            a.append(f"--rep_write={self.rep_write}")
        if self.cfg_cmd is not None:
            a.append(f"--cfg_cmd={self.cfg_cmd}")
        if self.verbose:
            a.append("--verbose")
        return a


@dataclass(frozen=True)
class Report:
    tps: int
    net_rate: float     # Mibit/s (already x8)
    cmd: str


def _make_report(tps_s: str, net_s: str, cmd: str) -> Report:
    """Convert raw filter strings to a Report; raise MemaslapError if malformed."""
    from pyte.errors import MemaslapError
    try:
        tps = int(tps_s)
    except ValueError:
        raise MemaslapError(f"malformed TPS value: {tps_s!r}") from None
    try:
        net_rate = float(net_s) * 8
    except ValueError:
        raise MemaslapError(
            f"malformed Net_rate value: {net_s!r}") from None
    return Report(tps=tps, net_rate=net_rate, cmd=cmd)


class Memaslap(_tool.ToolHandle):
    """A running memaslap client job (from run()).

    wait() is status-first.  The output is the last message of each
    regex filter: read_all() would join matches without separators,
    corrupting the value when stat_freq causes multiple matches
    (e.g. "17891"+"18200" -> "1789118200").
    """

    tool = "memaslap"
    error_cls = MemaslapError
    default_timeout = 600.0
    wait_policy = "status-first"

    def __init__(self, job, tps_flt, net_flt, cmd: str, pco, cfg_fn):
        super().__init__(job)
        self._tps_flt = tps_flt
        self._net_flt = net_flt
        self._cmd = cmd
        self._pco = pco
        self._cfg_fn = cfg_fn

    def _read_output(self, timeout: float) -> tuple[list, list]:
        return ([m.data for m in self._tps_flt.messages(timeout=timeout)],
                [m.data for m in self._net_flt.messages(timeout=timeout)])

    def _parse(self, raw: tuple[list, list]) -> Report:
        tps_vals, net_vals = raw
        tps_s = _pick_last(tps_vals, "TPS")
        net_s = _pick_last(net_vals, "Net_rate")
        return _make_report(tps_s, net_s, self._cmd)

    def _after_close(self) -> None:
        if self._cfg_fn is not None:
            self._pco.unlink(self._cfg_fn)

    def _mi(self, logger, rep: Report) -> None:
        from pyte.mi import Aggr, Meas, Mult
        logger.add(Meas.RPS, "TPS", Aggr.SINGLE, rep.tps, Mult.PLAIN)
        logger.add(Meas.THROUGHPUT, "Net_rate", Aggr.SINGLE,
                   rep.net_rate, Mult.MEBI)
        logger.comment("command", rep.cmd)


@contextmanager
def run(pco: "RpcServer", opts: Opts, cfg_opts: CfgOpts | None = None):
    """Create+start a memaslap client; yields Memaslap; close() on exit.

    When cfg_opts is given, its rendered text is uploaded to the agent
    as a temp file and passed via --cfg_cmd (tapi_memaslap.c:211-258);
    the file is removed on close (or here, if the launch fails before
    the handle exists).
    """
    import os
    from pyte import log

    def _setup(job):
        tps_flt = job.filter(stdout=True, regex=r"TPS:\s*([0-9]+)\s",
                             group=1, name="tps")
        net_flt = job.filter(stdout=True,
                             regex=r"Net_rate:\s*([0-9]+.[0-9]+)M",
                             group=1, name="net_rate")
        # Names match tapi_memaslap.c:296-306 for log parity.
        # stdout is readable=True (default); stderr is readable=False
        # (tapi_memaslap.c:303 .readable = false).
        job.filter(stdout=True, readable=True, log_level="RING",
                   name="memaslap stdout")
        job.filter(stderr=True, readable=False, log_level="WARN",
                   name="memaslap stderr")
        return tps_flt, net_flt

    cfg_fn = None
    try:
        if cfg_opts is not None:
            cfg_fn = (f"/tmp/pyte_memaslap_{os.getpid()}"
                      f"_{uuid.uuid4().hex[:8]}.cfg")
            log.ring(f"memaslap config file {cfg_fn}:\n{cfg_opts.render()}")
            pco.file_put(cfg_fn, cfg_opts.render().encode())
            opts = replace(opts, cfg_cmd=cfg_fn)
        argv = opts.to_argv()
        cmd = " ".join([opts.memaslap_path, *argv])
        job, (tps_flt, net_flt) = _tool.launch(
            pco, opts.memaslap_path, argv, setup=_setup)
    except BaseException as exc:
        if cfg_fn is not None:
            cleanup_all(lambda: pco.unlink(cfg_fn), primary=exc)
        raise
    with _tool.running(Memaslap(job, tps_flt, net_flt, cmd,
                                pco, cfg_fn)) as m:
        yield m
