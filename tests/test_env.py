# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.env unit tests: dataclasses, lazy t.env, ownership."""
import pytest

from pyte import env as env_mod
from pyte._params import Params
from pyte.errors import EnvError
from pyte.rpc.server import RpcServer


class _EnvLib:
    """Fake shim for Env lookups and teardown."""

    PYTE_ENOENT = 0x7E02

    def __init__(self):
        self.calls = []
        self.pco_handle = object()

    def pyte_env_get_pco(self, h, name, out):
        self.calls.append(("get_pco", h, bytes(name)))
        out[0] = self.pco_handle
        return 0

    def pyte_rpc_server_ta_name(self, h, out):
        self.calls.append(("ta_name", h))
        out[0] = b"Agt_A"
        return 0

    def pyte_env_get_addr(self, h, name, ip_out, fam_out, port_out):
        self.calls.append(("get_addr", h, bytes(name)))
        ip_out[0] = b"10.0.0.1"
        fam_out[0] = b"inet"
        port_out[0] = 0
        return 0

    def pyte_free_string(self, h):
        self.calls.append(("free_string", h))
        return 0

    def pyte_env_free(self, h):
        self.calls.append(("env_free", h))
        return 0

    def pyte_allocate_port(self, h, out):
        self.calls.append(("allocate_port", h))
        out[0] = 12345
        return 0

    def pyte_rc_error(self, rc):
        return rc

    def pyte_rc_module(self, rc):
        return 0

    def te_rc_mod2str(self, rc):
        return b"TAPI"

    def te_rc_err2str(self, rc):
        return b"E"


class _EnvFfi:
    NULL = None

    def new(self, spec):
        return [None]

    @staticmethod
    def string(value):
        return value


def _fake_env(monkeypatch):
    import sys
    import types
    lib = _EnvLib()
    monkeypatch.setitem(sys.modules, "pyte._shim",
                        types.SimpleNamespace(ffi=_EnvFfi(), lib=lib))
    env = env_mod.Env.__new__(env_mod.Env)
    env._h = object()
    env._cfg = "test-env"
    env._pcos = {}
    return env, lib


def test_addr_pair():
    a = env_mod.Addr(ip="10.38.10.1", family="inet", port=7777)
    assert a.pair == ("10.38.10.1", 7777)


def test_addr_frozen():
    import dataclasses
    a = env_mod.Addr(ip="::1", family="inet6", port=0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        a.ip = "other"


def test_env_iface_bridge(monkeypatch):
    captured = {}

    class FakeIface:
        def __init__(self, agent, name):
            captured["args"] = (agent, name)

    monkeypatch.setattr("pyte.net.Iface", FakeIface)
    i = env_mod.EnvIface(name="veth0", index=5, agent="Agt_B")
    i.cfg_iface()
    assert captured["args"] == ("Agt_B", "veth0")


def test_rpc_server_not_owned_skips_destroy_but_clears_handle():
    """The env owns this server: destroy() must not call the shim, but
    it MUST drop the handle -- tapi_env_free frees that pointer, and a
    retained wrapper would keep passing it to C."""
    srv = RpcServer(object(), "Agt_A", "pco", owned=False)
    srv.destroy()          # must not touch the shim
    assert srv._h is None  # but the handle is no longer usable


def test_rpc_server_owned_default():
    srv = RpcServer(object(), "Agt_A", "pco")
    assert srv._owned is True


def test_test_env_requires_param():
    from pyte.test import Test
    t = Test(Params({"te_test_id": "1"}))
    with pytest.raises(EnvError, match="env"):
        t.env


def test_test_env_binds_once(monkeypatch):
    from pyte.test import Test
    bound = []

    class FakeEnv:
        def close(self):
            pass

    def fake_bind(cfg):
        bound.append(cfg)
        return FakeEnv()

    monkeypatch.setattr(env_mod.Env, "bind", staticmethod(fake_bind))
    t = Test(Params({"te_test_id": "1", "env": "{{{'p':IUT}}}"}))
    e1 = t.env
    e2 = t.env
    assert e1 is e2
    assert bound == ["{{{'p':IUT}}}"]


def test_enverror_is_teerror():
    from pyte.errors import TeError
    e = EnvError("env 'x' has no pco 'y'")
    assert isinstance(e, TeError)
    assert e.rc == 0
    assert "pco" in str(e)


def test_pco_returns_the_same_wrapper_for_the_same_server(monkeypatch):
    env, _ = _fake_env(monkeypatch)
    assert env.pco("iut_rpcs") is env.pco("iut_rpcs")


def test_pco_cache_hit_does_not_refetch_or_leak_ta_name(monkeypatch):
    """A cache hit must do no shim work: pyte_rpc_server_ta_name
    strdup()s the TA name, and only _take_str() on a fresh lookup
    frees it -- calling it again on a hit leaks that allocation."""
    env, lib = _fake_env(monkeypatch)
    env.pco("iut_rpcs")
    ta_name_calls_after_first = sum(
        1 for c in lib.calls if c[0] == "ta_name")
    env.pco("iut_rpcs")
    ta_name_calls_after_second = sum(
        1 for c in lib.calls if c[0] == "ta_name")
    assert ta_name_calls_after_first == 1
    assert ta_name_calls_after_second == 1


def test_close_invalidates_every_handed_out_pco(monkeypatch):
    from pyte.errors import ClosedResourceError
    env, _ = _fake_env(monkeypatch)
    pco = env.pco("iut_rpcs")
    env.close()
    with pytest.raises(ClosedResourceError):
        pco._handle()


def test_addr_rejects_a_stale_pco_as_port(monkeypatch):
    """A destroyed PCO passed as port= must raise, not reach the shim."""
    from pyte.errors import ClosedResourceError
    env, lib = _fake_env(monkeypatch)
    pco = env.pco("iut_rpcs")
    env.close()
    with pytest.raises(ClosedResourceError):
        env.addr("iut_addr", port=pco)
    assert not any(c[0] == "allocate_port" for c in lib.calls)


def test_env_close_idempotent():
    """close() on a handle-less Env is a no-op (no shim touched)."""
    e = env_mod.Env(None, "x")
    e.close()
    e.close()   # second call must also be silent


def test_env_close_clears_handle_on_error(monkeypatch):
    """close() clears _h before raising so a second close is a no-op."""
    import sys
    import types

    call_count = 0

    class FakeFfi:
        NULL = None

        def string(self, b):
            return b if isinstance(b, bytes) else b"unknown"

    class FakeLib:
        PYTE_ETIMEDOUT = 1
        PYTE_ENOENT = 2

        def pyte_env_free(self, h):
            nonlocal call_count
            call_count += 1
            return 0xDEAD  # nonzero: simulate failure

        def pyte_rc_module(self, rc):
            return 0

        def pyte_rc_error(self, rc):
            return rc

        def te_rc_mod2str(self, rc):
            return b"TAPI"

        def te_rc_err2str(self, rc):
            return b"EFAIL"

    fake_shim = types.SimpleNamespace(lib=FakeLib(), ffi=FakeFfi())
    monkeypatch.setitem(sys.modules, "pyte._shim", fake_shim)

    e = env_mod.Env(object(), "x")
    with pytest.raises(EnvError):
        e.close()

    # Handle must be cleared even though close raised.
    assert e._h is None

    # A second close must be a no-op (shim called exactly once).
    e.close()
    assert call_count == 1
