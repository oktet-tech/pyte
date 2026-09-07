# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools.trex.astf Client unit tests (fake remote, no agent)."""
import pytest

from pyte.errors import RemotePythonError, TrexError
from pyte.testing import FakeShimLib
from pyte.tools.trex import _agent, astf


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


def test_load_profile_writes_into_the_directory_it_was_given(fake_shim):
    """write_profile() runs on the agent and cannot reach the
    Configurator, so session() reads /agent:<ta>/tmp_dir: and hands the
    value to the Client, which passes it to every profile write."""
    rem = FakeRemote(results={"write_profile": "/agent/tmp/p.py"})
    c = astf.Client(rem, cli=object(), ports=[0, 1],
                    tmp_dir="/agent/tmp")
    c.load_profile("print(1)\n", "emix")
    assert rem.calls[0][1] == ("print(1)\n", ".py", "/agent/tmp")


def test_load_profile_without_a_directory_keeps_the_mkstemp_default(
        fake_shim):
    """No usable tmp_dir on the agent is a fallback, not a failure."""
    rem = FakeRemote(results={"write_profile": "/tmp/p.py"})
    c = _client(rem)
    c.load_profile("print(1)\n", "emix")
    assert rem.calls[0][1][2] is None


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
    def __init__(self, trace=None):
        self.started = False
        self.destroyed = False
        # Shared with a FakeRemote's call list where a test wants one
        # ordered trace of shipped ops and job lifecycle events.
        self.trace = [] if trace is None else trace
        self.stdout = self
        self.stderr = self

    def log(self, level=None):
        pass

    def start(self):
        self.started = True

    def destroy(self):
        self.destroyed = True
        self.trace.append(("destroy", ()))


class _FakePco:
    ta = "TST1"

    def __init__(self, trace=None):
        self.job_obj = _FakeJob(trace)

    def job(self, path, args):
        return self.job_obj


def _fake_remote_python(monkeypatch, rem):
    """Make pyte.remote.python() hand out *rem* instead of an agent."""
    class _Ctx:
        def __enter__(self):
            return rem

        def __exit__(self, *exc):
            return False

    import pyte.remote as remote_mod
    monkeypatch.setattr(remote_mod, "python", lambda p: _Ctx())
    # No Configurator here: hand session() a directory directly.
    monkeypatch.setattr(_agent, "tmp_dir", lambda ta: "/agent/tmp")


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
    _fake_remote_python(monkeypatch, rem)

    opts = astf.ServerOpts(trex_exec="/usr/local/trex/t-rex-64",
                           ports=["0000:03:00.0", "0000:03:00.1"],
                           astf=True)
    with astf.session(pco, opts) as client:
        seen = [name for name, _ in rem.calls]
        assert "reset" in seen
        assert seen.index("reset") > seen.index("bootstrap")
        assert client is not None
        # Both temp files land in the agent's own directory: the cfg
        # written here, and whatever the Client writes later.
        assert rem.calls[0] == ("write_cfg", (opts.cfg_yaml(),
                                              "/agent/tmp"))
        assert client._tmp_dir == "/agent/tmp"


def _astf_opts():
    return astf.ServerOpts(trex_exec="/usr/local/trex/t-rex-64",
                           ports=["0000:03:00.0", "0000:03:00.1"],
                           astf=True)


def test_session_destroys_trex_before_removing_its_cfg(fake_shim,
                                                       monkeypatch):
    """Teardown order, not just teardown coverage.

    TRex reopens the config it was started with while shutting down
    (cleanup_servers()), so unlinking the file first made every run --
    passing ones included -- carry a FileNotFoundError traceback from
    a TRex already on its way out.
    """
    rem = FakeRemote(results={"write_cfg": "/tmp/c.yaml",
                              "bootstrap": object()})
    pco = _FakePco(trace=rem.calls)
    _fake_remote_python(monkeypatch, rem)

    with astf.session(pco, _astf_opts()):
        pass
    seen = [name for name, _ in rem.calls]
    assert "destroy" in seen and "remove_file" in seen
    assert seen.index("destroy") < seen.index("remove_file")
    assert pco.job_obj.destroyed


def test_session_order_holds_and_keeps_the_body_error(fake_shim,
                                                      monkeypatch):
    """The reorder must not cost the property cleanup_all exists for:
    a teardown failure is attached to the body's exception, never
    substituted for it, and the cfg is still removed after the kill."""
    rem = FakeRemote(results={"write_cfg": "/tmp/c.yaml",
                              "bootstrap": object()})
    pco = _FakePco(trace=rem.calls)
    _fake_remote_python(monkeypatch, rem)

    def _boom_destroy():
        rem.calls.append(("destroy", ()))
        raise RuntimeError("destroy failed")

    pco.job_obj.destroy = _boom_destroy
    boom = RuntimeError("BODY BOOM")
    with pytest.raises(RuntimeError) as info:
        with astf.session(pco, _astf_opts()):
            raise boom
    assert info.value is boom              # identity, not just message
    assert info.value.cleanup_errors       # destroy failure attached
    seen = [name for name, _ in rem.calls]
    assert seen.index("destroy") < seen.index("remove_file")


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


def test_every_shipped_op_is_announced_at_verb(fake_shim):
    # Half the API opens no step bracket, so before this line a run
    # left no record of the stats polls at all -- and a bring-up
    # failure gave a traceback with no way to tell which call was in
    # flight.
    rem = FakeRemote(results={"get_stats": {"global": {}},
                              "get_traffic_stats": {"client": {},
                                                    "server": {}}})
    c = _client(rem)
    c.get_global()
    c.get_traffic()
    c.clear_stats()
    verbs = fake_shim.texts(FakeShimLib.TE_LL_VERB)
    assert "astf op: get_stats" in verbs
    assert "astf op: get_traffic_stats" in verbs
    assert "astf op: clear_stats" in verbs


def test_the_verb_line_names_the_op_the_error_names(fake_shim):
    rem = FakeRemote(raises={"stop": "no context"})
    with pytest.raises(TrexError) as e:
        _client(rem).stop()
    verbs = fake_shim.texts(FakeShimLib.TE_LL_VERB)
    assert verbs[-1] == "astf op: stop"
    assert str(e.value).startswith("stop failed:")


def test_verb_detail_is_small_and_only_where_it_helps(fake_shim):
    rem = FakeRemote(results={"get_tg_names": ["a", "b", "c"],
                              "get_tg_stats": {}})
    c = _client(rem)
    c.start(mult=2.0, duration=30.0, latency_pps=100)
    c.wait_on_traffic(timeout=5.0)
    c.get_template_stats()
    verbs = fake_shim.texts(FakeShimLib.TE_LL_VERB)
    assert ("astf op: start mult=2.0 duration=30.0 nc=False "
            "latency_pps=100") in verbs
    assert "astf op: wait_on_traffic timeout=5.0" in verbs
    # The group names go over the wire; only their count goes in
    # the log, which is what a reader needs from them.
    assert "astf op: get_tg_stats 3 template group(s)" in verbs
    # A stats reply is a counter dict; rendering one would turn a
    # line into a page.
    assert "astf op: get_tg_names" in verbs
