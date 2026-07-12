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


def test_sleep_ok_run_is_quiet(_no_shim_calls):
    srv = _SleepServer()
    srv.system_status = 0
    srv.sleep(1.0)   # no raise


# -- expect_error: pytest.raises-style catching CM -----------------------

def _rpc_error(code):
    from pyte.errors import RpcError
    e = RpcError(0, "call()", "remote failed")
    e.code = code            # TE error part, as _check_call sets it
    return e


def _bare_server():
    srv = RpcServer.__new__(RpcServer)
    srv._h = object()
    return srv


def test_expect_error_catches_and_carries_the_error(_no_shim_calls):
    srv = _bare_server()
    with srv.expect_error() as info:
        raise _rpc_error(111)
    assert info.error is not None and info.error.code == 111


def test_expect_error_verifies_the_code(_no_shim_calls):
    srv = _bare_server()
    with srv.expect_error(111) as info:
        raise _rpc_error(111)
    assert info.error.code == 111


def test_expect_error_wrong_code_propagates(_no_shim_calls):
    from pyte.errors import RpcError
    srv = _bare_server()
    with pytest.raises(RpcError, match="remote failed"):
        with srv.expect_error(999):
            raise _rpc_error(111)


def test_expect_error_no_error_is_a_test_failure(_no_shim_calls):
    from pyte.errors import TestFail
    srv = _bare_server()
    with pytest.raises(TestFail, match="expected an RPC error"):
        with srv.expect_error():
            pass


def test_expect_error_stops_the_block_at_the_failure(_no_shim_calls):
    """The failing call raises: later block code must NOT run (the old
    suppression model let execution continue with Nones flowing)."""
    srv = _bare_server()
    ran_past = []
    with srv.expect_error():
        raise _rpc_error(1)
        ran_past.append(True)   # noqa: B012  unreachable by design
    assert ran_past == []


def test_check_call_always_raises_on_failure(_no_shim_calls, monkeypatch):
    """No suppression state: a failed predicate raises, full stop."""
    import sys
    import types
    from pyte.errors import RpcError

    class Lib:
        PYTE_ETIMEDOUT = 110

        def pyte_rpc_errno(self, h):
            return 111

        def pyte_rpc_err_msg(self, h):
            return b"boom"

        def pyte_rc_error(self, rc):
            return rc

        def pyte_rc_module(self, rc):
            return 0

        def te_rc_mod2str(self, rc):
            return b"RPC"

        def te_rc_err2str(self, rc):
            return b"E"

    class Ffi:
        @staticmethod
        def string(b):
            return b

    monkeypatch.setitem(sys.modules, "pyte._shim",
                        types.SimpleNamespace(ffi=Ffi(), lib=Lib()))
    srv = _bare_server()
    with pytest.raises(RpcError, match="boom"):
        srv._check_call(0, -1, lambda v: v >= 0, "call()")
    assert srv._check_call(0, 5, lambda v: v >= 0, "call()") == 5
