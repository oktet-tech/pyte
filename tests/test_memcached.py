# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools.memcached argv-builder and stats-parser tests (no testbed)."""
import pytest
from pyte.tools import memcached


def test_default_argv_is_ports_only():
    # tapi_memcached_default_opt sets tcp/udp port to zero_sockaddr =>
    # --port=0 --udp-port=0 always present (tapi_memcached.c:179-180).
    opts = memcached.Opts()
    assert opts.argv() == ["--port=0", "--udp-port=0"]


def test_suite_argv():
    # The option set mem-db/memcached.c:342-351 builds.
    opts = memcached.Opts(memory_limit=1024, threads=4, username="root",
                          tcp_port=("192.0.2.1", 11211),
                          enable_coredumps=True, conn_limit=1024,
                          napi_ids=4)
    assert opts.argv() == [
        "--user=root", "--memory-limit=1024", "--conn-limit=1024",
        "--port=11211", "--udp-port=0", "--enable-coredumps",
        "--threads=4", "--napi-ids=4",
    ]


def test_verbose_and_protocol_enums():
    opts = memcached.Opts(verbose=memcached.Verbose.MORE,
                          protocol=memcached.Proto.BINARY)
    argv = opts.argv()
    assert "-vv" in argv and "--protocol=binary" in argv


def test_ext_path_struct():
    # TAPI_JOB_OPT_STRUCT("-oext_path=", ":", ...) tapi_memcached.c:140-144
    opts = memcached.Opts(ext_path="/mnt/d1/extstore", ext_path_size_gb=1)
    assert "-oext_path=/mnt/d1/extstore:1G" in opts.argv()


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
    with pytest.raises(Exception):
        memcached.parse_stats("STAT pid 1\n")
