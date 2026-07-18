# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools.memtier argv/report tests (no testbed)."""
import pytest
from pyte.tools import memtier


def test_suite_argv():
    # Mirrors run_memtier() option set (mem-db/memcached.c:203-228).
    opts = memtier.Opts(server=("192.0.2.1", 11211),
                        protocol=memtier.Proto.MEMCACHE_BINARY,
                        clients=64, threads=4, test_time=60,
                        data_size=1024, ratio="1:9", key_prefix="memtier---",
                        key_pattern="S:R", key_minimum=100000,
                        key_maximum=200000, hide_histogram=True)
    assert opts.to_argv() == [
        "--server=192.0.2.1", "--port=11211",
        "--protocol=memcache_binary", "--clients=64", "--threads=4",
        "--test-time=60", "--data-size=1024", "--ratio=1:9",
        "--key-prefix=memtier---", "--key-pattern=S:R",
        "--key-minimum=100000", "--key-maximum=200000",
        "--hide-histogram",
    ]


def test_parse_row():
    row = ("Sets         1785.61          ---          ---      "
           "0.11500       1954.32")
    s = memtier.parse_row(row)
    assert s.tps == 1785.61
    # last field is KB/s -> /1024*8 Mbit/s (tapi_memtier.c:314-318)
    assert s.net_rate == pytest.approx(1954.32 / 1024 * 8)
    assert s.parsed


def test_parse_report_table():
    rows = [
        "Sets   1785.61   ---   ---   0.11500   1954.32",
        "Gets   16070.13  1785.61  14284.52  0.11400  15370.29",
        "Totals 17855.74  1785.61  14284.52  0.11400  17324.61",
    ]
    rep = memtier.parse_report(rows, cmd="memtier_benchmark ...")
    assert rep.totals.tps == 17855.74
    assert rep.gets.parsed and rep.sets.parsed
    assert rep.totals.net_rate == pytest.approx(17324.61 / 1024 * 8)


def test_parse_report_last_table_wins():
    # --run-count>1: later tables overwrite earlier (tapi_memtier.c:353-357)
    rows = [
        "Totals 100.0  ---  ---  0.1  100.0",
        "Totals 200.0  ---  ---  0.1  200.0",
    ]
    rep = memtier.parse_report(rows, cmd="x")
    assert rep.totals.tps == 200.0


def test_parse_report_empty_raises():
    from pyte.errors import MemtierError
    with pytest.raises(MemtierError, match="statistics"):
        memtier.parse_report([], cmd="x")


def test_parse_row_malformed():
    from pyte.errors import MemtierError
    with pytest.raises(MemtierError, match="malformed"):
        memtier.parse_row("Sets --- ---")


def test_argv_stub_server_extra_flags():
    """Addr-like stub with .pair, run_count, pipeline, random_data, debug."""

    class _Addr:
        pair = ("192.0.2.7", 6379)

    opts = memtier.Opts(server=_Addr(), run_count=2, requests=100,
                        pipeline=8, random_data=True, debug=True)
    argv = opts.to_argv()
    assert "--server=192.0.2.7" in argv
    assert "--port=6379" in argv
    assert "--run-count=2" in argv
    assert "--requests=100" in argv
    assert "--pipeline=8" in argv
    assert "--random-data" in argv
    assert "--debug" in argv
    # order: server flags come first, --random-data before --debug
    assert argv.index("--random-data") < argv.index("--debug")


# -- _read_output timeout plumbing (A3) --------------------------------------

class _FakeFilter:
    def __init__(self):
        self.calls = []

    def messages(self, timeout=None):
        self.calls.append(timeout)
        return []


def test_read_output_forwards_passed_timeout_not_hardcoded():
    """A3: the base passes the remaining wait() budget; memtier must
    not hardcode messages(timeout=10.0), ignoring it."""
    stats_flt = _FakeFilter()
    h = memtier.Memtier(job=None, stats_flt=stats_flt, cmd="x")
    h._read_output(2.5)
    assert stats_flt.calls == [2.5]
