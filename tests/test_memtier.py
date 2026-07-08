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
    assert opts.argv() == [
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
