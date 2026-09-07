# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tad.csap unit tests (fake shim): session cache + Receiver state."""
import sys
import types
from types import SimpleNamespace

import pytest

from pyte.tad import csap as csapmod
from pyte.tad.csap import Csap, Receiver


@pytest.fixture(autouse=True)
def _clear_sessions():
    """The session cache is a module-level dict; keep tests independent."""
    csapmod._sessions.clear()
    yield
    csapmod._sessions.clear()


class FakeLib:
    PYTE_ETIMEDOUT = 110

    def __init__(self):
        self.calls = []
        self.session_rc = 0
        self.recv_rc = 0
        #: rc-steering knob for destroy() failure tests
        self.destroy_rc = 0
        #: packet handles pyte_csap_recv_wait/stop deliver
        self.recv_pkts = []

    def pyte_ta_session(self, ta, out):
        self.calls.append(("ta_session", bytes(ta)))
        out[0] = 42
        return self.session_rc

    def _recv(self, kind, ta, session, handle, out):
        self.calls.append((kind, bytes(ta)))
        out.pkts = list(self.recv_pkts)
        out.n = len(self.recv_pkts)
        return self.recv_rc

    def pyte_csap_recv_wait(self, ta, session, handle, out):
        return self._recv("recv_wait", ta, session, handle, out)

    def pyte_csap_recv_stop(self, ta, session, handle, out):
        return self._recv("recv_stop", ta, session, handle, out)

    def pyte_pkts_free(self, out):
        self.calls.append(("pkts_free",))

    def pyte_pkt_free(self, h):
        self.calls.append(("pkt_free", h))

    def pyte_csap_destroy(self, ta, session, handle):
        self.calls.append(("csap_destroy", bytes(ta)))
        return self.destroy_rc

    # TeError construction helpers
    def pyte_rc_error(self, rc):
        return rc

    def pyte_rc_module(self, rc):
        return 0

    def te_rc_mod2str(self, rc):
        return b"TAD"

    def te_rc_err2str(self, rc):
        return b"EFAIL"


class FakeFfi:
    NULL = object()

    def new(self, spec, *a):
        if spec == "pyte_pkts *":
            return SimpleNamespace(pkts=[], n=0)
        return [0 if not a else a[0]]

    @staticmethod
    def string(b):
        return b


def _fake_shim(monkeypatch):
    lib = FakeLib()
    monkeypatch.setitem(sys.modules, "pyte._shim",
                        types.SimpleNamespace(ffi=FakeFfi(), lib=lib))
    return lib


def _bare_csap(ta="Agt_A"):
    """A Csap without going through pyte_csap_create."""
    c = Csap.__new__(Csap)
    c.ta = ta
    c.stack_id = "udp.ip4"
    c._session = 42
    c._handle = 7
    c._rx = None
    return c


# -- session cache ------------------------------------------------------

def test_session_cached_per_agent(monkeypatch):
    lib = _fake_shim(monkeypatch)
    assert csapmod._session("A") == 42
    assert csapmod._session("A") == 42
    assert [c for c in lib.calls if c[0] == "ta_session"] == \
        [("ta_session", b"A")]


def test_reset_sessions_single_agent(monkeypatch):
    """After an agent reboot its cached RCF session id is dead; a
    public reset must exist (reaching into _sessions is not an API)."""
    lib = _fake_shim(monkeypatch)
    csapmod._session("A")
    csapmod._session("B")
    csapmod.reset_sessions("A")
    csapmod._session("A")           # re-created
    csapmod._session("B")           # still cached
    assert [c for c in lib.calls if c[0] == "ta_session"] == [
        ("ta_session", b"A"), ("ta_session", b"B"), ("ta_session", b"A")]


def test_reset_sessions_all(monkeypatch):
    lib = _fake_shim(monkeypatch)
    csapmod._session("A")
    csapmod._session("B")
    csapmod.reset_sessions()
    csapmod._session("A")
    csapmod._session("B")
    assert len([c for c in lib.calls if c[0] == "ta_session"]) == 4


def test_reset_sessions_exported_from_tad():
    import pyte.tad as tad
    assert tad.reset_sessions is csapmod.reset_sessions
    assert "reset_sessions" in tad.__all__


# -- Receiver._finish state honesty --------------------------------------

