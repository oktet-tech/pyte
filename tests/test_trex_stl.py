# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools.trex.stl unit tests (offline: orchestration with fakes)."""
import pytest
from scapy.all import IP, UDP, Ether

from pyte.errors import TeError, TrexError
from pyte.tools.trex import PktBuilder, Stream, TXCont
from pyte.tools.trex import stl


def test_trexerror_message_path():
    e = TrexError("connect failed: no server")
    assert "connect failed" in str(e)
    assert e.rc == 0
    assert isinstance(e, TeError)


class _FakeRem:
    """Fake pyte.remote session: records (op_name, args), returns canned."""

    def __init__(self, canned):
        self.canned = canned          # op __name__ -> return value
        self.calls = []               # list of (op_name, args, kwargs)

    def call(self, fn, *args, **kwargs):
        self.calls.append((fn.__name__, args, kwargs))
        val = self.canned.get(fn.__name__)
        return val() if callable(val) else val


_STATS = {
    "0": {"opackets": 1000, "ipackets": 998, "obytes": 64000,
          "ibytes": 63872, "tx_pps": 500.0, "rx_pps": 499.0,
          "tx_bps": 256000.0, "rx_bps": 255488.0},
    "global": {"tx_bps": 256000.0, "rx_bps": 255488.0, "tx_pps": 500.0,
               "rx_pps": 499.0, "cpu_util": 5.0, "queue_full": 0},
}


def _client():
    rem = _FakeRem({
        "reset": {"ok": True},
        "add_streams": {"count": 1},
        "start": {"started": True},
        "wait_on_traffic": {"done": True},
        "get_stats": _STATS,
        "stop": {"stopped": True},
    })
    # cli sentinel stands in for the remote STLClient RemoteObject
    return stl.Client(rem, cli=object(), ports=[0, 1]), rem


def test_client_add_streams_shipped_and_logged():
    c, rem = _client()
    c.add_streams(Stream(packet=PktBuilder(Ether() / IP() / UDP()),
                         mode=TXCont(pps=1000), name="s1"), ports=[0])
    op, args, _ = rem.calls[-1]
    assert op == "add_streams"
    # args: (cli, port, [spec, ...])
    assert args[1] == 0
    assert args[2][0]["name"] == "s1"
    assert "pkt_b64" in args[2][0]


def test_client_start_passes_params():
    c, rem = _client()
    c.start(ports=[0], mult="10gbps", duration=10)
    op, args, _ = rem.calls[-1]
    assert op == "start"
    assert args[1:] == ([0], "10gbps", 10, False)


def test_client_get_stats_parses():
    c, _ = _client()
    ps = c.get_stats(ports=[0])[0]
    assert ps.tx_pkts == 1000
    assert ps.loss_pkts == 2


def test_wait_on_traffic_requires_an_explicit_timeout():
    """None used to promise "forever" and deliver the 30 s session
    default, killing any run longer than that."""
    c, _ = _client()
    with pytest.raises(ValueError, match="requires an explicit timeout"):
        c.wait_on_traffic(None)
    with pytest.raises(TypeError):
        c.wait_on_traffic()


def test_wait_on_traffic_rejects_a_negative_timeout():
    c, _ = _client()
    with pytest.raises(ValueError, match="must not be negative"):
        c.wait_on_traffic(-1)


def test_wait_on_traffic_explicit_zero_is_zero():
    """timeout=0 must mean zero seconds, not silently block forever
    (the old `timeout or None` turned any falsy float into None)."""
    c, rem = _client()
    c.wait_on_traffic(timeout=0)
    op, args, _ = rem.calls[-1]
    assert args[1] == 0


def test_wait_on_traffic_explicit_value_passes_through():
    c, rem = _client()
    c.wait_on_traffic(timeout=12.5)
    _, args, _ = rem.calls[-1]
    assert args[1] == 12.5


