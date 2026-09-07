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
    assert opts.to_argv() == [
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
    opts = memaslap.Opts(win_size_kb=10, stat_freq=5, expected_ktps=20)
    argv = opts.to_argv()
    assert "--win_size=10k" in argv
    assert "--stat_freq=5s" in argv
    assert "--tps=20k" in argv


def test_multi_server_and_addr():
    class _Addr:
        pair = ("b", 2)

    opts = memaslap.Opts(servers=(("a", 1), _Addr()))
    argv = opts.to_argv()
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


# -- _read_output timeout plumbing (A3) --------------------------------------

class _FakeFilter:
    def __init__(self):
        self.calls = []

    def messages(self, timeout=None):
        self.calls.append(timeout)
        return []


def test_read_output_forwards_passed_timeout_not_hardcoded():
    """A3: the base passes the remaining wait() budget; memaslap must
    not hardcode messages(timeout=10.0), ignoring it."""
    tps_flt, net_flt = _FakeFilter(), _FakeFilter()
    h = memaslap.Memaslap(job=None, tps_flt=tps_flt, net_flt=net_flt,
                          cmd="x", pco=None, cfg_fn=None)
    h._read_output(2.5)
    assert tps_flt.calls == [2.5]
    assert net_flt.calls == [2.5]


# -- run(): cfg-file cleanup must not mask a bring-up failure -----------

_boom_start = RuntimeError("start failed")


class _FakeJob:
    def filter(self, **kw):
        return _FakeFilter()

    def start(self):
        raise _boom_start

    def destroy(self, *a, **k):
        pass


class _FakePco:
    def __init__(self):
        self.put = {}
        self.unlinked = []

    def file_put(self, path, data):
        self.put[path] = data

    def job(self, program, argv):
        return _FakeJob()

    def unlink(self, path):
        self.unlinked.append(path)
        raise RuntimeError("unlink failed")


def test_run_preserves_bring_up_error_when_cfg_cleanup_also_fails():
    """A pco.unlink() failure while cleaning up the temp cfg file after
    a failed launch() must not replace the real bring-up failure."""
    pco = _FakePco()
    cfg_opts = memaslap.CfgOpts(key_len_min=16, key_len_max=16,
                                value_len_min=1, value_len_max=1,
                                set_share=0.5)
    opts = memaslap.Opts(servers=(("h", 1),))

    with pytest.raises(RuntimeError) as info:
        with memaslap.run(pco, opts, cfg_opts):
            pass  # pragma: no cover -- run() raises before yielding

    assert info.value is _boom_start     # identity, not a message match
    assert info.value.cleanup_errors     # unlink failure attached
    assert len(pco.unlinked) == 1