def test_finish_success_marks_done(monkeypatch):
    lib = _fake_shim(monkeypatch)
    c = _bare_csap()
    rx = Receiver(c)
    c._rx = rx
    lib.recv_pkts = ["p1", "p2"]

    pkts = rx.wait()

    assert [p._h for p in pkts] == ["p1", "p2"]
    assert rx._done and c._rx is None
    c.destroy()   # avoid leaking the bare CSAP past this test


def test_finish_timeout_is_not_an_error(monkeypatch):
    lib = _fake_shim(monkeypatch)
    c = _bare_csap()
    rx = Receiver(c)
    c._rx = rx
    lib.recv_rc = lib.PYTE_ETIMEDOUT
    lib.recv_pkts = ["p1"]

    pkts = rx.wait()

    assert len(pkts) == 1
    assert rx._done and c._rx is None
    c.destroy()   # avoid leaking the bare CSAP past this test


def test_finish_failure_keeps_receiver_active_and_frees_partials(
        monkeypatch):
    """On an RCF error the operation did NOT complete: Python must not
    pretend no receive is active (destroy() would then skip the stop),
    and the partially-collected packets must be freed, not leaked to
    GC timing."""
    from pyte.errors import TeError
    lib = _fake_shim(monkeypatch)
    c = _bare_csap()
    rx = Receiver(c)
    c._rx = rx
    lib.recv_rc = 12                # non-timeout failure
    lib.recv_pkts = ["p1", "p2"]

    with pytest.raises(TeError):
        rx.wait()

    assert not rx._done, "failed finish must not mark the receive done"
    assert c._rx is rx, "csap must still consider the receive active"
    assert [x for x in lib.calls if x[0] == "pkt_free"] == [
        ("pkt_free", "p1"), ("pkt_free", "p2")]

    lib.recv_rc = 0     # let destroy()'s stop-then-destroy succeed;
    c.destroy()         # avoid leaking the bare CSAP past this test


def test_destroy_logs_swallowed_stop_failure(monkeypatch):
    """destroy() ignores a failing receive-stop by design (the CSAP is
    going away) but must say so in the log, not hide the root cause."""
    lib = _fake_shim(monkeypatch)
    warnings = []
    from pyte import log
    monkeypatch.setattr(log, "warn", lambda msg, *a, **k:
                        warnings.append(msg))
    c = _bare_csap()
    rx = Receiver(c)
    c._rx = rx
    lib.recv_rc = 12                # stop() inside destroy() fails

    c.destroy()

    assert [x for x in lib.calls if x[0] == "csap_destroy"]
    assert warnings and "stop" in warnings[0]


# -- Csap.__del__ (finalizer) --------------------------------------------

def test_del_warns_but_does_not_touch_the_shim(monkeypatch):
    """A Csap dropped without destroy()/a context manager leaks the
    agent-side CSAP for the whole run; __del__ must warn so the leak
    is visible.  It must NOT call into the shim: destroy() is
    RPC-backed (a possible receive-stop plus pyte_csap_destroy over
    RCF) and GC can fire mid-request, so this is warn-only -- unlike
    Packet.free(), which is a local, synchronous, non-RPC free."""
    lib = _fake_shim(monkeypatch)
    c = _bare_csap()

    with pytest.warns(ResourceWarning, match="never destroyed"):
        c.__del__()

    assert lib.calls == []
    assert c._handle == 7, "must not free anything from __del__"


def test_del_is_a_noop_after_destroy(monkeypatch, recwarn):
    """__del__ on an already-destroyed Csap must not warn."""
    lib = _fake_shim(monkeypatch)
    c = _bare_csap()
    c.destroy()
    lib.calls.clear()

    c.__del__()

    assert lib.calls == []
    assert len(recwarn) == 0


def test_context_manager_preserves_body_exception_when_destroy_fails(
        monkeypatch):
    """__exit__ already receives the body's exception as its second
    argument, so a failing destroy() must not replace it: the body's
    exception keeps its identity and the destroy failure is attached
    as a cleanup_errors entry instead of being logged and swallowed."""
    lib = _fake_shim(monkeypatch)
    lib.destroy_rc = 12
    c = _bare_csap()
    boom = RuntimeError("BODY BOOM")

    with pytest.raises(RuntimeError) as info:
        with c:
            raise boom

    assert info.value is boom
    assert len(boom.cleanup_errors) == 1