def test_wait_on_traffic_gives_the_transport_a_margin():
    """The native wait must expire before the transport carrying it,
    so the agent-side client reports why traffic did not finish."""
    c, rem = _client()
    c.wait_on_traffic(timeout=600)
    _, args, kwargs = rem.calls[-1]
    assert args[1] == 600                                # native wait
    assert kwargs["timeout"] == 600 + stl.WAIT_MARGIN    # transport


def test_control_ops_leave_the_transport_at_the_session_default():
    c, rem = _client()
    c.reset()
    _, _, kwargs = rem.calls[-1]
    assert kwargs["timeout"] is None


def test_session_removes_cfg_on_teardown(monkeypatch):
    """The mkstemp'd cfg YAML on the agent must not accumulate across
    runs on a shared DUT: teardown removes it best-effort."""
    from contextlib import contextmanager

    from pyte.tools.trex import _config

    calls = []

    class FakeRem:
        def call(self, fn, *args, **kwargs):
            calls.append((fn.__name__, args))
            if fn.__name__ == "write_cfg":
                return "/tmp/pyte_trex_x.yaml"
            if fn.__name__ == "bootstrap":
                return object()     # the remote cli
            return None

    @contextmanager
    def fake_python(pco, timeout=30.0, interpreter="python3"):
        yield FakeRem()

    class FakeChannel:
        def log(self, level=None):
            pass

    class FakeJob:
        stdout = FakeChannel()
        stderr = FakeChannel()

        def start(self):
            pass

        def destroy(self, *a, **k):
            pass

    class FakePco:
        ta = "Agt_A"

        def job(self, program, args=None):
            return FakeJob()

    monkeypatch.setattr("pyte.remote.python", fake_python)
    # session() logs via the real shim; quiet it (no TE logger here)
    from pyte import log
    monkeypatch.setattr(log, "step_push", lambda *a, **k: None)
    monkeypatch.setattr(log, "step_pop", lambda *a, **k: None)
    monkeypatch.setattr(log, "ring", lambda *a, **k: None)
    opts = _config.ServerOpts(trex_exec="/x/t-rex-64", ports=["0000:04:00.0"])
    with stl.session(FakePco(), opts):
        pass
    assert ("remove_file", ("/tmp/pyte_trex_x.yaml",)) in calls


def test_session_teardown_failure_does_not_mask_the_body_error(
        monkeypatch):
    """session()'s outermost finally used to let a failing job.destroy()
    replace the exception the body raised -- so a real bring-up failure
    surfaced as a teardown error instead."""
    from contextlib import contextmanager

    from pyte.tools.trex import _config

    class FakeRem:
        def call(self, fn, *args, **kwargs):
            if fn.__name__ == "write_cfg":
                return "/tmp/pyte_trex_x.yaml"
            if fn.__name__ == "bootstrap":
                return object()     # the remote cli
            return None

    @contextmanager
    def fake_python(pco, timeout=30.0, interpreter="python3"):
        yield FakeRem()

    class FakeChannel:
        def log(self, level=None):
            pass

    class FakeJob:
        stdout = FakeChannel()
        stderr = FakeChannel()

        def start(self):
            pass

        def destroy(self, *a, **k):
            raise RuntimeError("destroy failed")

    class FakePco:
        ta = "Agt_A"

        def job(self, program, args=None):
            return FakeJob()

    monkeypatch.setattr("pyte.remote.python", fake_python)
    # session() logs via the real shim; quiet it (no TE logger here)
    from pyte import log
    monkeypatch.setattr(log, "step_push", lambda *a, **k: None)
    monkeypatch.setattr(log, "step_pop", lambda *a, **k: None)
    monkeypatch.setattr(log, "ring", lambda *a, **k: None)
    opts = _config.ServerOpts(trex_exec="/x/t-rex-64", ports=["0000:04:00.0"])

    boom = RuntimeError("BODY BOOM")
    with pytest.raises(RuntimeError) as info:
        with stl.session(FakePco(), opts):
            raise boom
    assert info.value is boom                 # identity, not just message
    assert info.value.cleanup_errors          # destroy failure attached
