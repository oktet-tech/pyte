# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.env unit tests: dataclasses, lazy t.env, ownership."""
import pytest

from pyte import env as env_mod
from pyte._params import Params
from pyte.errors import EnvError
from pyte.rpc.server import RpcServer


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


def test_rpc_server_not_owned_skips_destroy():
    srv = RpcServer(object(), "Agt_A", "pco", owned=False)
    srv.destroy()          # must not touch the shim
    assert srv._h is not None  # handle intentionally left alone


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
