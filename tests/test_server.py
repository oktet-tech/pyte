# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""RpcServer unit tests (fake shim / fake transport)."""
import sys
import types

import pytest

from pyte.rpc.server import RpcServer


class _SleepServer(RpcServer):
    """RpcServer with system()/sh() replaced by recorders."""

    def __init__(self):
        # bypass RpcServer.__init__ (no RCF behind these tests)
        self._h = object()
        self.system_calls = []
        self.system_status = 0

    def system(self, cmd, timeout=None):
        self.system_calls.append((cmd, timeout))
        return self.system_status

    def sh(self, cmd):
        raise AssertionError(
            "sleep() must not use the multi-RPC sh(): a raised RPC "
            "timeout covers only its FIRST rpc, not the sleep")


@pytest.fixture()
def _no_shim_calls(monkeypatch):
    """Any transport shim call in sleep() is a bug now — fail loudly.

    Only the TeError rc-stringify helpers are allowed (RpcError
    construction); pyte_rpc_set_timeout / pyte_rpc_shell_get_all etc.
    trip the trap.
    """
    class TrapLib:
        PYTE_ETIMEDOUT = 110

        @staticmethod
        def pyte_rc_error(rc):
            return rc

        @staticmethod
        def pyte_rc_module(rc):
            return 0

        @staticmethod
        def te_rc_mod2str(rc):
            return b"RPC"

        @staticmethod
        def te_rc_err2str(rc):
            return b"E"

        def __getattr__(self, name):
            raise AssertionError(f"unexpected shim call {name}")

    class TrapFfi:
        @staticmethod
        def string(b):
            return b

    monkeypatch.setitem(sys.modules, "pyte._shim",
                        types.SimpleNamespace(ffi=TrapFfi(), lib=TrapLib()))


def test_sleep_is_one_system_rpc_with_covering_timeout(_no_shim_calls):
    """The timeout must cover the WHOLE remote sleep: one rpc_system()
    call with timeout = seconds + margin."""
    srv = _SleepServer()
    srv.sleep(2.5)
    assert srv.system_calls == [("sleep 2.5", 12.5)]


def test_sleep_rejects_negative(_no_shim_calls):
    with pytest.raises(ValueError, match=">= 0"):
        _SleepServer().sleep(-1)


def test_sleep_raises_on_nonzero_exit(_no_shim_calls):
    from pyte.errors import RpcError
    srv = _SleepServer()
    srv.system_status = 2
    with pytest.raises(RpcError, match="sleep"):
        srv.sleep(1.0)


def test_sleep_suppressed_returns_quietly(_no_shim_calls):
    """Under expect_error, system() returns None (SUPPRESSED)."""
    srv = _SleepServer()
    srv.system_status = None
    srv.sleep(1.0)   # no raise
