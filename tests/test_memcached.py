# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools.memcached argv-builder and stats-parser tests (no testbed)."""
from contextlib import contextmanager

import pytest
from pyte.errors import MemcachedError
from pyte.tools import memcached


def test_default_argv_is_ports_only():
    # tapi_memcached_default_opt sets tcp/udp port to zero_sockaddr =>
    # --port=0 --udp-port=0 always present (tapi_memcached.c:179-180).
    opts = memcached.Opts()
    assert opts.to_argv() == ["--port=0", "--udp-port=0"]


def test_suite_argv():
    # The option set mem-db/memcached.c:342-351 builds.
    opts = memcached.Opts(memory_limit=1024, threads=4, username="root",
                          tcp_port=("192.0.2.1", 11211),
                          enable_coredumps=True, conn_limit=1024,
                          napi_ids=4)
    assert opts.to_argv() == [
        "--user=root", "--memory-limit=1024", "--conn-limit=1024",
        "--port=11211", "--udp-port=0", "--enable-coredumps",
        "--threads=4", "--napi-ids=4",
    ]


def test_verbose_and_protocol_enums():
    opts = memcached.Opts(verbose=memcached.Verbose.MORE,
                          protocol=memcached.Proto.BINARY)
    argv = opts.to_argv()
    assert "-vv" in argv and "--protocol=binary" in argv


def test_ext_path_struct():
    # TAPI_JOB_OPT_STRUCT("-oext_path=", ":", ...) tapi_memcached.c:140-144
    opts = memcached.Opts(ext_path="/mnt/d1/extstore", ext_path_size_gb=1)
    assert "-oext_path=/mnt/d1/extstore:1G" in opts.to_argv()


def test_stats_parse():
    out = ("STAT pid 1\nSTAT cmd_get 200\nSTAT cmd_set 100\n"
           "STAT get_hits 190\nSTAT get_misses 10\nSTAT curr_items 42\n"
           "STAT bytes_read 1000\nSTAT bytes_written 2000\n")
    s = memcached.parse_stats(out)
    assert s.cmd_set == 100 and s.cmd_get == 200
    assert s.get_hits == 190 and s.get_misses == 10
    assert s.curr_items == 42
    assert s.bytes_read == 1000 and s.bytes_written == 2000


def test_stats_parse_missing_field_raises():
    with pytest.raises(MemcachedError, match="cmd_set"):
        memcached.parse_stats("STAT pid 1\n")


def test_addr_duck_type():
    # Duck-typed Addr object with .pair => port extracted from pair[1].
    class FakeAddr:
        pair = ("192.0.2.1", 11211)

    opts = memcached.Opts(tcp_port=FakeAddr())
    assert "--port=11211" in opts.to_argv()


def test_unix_mask_octal():
    # unix_mask emitted as octal digits (0o755 -> "755").
    opts = memcached.Opts(unix_mask=0o755)
    assert "--unix-mask=755" in opts.to_argv()


def test_delimiter_flag():
    # delimiter emits -D<char> (tapi_memcached.c option "-D").
    opts = memcached.Opts(delimiter=":")
    assert "-D:" in opts.to_argv()


# -- Memcached.stats() quiet bracket (mem-db/memcached.c:458-484) ------------

_STATS_OUT = "".join(
    f"STAT {f} {i}\n"
    for i, f in enumerate(("cmd_set", "cmd_get", "get_hits", "get_misses",
                           "curr_items", "bytes_read", "bytes_written")))


class _FakeStatus:
    ok = True


class _FakeFilter:
    def read_all(self, timeout):
        return _STATS_OUT


class _FakeJob:
    def __init__(self, calls):
        self.calls = calls

    def filter(self, **kw):
        self.calls.append(("filter", kw.get("name")))
        return _FakeFilter()

    def start(self):
        self.calls.append("start")

    def wait(self, timeout):
        self.calls.append("wait")
        return _FakeStatus()

    def destroy(self):
        self.calls.append("destroy")

    @contextmanager
    def quiet(self):
        self.calls.append("quiet-on")
        try:
            yield self
        finally:
            self.calls.append("quiet-off")


class _FakePco:
    def __init__(self):
        self.calls = []

    def job(self, program, argv):
        self.calls.append(("job", program, argv))
        return _FakeJob(self.calls)


def test_stats_quiet_wraps_probe():
    # quiet=True (default): filter attach, start, wait and the read all
    # happen inside one Job.quiet() bracket; destroy stays outside.
    pco = _FakePco()
    m = memcached.Memcached(pco, job=None,
                            opts=memcached.Opts(tcp_port=11211))
    s = m.stats()
    assert s.cmd_set == 0 and s.bytes_written == 6
    assert pco.calls == [("job", "mc-stats", ["11211"]),
                         "quiet-on",
                         ("filter", "stat stdout"),
                         ("filter", "stat stderr"),
                         "start", "wait",
                         "quiet-off", "destroy"]


def test_stats_quiet_false_keeps_tracing():
    pco = _FakePco()
    m = memcached.Memcached(pco, job=None,
                            opts=memcached.Opts(tcp_port=11211))
    m.stats(quiet=False)
    assert "quiet-on" not in pco.calls
