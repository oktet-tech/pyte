# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools.memcached — run a memcached server from Python tests.

Pure Python over pyte.job; zero shim imports.

Pinned mapping (from te/lib/tapi_tool/tapi_memcached.{h,c})
===========================================================
argv (memcached_binds, tapi_memcached.c:53-166), in binds order:
  --unix-socket=S  --enable-shutdown  --unix-mask=OCT  --listen=ADDR
  --user=S  --memory-limit=U  --conn-limit=U  --max-reqs-per-event=U
  --lock-memory  --port=PORT  --udp-port=PORT  --disable-evictions
  --enable-coredumps  --slab-growth-factor=F  --slab-min-size=U
  --disable-cas  -v|-vv|-vvv  --threads=U  --napi-ids=U  -DCHAR
  --enable-largepages  --listen-backlog=U  --protocol=auto|ascii|binary
  --max-item-size=Uk  --enable-sasl  --disable-flush-all
  --disable-dumping  --disable-watch  -omaxconns_fast  -ono_maxconns_fast
  -ohashpower=U  -otail_repair_time=U  -ono_lru_crawler
  -olru_crawler_sleep=U  -olru_crawler_tocrawl=U  -ono_lru_maintainer
  -ohot_lru_pct=U  -owarm_lru_pct=U  -ohot_max_factor=F
  -owarm_max_factor=F  -otemporary_ttl=U  -oidle_timeout=U
  -owatcher_logbuf_size=U  -oworker_logbuf_size=U  -otrack_sizes
  -ono_hashexpand  -oext_page_size=U  -oext_path=PATH:SIZEG
  -oext_wbuf_size=U  -oext_threads=U  -oext_item_size=U  -oext_item_age=U
  -oext_low_ttl=U  -oext_drop_unread  -oext_recache_rate=U
  -oext_compact_under=U  -oext_drop_under=U  -oext_max_frag=F
  -oslab_automove_freeratio=F
Defaults: tcp_port/udp_port default to 0.0.0.0:0 => --port=0 --udp-port=0
always emitted (tapi_memcached.c:30-34,179-180). DIVERGENCE from C: the C
default opt emits --protocol=auto always (PROTO_AUTO enum, not UNDEF); we
omit --protocol unless set. memcached treats absence as auto. Suites
wanting byte-identical command lines pass protocol=Proto.AUTO.
Filters (tapi_memcached.c:296-309): stdout logged at RING, stderr at WARN,
both non-readable. Stop: SIGTERM, 10s (:21,380).
Stats reader pinned to app-perf-ts mem-db/memcached.c:432-517:
  mc-stats <port>; regexes "STAT <field> ([0-9]+)" for cmd_set cmd_get
  get_hits get_misses curr_items bytes_read bytes_written.
