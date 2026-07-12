# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools.memtier — drive memtier_benchmark.

Pinned mapping (te/lib/tapi_tool/tapi_memtier.{h,c})
====================================================
argv (memtier_binds :42-73, in order): --server=HOST --port=PORT
--protocol=redis|resp2|resp3|memcache_text|memcache_binary --run-count=U
--requests=U --clients=U --threads=U --pipeline=U --test-time=U
--data-size=U --random-data --ratio=S --key-prefix=S --key-pattern=S
--key-minimum=U --key-maximum=U --hide-histogram --debug
Stats rows filter: "^[a-zA-Z]+\\s+([0-9.-]+\\s+){2,}[0-9.-]+\\s*$" (:163),
no extract group -- each matched LINE arrives as one filter message.
Row parse (:283-323): first numeric after the label = Ops/sec (tps);
last numeric = KB/sec -> net_rate = kb/1024*8 Mbit/s. Rows: Sets, Gets,
Totals (:376-381); with --run-count>1 the LAST table wins (:353-357) --
we keep updating per matching row, so later tables overwrite earlier.
MI (:406-457): tool "memtier_benchmark"; per parsed op: RPS "<Op>.TPS"
single plain + THROUGHPUT "<Op>.Net_rate" single mebi; comment "command"
= argv joined, emitted natively via logger.comment().
"""
from __future__ import annotations

import enum
from contextlib import contextmanager
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from pyte.errors import MemtierError
from pyte.tools import _tool

if TYPE_CHECKING:
    from pyte.rpc import RpcServer

__all__ = ["Proto", "Opts", "OpStats", "Report", "Memtier", "run",
           "parse_row", "parse_report", "replace"]


class Proto(enum.Enum):
    REDIS = "redis"
    RESP2 = "resp2"
    RESP3 = "resp3"
    MEMCACHE_TEXT = "memcache_text"
    MEMCACHE_BINARY = "memcache_binary"


@dataclass(frozen=True)
class Opts:
    server: object = None            # (host, port) | pyte.env.Addr
    protocol: Proto | None = None
    run_count: int | None = None
    requests: int | None = None
    clients: int | None = None
    threads: int | None = None
    pipeline: int | None = None
    test_time: int | None = None
    data_size: int | None = None
    random_data: bool = False
    ratio: str | None = None
    key_prefix: str | None = None
    key_pattern: str | None = None
    key_minimum: int | None = None
    key_maximum: int | None = None
    hide_histogram: bool = False
    debug: bool = False
    memtier_path: str = "memtier_benchmark"

    def to_argv(self) -> list[str]:
        a: list = []
        if self.server is not None:
            s = self.server.pair if hasattr(self.server, "pair") \
                else self.server
            a += [f"--server={s[0]}", f"--port={s[1]}"]
        if self.protocol is not None:
            a.append(f"--protocol={self.protocol.value}")
        for flag, v in (("--run-count=", self.run_count),
                        ("--requests=", self.requests),
                        ("--clients=", self.clients),
                        ("--threads=", self.threads),
                        ("--pipeline=", self.pipeline),
                        ("--test-time=", self.test_time),
                        ("--data-size=", self.data_size)):
            if v is not None:
                a.append(f"{flag}{v}")
        if self.random_data:
            a.append("--random-data")
        for flag, v in (("--ratio=", self.ratio),
                        ("--key-prefix=", self.key_prefix),
                        ("--key-pattern=", self.key_pattern),
                        ("--key-minimum=", self.key_minimum),
                        ("--key-maximum=", self.key_maximum)):
            if v is not None:
                a.append(f"{flag}{v}")
        if self.hide_histogram:
            a.append("--hide-histogram")
        if self.debug:
            a.append("--debug")
        return a


@dataclass
class OpStats:
    tps: float = 0.0
    net_rate: float = 0.0   # Mbit/s
    parsed: bool = False


@dataclass
class Report:
    sets: OpStats
    gets: OpStats
    totals: OpStats
    cmd: str


def parse_row(row: str) -> OpStats:
    """First numeric after label = Ops/sec; last = KB/s -> Mbit/s (:283-323).

    The stats filter regex matches whole lines (no extract group, :163-165),
    so each message is a full row like "Sets  1785.61  ---  ---  0.115  1954.32".
    split() handles any amount of whitespace including trailing.
    fields[0] is the label (Sets/Gets/Totals); fields[1] is tps; fields[-1]
    is KB/s.
    """
    from pyte.errors import MemtierError
    fields = row.split()
    try:
        return OpStats(tps=float(fields[1]),
                       net_rate=float(fields[-1]) / 1024 * 8,
                       parsed=True)
    except (ValueError, IndexError):
        raise MemtierError(f"malformed stats row: {row!r}") from None


def parse_report(rows: list, cmd: str) -> Report:
    """Parse a list of stats-filter messages into a Report.

    With --run-count>1, memtier emits multiple tables; later rows for the
    same label overwrite earlier ones (last table wins, :353-357).
    Raises MemtierError when no statistics rows were found.
    """
    from pyte.errors import MemtierError
    rep = Report(sets=OpStats(), gets=OpStats(), totals=OpStats(), cmd=cmd)
    for row in rows:
        if row.startswith("Sets"):
            rep.sets = parse_row(row)
        elif row.startswith("Gets"):
            rep.gets = parse_row(row)
        elif row.startswith("Totals"):
            rep.totals = parse_row(row)
    if not (rep.sets.parsed or rep.gets.parsed or rep.totals.parsed):
        raise MemtierError("no statistics rows in memtier output")
    return rep


class Memtier(_tool.ToolHandle):
    """A running memtier_benchmark client job (from run()).

    wait() is status-first (a failed run prints no stats tables); the
    output is the stats regex filter's per-line messages -- read_all()
    would join rows without separators and corrupt the values.
    """

    tool = "memtier"
    error_cls = MemtierError
    default_timeout = 600.0
    wait_policy = "status-first"

    def __init__(self, job, stats_flt, cmd: str):
        super().__init__(job)
        self._stats_flt = stats_flt
        self._cmd = cmd

    def _read_output(self, timeout: float) -> list:
        return [m.data for m in self._stats_flt.messages(timeout=10.0)]

    def _parse(self, rows: list) -> "Report":
        return parse_report([r for r in rows if r], self._cmd)

    def _mi(self, logger, rep: "Report") -> None:
        from pyte.mi import Aggr, Meas, Mult
        for name, st in (("Sets", rep.sets),
                         ("Gets", rep.gets),
                         ("Totals", rep.totals)):
            if st.parsed:
                logger.add(Meas.RPS, f"{name}.TPS", Aggr.SINGLE,
                           st.tps, Mult.PLAIN)
                logger.add(Meas.THROUGHPUT, f"{name}.Net_rate",
                           Aggr.SINGLE, st.net_rate, Mult.MEBI)
        logger.comment("command", rep.cmd)

    def mi_report(self, tool: str = "memtier_benchmark") -> None:
        super().mi_report(tool)


@contextmanager
def run(pco: "RpcServer", opts: Opts):
    """Create+start a memtier_benchmark client; yields Memtier;
    close() on exit."""
    def _setup(job):
        stats_flt = job.filter(
            stdout=True,
            regex=r"^[a-zA-Z]+\s+([0-9.-]+\s+){2,}[0-9.-]+\s*$",
            group=0, name="stats")
        # Names match tapi_memtier.c:166-177 for log parity; C has
        # readable=true on BOTH stdout and stderr log filters.
        job.filter(stdout=True, readable=True, log_level="RING",
                   name="memtier_benchmark stdout")
        job.filter(stderr=True, readable=True, log_level="WARN",
                   name="memtier_benchmark stderr")
        return stats_flt

    argv = opts.to_argv()
    cmd = " ".join([opts.memtier_path, *argv])
    job, stats_flt = _tool.launch(pco, opts.memtier_path, argv,
                                  setup=_setup)
    with _tool.running(Memtier(job, stats_flt, cmd)) as m:
        yield m
