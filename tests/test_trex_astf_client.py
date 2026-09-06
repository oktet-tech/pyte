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