"""
from __future__ import annotations

import enum
import re
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyte.rpc import RpcServer


class Proto(enum.Enum):
    AUTO = "auto"
    ASCII = "ascii"
    BINARY = "binary"


class Verbose(enum.Enum):
    V = "-v"
    MORE = "-vv"
    EXTRA = "-vvv"


def _addr_port(v) -> str:
    """(host, port) tuple, pyte.env.Addr, or int port -> port string."""
    from pyte.tools._tool import addr_port
    return str(addr_port(v))


@dataclass(frozen=True)
class Opts:
    """memcached options; None omits the flag (mirrors *_UNDEF)."""
    unix_socket: str | None = None
    enable_ascii_shutdown: bool = False
    unix_mask: int | None = None            # emitted octal
    listen_ipaddr: str | None = None
    username: str | None = None
    memory_limit: int | None = None
    conn_limit: int | None = None
    max_reqs_per_event: int | None = None
    lock_memory: bool = False
    tcp_port: object = 0                    # int port | (host, port) | Addr
    udp_port: object = 0
    disable_evictions: bool = False
    enable_coredumps: bool = False
    slab_growth_factor: float | None = None
    slab_min_size: int | None = None
    disable_cas: bool = False
    verbose: Verbose | None = None
    threads: int | None = None
    napi_ids: int | None = None
    delimiter: str | None = None
    enable_largepages: bool = False
    listen_backlog: int | None = None
    protocol: Proto | None = None
    max_item_size: int | None = None        # kilobytes ("k" suffix)
    enable_sasl: bool = False
    disable_flush_all: bool = False
    disable_dumping: bool = False
    disable_watch: bool = False
    maxconns_fast: bool = False
    no_maxconns_fast: bool = False
    hashpower: int | None = None
    tail_repair_time: int | None = None
    no_lru_crawler: bool = False
    lru_crawler_sleep: int | None = None
    lru_crawler_tocrawl: int | None = None
    no_lru_maintainer: bool = False
    hot_lru_pct: int | None = None
    warm_lru_pct: int | None = None
    hot_max_factor: float | None = None
    warm_max_factor: float | None = None
    temporary_ttl: int | None = None
    idle_timeout: int | None = None
    watcher_logbuf_size: int | None = None
    worker_logbuf_size: int | None = None
    track_sizes: bool = False
    no_hashexpand: bool = False
    ext_path: str | None = None
    ext_path_size_gb: int | None = None
    ext_page_size: int | None = None
    ext_wbuf_size: int | None = None
    ext_threads: int | None = None
    ext_item_size: int | None = None
    ext_item_age: int | None = None
    ext_low_ttl: int | None = None
    ext_drop_unread: bool = False
    ext_recache_rate: int | None = None
    ext_compact_under: int | None = None
    ext_drop_under: int | None = None
    ext_max_frag: float | None = None
    slab_automove_freeratio: float | None = None
    memcached_path: str = "memcached"

    def argv(self) -> list[str]:
        """Build argv (without argv[0]) in memcached_binds order."""
        a: list[str] = []

        def u(flag: str, v, suffix: str = ""):
            if v is not None:
                a.append(f"{flag}{v}{suffix}")

        def b(flag: str, v: bool):
            if v:
                a.append(flag)

        u("--unix-socket=", self.unix_socket)
        b("--enable-shutdown", self.enable_ascii_shutdown)
        if self.unix_mask is not None:
            a.append(f"--unix-mask={self.unix_mask:o}")
        u("--listen=", self.listen_ipaddr)
        u("--user=", self.username)
        u("--memory-limit=", self.memory_limit)
        u("--conn-limit=", self.conn_limit)
        u("--max-reqs-per-event=", self.max_reqs_per_event)
        b("--lock-memory", self.lock_memory)
        a.append(f"--port={_addr_port(self.tcp_port)}")
        a.append(f"--udp-port={_addr_port(self.udp_port)}")
        b("--disable-evictions", self.disable_evictions)
        b("--enable-coredumps", self.enable_coredumps)
        u("--slab-growth-factor=", self.slab_growth_factor)
        u("--slab-min-size=", self.slab_min_size)
        b("--disable-cas", self.disable_cas)
        if self.verbose is not None:
            a.append(self.verbose.value)
        u("--threads=", self.threads)
        u("--napi-ids=", self.napi_ids)
        if self.delimiter is not None:
            a.append(f"-D{self.delimiter}")
        b("--enable-largepages", self.enable_largepages)
        u("--listen-backlog=", self.listen_backlog)
        if self.protocol is not None:
            a.append(f"--protocol={self.protocol.value}")
        u("--max-item-size=", self.max_item_size, "k")
        b("--enable-sasl", self.enable_sasl)
        b("--disable-flush-all", self.disable_flush_all)
        b("--disable-dumping", self.disable_dumping)
        b("--disable-watch", self.disable_watch)
        b("-omaxconns_fast", self.maxconns_fast)
        b("-ono_maxconns_fast", self.no_maxconns_fast)
        u("-ohashpower=", self.hashpower)
        u("-otail_repair_time=", self.tail_repair_time)
        b("-ono_lru_crawler", self.no_lru_crawler)
        u("-olru_crawler_sleep=", self.lru_crawler_sleep)
        u("-olru_crawler_tocrawl=", self.lru_crawler_tocrawl)
        b("-ono_lru_maintainer", self.no_lru_maintainer)
        u("-ohot_lru_pct=", self.hot_lru_pct)
        u("-owarm_lru_pct=", self.warm_lru_pct)
        u("-ohot_max_factor=", self.hot_max_factor)
        u("-owarm_max_factor=", self.warm_max_factor)
        u("-otemporary_ttl=", self.temporary_ttl)
        u("-oidle_timeout=", self.idle_timeout)
        u("-owatcher_logbuf_size=", self.watcher_logbuf_size)
        u("-oworker_logbuf_size=", self.worker_logbuf_size)
        b("-otrack_sizes", self.track_sizes)
        b("-ono_hashexpand", self.no_hashexpand)
        u("-oext_page_size=", self.ext_page_size)
        if self.ext_path is not None:
            sz = (f":{self.ext_path_size_gb}G"
                  if self.ext_path_size_gb is not None else "")
            a.append(f"-oext_path={self.ext_path}{sz}")
        u("-oext_wbuf_size=", self.ext_wbuf_size)
        u("-oext_threads=", self.ext_threads)
        u("-oext_item_size=", self.ext_item_size)
        u("-oext_item_age=", self.ext_item_age)
        u("-oext_low_ttl=", self.ext_low_ttl)
        b("-oext_drop_unread", self.ext_drop_unread)
        u("-oext_recache_rate=", self.ext_recache_rate)
        u("-oext_compact_under=", self.ext_compact_under)
        u("-oext_drop_under=", self.ext_drop_under)
        u("-oext_max_frag=", self.ext_max_frag)
        u("-oslab_automove_freeratio=", self.slab_automove_freeratio)
        return a


_STATS_FIELDS = ("cmd_set", "cmd_get", "get_hits", "get_misses",
                 "curr_items", "bytes_read", "bytes_written")


@dataclass(frozen=True)
class Stats:
    """memcached counters read via mc-stats (mem-db/memcached.c:291-299)."""
    cmd_set: int
    cmd_get: int
    get_hits: int
    get_misses: int
    curr_items: int
    bytes_read: int
    bytes_written: int
    raw: str = ""


def parse_stats(text: str) -> Stats:
    """Parse `STAT <field> <val>` lines (mem-db/memcached.c:464-475)."""
    from pyte.errors import MemcachedError
    vals = {}
    for f in _STATS_FIELDS:
        m = re.search(rf"STAT {f} ([0-9]+)", text)
        if not m:
            raise MemcachedError(f"mc-stats output lacks {f!r}: "
                                 f"{text[:200]!r}")
        vals[f] = int(m.group(1))
    return Stats(raw=text, **vals)


class Memcached:
    """A running memcached server (yielded by server())."""

    def __init__(self, pco: "RpcServer", job, opts: Opts):
        self._pco = pco
        self.job = job          # exposed: suite attaches filters/wrappers
        self.opts = opts

    def stats(self, timeout: float = 15.0,
              program: str = "mc-stats", quiet: bool = True) -> Stats:
        """Run mc-stats <port> and parse counters.

        Mirrors memcached_stats_get() (mem-db/memcached.c:432-517): a
        one-shot job whose full stdout is read and scraped for the
        seven counters.

        quiet mirrors the C's tapi_job_set_tracing toggles around the
        probe (mem-db/memcached.c:458-459,480,484) with one Job.quiet()
        bracket over filter attach/start/wait/read (the C re-enables
        tracing just for start+wait; not worth two brackets here).
        """
        from pyte.errors import MemcachedError
        port = _addr_port(self.opts.tcp_port)
        j = self._pco.job(program, [port])
        try:
            with j.quiet() if quiet else nullcontext():
                # Filter names match app-perf-ts mem-db/memcached.c:462,478
                # for log parity.
                flt = j.filter(stdout=True, readable=True,
                               name="stat stdout")
                j.filter(stderr=True, readable=False, log_level="WARN",
                         name="stat stderr")
                j.start()
                status = j.wait(timeout=timeout)
                if not status.ok:
                    raise MemcachedError(f"mc-stats exited with {status}")
                return parse_stats(flt.read_all(timeout=timeout))
        finally:
            j.destroy()


@contextmanager
def server(pco: "RpcServer", opts: Opts | None = None):
    """Create (but do not start) a memcached server job for the block.

    Yields a Memcached whose job is created with the C TAPI's filters
    (stdout RING / stderr WARN, tapi_memcached.c:296-309) but NOT yet
    started: the caller may attach extra filters or an accel wrapper
    first, then call m.job.start(). On exit: stop (SIGTERM, 10 s) +
    destroy, errors from stop tolerated (memcached often needs SIGKILL,
    which the C suite tolerates too, mem-db/memcached.c:419-424).
    """
    opts = opts or Opts()
    job = pco.job(opts.memcached_path, opts.argv())
    m = Memcached(pco, job, opts)
    try:
        job.stdout.log(level="RING")
        job.stderr.log(level="WARN")
        yield m
    finally:
        from pyte.errors import TeError
        try:
            job.stop()
        except TeError:
            pass
        job.destroy()
