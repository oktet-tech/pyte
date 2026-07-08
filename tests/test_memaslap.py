# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools.memaslap argv/cfg-file/report tests (no testbed)."""
import pytest
from pyte.tools import memaslap


def test_suite_argv():
    # Mirrors run_memaslap() option set (mem-db/memcached.c:153-170).
    opts = memaslap.Opts(servers=(("192.0.2.1", 11211),), threads=4,
                         concurrency=256, time=60, bin_protocol=True,
                         verbose=True, cfg_cmd="/tmp/x.cfg")
    assert opts.argv() == [
        "--servers=192.0.2.1:11211", "--threads=4", "--concurrency=256",
        "--time=60s", "--binary", "--cfg_cmd=/tmp/x.cfg", "--verbose",
    ]


def test_cfg_text():
    # Exact format of tapi_memaslap.c:227-240.
    c = memaslap.CfgOpts(key_len_min=16, key_len_max=16,
                         value_len_min=1024, value_len_max=1024,
                         set_share=0.1)
    assert c.render() == ("key\n16 16 1\nvalue\n1024 1024 1\n"
                          "cmd\n0    0.10\n1    0.90\n")


def test_cfg_limits():
    with pytest.raises(ValueError):
        memaslap.CfgOpts(key_len_min=8, key_len_max=16,
                         value_len_min=1, value_len_max=1,
                         set_share=0.5)  # key_len_min < 16


def test_report_regexes():
    line = "Run time: 60.0s Ops: 100 TPS: 17891 Net_rate: 10.5M/s"
    assert memaslap._RE_TPS.search(line).group(1) == "17891"
    assert memaslap._RE_NET_RATE.search(line).group(1) == "10.5"


def test_pick_last_returns_last():
    assert memaslap._pick_last(["17891", "18200"], "TPS") == "18200"


def test_pick_last_empty_raises():
    from pyte.errors import MemaslapError
    with pytest.raises(MemaslapError, match="TPS"):
        memaslap._pick_last([], "TPS")


def test_argv_suffixes():
    opts = memaslap.Opts(win_size=10, stat_freq=5, expected_tps=20)
    argv = opts.argv()
    assert "--win_size=10k" in argv
    assert "--stat_freq=5s" in argv
    assert "--tps=20k" in argv


def test_multi_server_and_addr():
    class _Addr:
        pair = ("b", 2)

    opts = memaslap.Opts(servers=(("a", 1), _Addr()))
    argv = opts.argv()
    assert argv[0] == "--servers=a:1,b:2"


def test_make_report_good():
    r = memaslap._make_report("17891", "10.5", "memaslap --servers=x:1")
    assert r.tps == 17891
    assert abs(r.net_rate - 84.0) < 1e-6
    assert r.cmd == "memaslap --servers=x:1"


def test_make_report_malformed_tps():
    from pyte.errors import MemaslapError
    with pytest.raises(MemaslapError, match="TPS"):
        memaslap._make_report("bad", "10.5", "cmd")


def test_make_report_malformed_net_rate():
    from pyte.errors import MemaslapError
    with pytest.raises(MemaslapError, match="Net_rate"):
        memaslap._make_report("17891", "bad", "cmd")
