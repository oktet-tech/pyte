# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools.trex.astf Client unit tests (fake remote, no agent)."""
import pytest

from pyte.errors import RemotePythonError, TrexError
from pyte.testing import FakeShimLib
from pyte.tools.trex import astf


class FakeRemote:
    """Stands in for a pyte.remote session: records shipped ops."""

    def __init__(self, results=None, raises=None):
        self.calls = []
        self.results = results or {}
        self.raises = raises or {}

    def call(self, fn, *args, timeout=None, **kwargs):
        self.calls.append((fn.__name__, args))
        if fn.__name__ in self.raises:
            raise RemotePythonError(self.raises[fn.__name__])
        return self.results.get(fn.__name__, {"ok": True})


def _client(rem):
    return astf.Client(rem, cli=object(), ports=[0, 1])


def test_load_profile_ships_the_text_then_loads_it():
    rem = FakeRemote(results={"write_profile": "/tmp/p.py"})
    c = _client(rem)
    c.load_profile("print(1)\n", "emix", tunables={"flow_size": 10})
    assert [name for name, _ in rem.calls] == ["write_profile",
                                               "load_profile"]
    assert rem.calls[1][1][1] == "/tmp/p.py"
    assert rem.calls[1][1][2] == {"flow_size": 10}


def test_load_profile_failure_names_the_profile_and_tunables():
    rem = FakeRemote(results={"write_profile": "/tmp/p.py"},
                     raises={"load_profile": "bad tunable"})
    c = _client(rem)
    with pytest.raises(TrexError) as e:
        c.load_profile("x\n", "emix", tunables={"flow_size": 99})
    assert "emix" in str(e.value)
    assert "flow_size" in str(e.value)


def test_get_global_parses_active_flows(fake_shim):
    rem = FakeRemote(results={"get_stats": {"global":
                                            {"active_flows": 42}}})
    assert _client(rem).get_global().active_flows == 42


def test_start_logs_a_readable_line(fake_shim):
    rem = FakeRemote()
    _client(rem).start(mult=2.0, duration=30.0, latency_pps=100)
    push_texts = [text for lvl, text in fake_shim.logs
                  if lvl == "STEP_PUSH"]
    text = "\n".join(fake_shim.texts(FakeShimLib.TE_LL_RING) +
                     push_texts)
    assert "mult=2.0" in text
    assert "duration=30.0" in text
    assert "latency_pps=100" in text


def test_poll_records_a_series_and_rings_one_line_per_tick(fake_shim):
    rem = FakeRemote(results={
        "get_stats": {"global": {"active_flows": 5, "tx_bps": 1e9}},
        "get_traffic_stats": {"client": {}, "server": {}}})
    c = _client(rem)
    ticks = iter([True, True, False])
    series = c.poll(every=0.0, until=lambda: next(ticks))
    assert len(series.samples) == 2
    assert len([x for x in fake_shim.texts(FakeShimLib.TE_LL_RING)
                if "active" in x]) == 2


def test_get_template_stats_is_empty_without_groups(fake_shim):
    rem = FakeRemote(results={"get_tg_names": []})
    assert _client(rem).get_template_stats() == []


def test_log_summary_reports_non_zero_flow_table_errors(fake_shim):
    rem = FakeRemote(results={
        "get_traffic_stats": {"client": {"err_cwf": 4},
                              "server": {}},
        "get_tg_names": []})
    c = _client(rem)
    c.log_summary(astf._stats.Series(), 0.0, 1.0)
    text = "\n".join(fake_shim.texts(FakeShimLib.TE_LL_RING) +
                     fake_shim.texts(FakeShimLib.TE_LL_WARN))
    assert "err_cwf" in text


class _FakeJob:
    def __init__(self):
        self.started = False
        self.destroyed = False
        self.stdout = self
        self.stderr = self

    def log(self, level=None):
        pass

    def start(self):
        self.started = True

    def destroy(self):
        self.destroyed = True


class _FakePco:
    ta = "TST1"

    def __init__(self):
        self.job_obj = _FakeJob()

    def job(self, path, args):
        return self.job_obj


def test_session_acquires_the_ports_before_yielding(fake_shim,
                                                    monkeypatch):
    """A connected ASTF client owns no port yet.

    TRex answers "must acquire the context for this operation" to
    load_profile until the ports are taken, which is how the first
    live bring-up failed. session() must therefore reset (force
    acquire) before it hands the client over, not leave it to the
    caller.
    """
    rem = FakeRemote(results={"write_cfg": "/tmp/c.yaml",
                              "bootstrap": object()})
    pco = _FakePco()

    class _Ctx:
        def __enter__(self):
            return rem

        def __exit__(self, *exc):
            return False

    import pyte.remote as remote_mod
    monkeypatch.setattr(remote_mod, "python", lambda p: _Ctx())

    opts = astf.ServerOpts(trex_exec="/usr/local/trex/t-rex-64",
                           ports=["0000:03:00.0", "0000:03:00.1"],
                           astf=True)
    with astf.session(pco, opts) as client:
        seen = [name for name, _ in rem.calls]
        assert "reset" in seen
        assert seen.index("reset") > seen.index("bootstrap")
        assert client is not None


def test_rate_scales_to_the_largest_prefix_that_fits():
    assert astf._rate(0.0, "bps") == "0.00 bps"
    assert astf._rate(615.94, "bps") == "615.94 bps"
    assert astf._rate(4450.0, "bps") == "4.45 Kbps"
    assert astf._rate(12.3e6, "pps") == "12.30 Mpps"
    assert astf._rate(4.67e9, "bps") == "4.67 Gbps"


def test_log_summary_logs_the_server_side_counters_too(fake_shim):
    # The connection line above it is the client's view, which is
    # what the tests key on; a device that drops connections only the
    # server sees is invisible without this line.
    rem = FakeRemote(results={
        "get_traffic_stats": {
            "client": {"tcps_connattempt": 30, "tcps_connects": 30,
                       "tcps_closed": 30},
            "server": {"tcps_accepts": 28, "tcps_closed": 27,
                       "tcps_drops": 2, "udps_accepts": 5},
        },
        "get_latency_stats": {},
        "get_tg_names": [],
    })
    c = _client(rem)
    c.log_summary(astf._stats.Series(), 0.0, 1.0)
    rings = "\n".join(fake_shim.texts(FakeShimLib.TE_LL_RING))
    assert "server side: accepted 28" in rings
    assert "drops 2" in rings
    # UDP is udps_accepts on the server, not
    # udps_connects: that name is client-side only, and
    # reading it here reported a flat zero on a live run
    # whose server had accepted 62 UDP flows.
    assert "udp accepted 5" in rings
