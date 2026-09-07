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
    srv._silent_pass_depth = 0
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


# -- sh(): output capture on non-zero exit ------------------------------

class _ShLib:
    """Fake shim lib for RpcServer.sh(): scripted exit status/output."""

    PYTE_ETIMEDOUT = 110

    def __init__(self, output: bytes | None, flag: int, value: int):
        self._output = output
        self._flag = flag
        self._value = value
        self.freed = []

    def pyte_rpc_shell_get_all(self, h, pbuf, cmd, flag, value):
        pbuf[0] = self._output if self._output is not None else _ShFfi.NULL
        flag[0] = self._flag
        value[0] = self._value
        return 0

    def pyte_free_string(self, p):
        self.freed.append(p)

    def pyte_rpc_errno(self, h):
        return 111

    def pyte_rpc_err_msg(self, h):
        return b"remote failed"

    def pyte_rc_error(self, rc):
        return rc

    def pyte_rc_module(self, rc):
        return 0

    def te_rc_mod2str(self, rc):
        return b"RPC"

    def te_rc_err2str(self, rc):
        return b"E"


class _ShFfi:
    NULL = object()

    def new(self, spec):
        return [self.NULL if spec == "char **" else 0]

    @staticmethod
    def string(b):
        return b


def _fake_sh_shim(monkeypatch, output, flag=1, value=1):
    lib = _ShLib(output, flag, value)
    monkeypatch.setitem(sys.modules, "pyte._shim",
                        types.SimpleNamespace(ffi=_ShFfi(), lib=lib))
    return lib


def test_sh_success_returns_decoded_output(monkeypatch):
    _fake_sh_shim(monkeypatch, b"hello\n", flag=0, value=0)
    srv = _bare_server()
    assert srv.sh("echo hello") == "hello\n"


def test_sh_failure_attaches_decoded_output(monkeypatch):
    from pyte.errors import RpcError
    lib = _fake_sh_shim(monkeypatch, b"boom output\n", flag=0, value=1)
    srv = _bare_server()
    with pytest.raises(RpcError) as ei:
        srv.sh("false")
    assert ei.value.output == "boom output\n"
    # buffer is still freed on the failure path -- no leak
    assert lib.freed == [b"boom output\n"]


def test_sh_failure_message_includes_output_excerpt(monkeypatch):
    from pyte.errors import RpcError
    _fake_sh_shim(monkeypatch, b"boom output\n", flag=0, value=1)
    srv = _bare_server()
    with pytest.raises(RpcError, match="boom output"):
        srv.sh("false")


def test_sh_failure_with_no_output_has_output_none_or_empty(monkeypatch):
    from pyte.errors import RpcError
    _fake_sh_shim(monkeypatch, None, flag=0, value=1)
    srv = _bare_server()
    with pytest.raises(RpcError) as ei:
        srv.sh("false")
    assert ei.value.output == ""


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


# -- silent_pass: rcf_rpc_server.silent_pass toggle CM -------------------

class _SilentPassLib:
    """Fake shim lib recording every pyte_rpc_set_silent_pass(h, on) call."""

    def __init__(self):
        self.calls: list[int] = []

    def pyte_rpc_set_silent_pass(self, h, on):
        self.calls.append(on)


def _fake_silent_pass_shim(monkeypatch):
    lib = _SilentPassLib()
    monkeypatch.setitem(sys.modules, "pyte._shim",
                        types.SimpleNamespace(ffi=object(), lib=lib))
    return lib


def test_silent_pass_sets_and_restores(monkeypatch):
    lib = _fake_silent_pass_shim(monkeypatch)
    srv = _bare_server()
    with srv.silent_pass():
        assert lib.calls == [1]
    assert lib.calls == [1, 0]
    assert srv._silent_pass_depth == 0


def test_silent_pass_nests_without_toggling_in_between(monkeypatch):
    lib = _fake_silent_pass_shim(monkeypatch)
    srv = _bare_server()
    with srv.silent_pass():
        with srv.silent_pass():
            assert lib.calls == [1]     # only the OUTER on() call
        assert lib.calls == [1]         # inner exit did NOT turn it off
    assert lib.calls == [1, 0]          # outer exit turns it off once
    assert srv._silent_pass_depth == 0


def test_silent_pass_restores_on_exception(monkeypatch):
    lib = _fake_silent_pass_shim(monkeypatch)
    srv = _bare_server()
    with pytest.raises(ValueError, match="boom"):
        with srv.silent_pass():
            raise ValueError("boom")
    assert lib.calls == [1, 0]
    assert srv._silent_pass_depth == 0


def test_silent_pass_nested_restores_on_exception_from_inner_block(
        monkeypatch):
    lib = _fake_silent_pass_shim(monkeypatch)
    srv = _bare_server()
    with pytest.raises(ValueError, match="boom"):
        with srv.silent_pass():
            with srv.silent_pass():
                raise ValueError("boom")
    assert lib.calls == [1, 0]
    assert srv._silent_pass_depth == 0


class _LifecycleLib:
    """Fake shim for the RpcServer destroy/getpid lifecycle."""

    PYTE_ETIMEDOUT = 110

    def __init__(self):
        self.calls = []
        self.destroy_rc = 0

    def pyte_rpc_server_destroy(self, h):
        self.calls.append(("destroy", h))
        return self.destroy_rc

    def pyte_rpc_getpid(self, h, out):
        self.calls.append(("getpid", h))
        out[0] = 4242
        return 0

    def pyte_rc_error(self, rc):
        return rc

    def pyte_rc_module(self, rc):
        return 0

    def te_rc_mod2str(self, rc):
        return b"RPC"

    def te_rc_err2str(self, rc):
        return b"E"


class _LifecycleFfi:
    NULL = object()

    def new(self, spec):
        return [0]

    @staticmethod
    def string(b):
        return b


def _fake_lifecycle_shim(monkeypatch):
    lib = _LifecycleLib()
    monkeypatch.setitem(
        sys.modules, "pyte._shim",
        types.SimpleNamespace(ffi=_LifecycleFfi(), lib=lib))
    return lib


def test_destroyed_server_raises_instead_of_passing_null(monkeypatch):
    from pyte.errors import ClosedResourceError
    _fake_lifecycle_shim(monkeypatch)
    srv = RpcServer(object(), "Agt", "pco")
    srv.destroy()
    with pytest.raises(ClosedResourceError, match="pco"):
        srv.getpid()


def test_unowned_destroy_clears_the_handle(monkeypatch):
    """tapi_env_free will free this pointer; the wrapper must stop
    handing it to C just because destroy() is a no-op for env PCOs."""
    from pyte.errors import ClosedResourceError
    lib = _fake_lifecycle_shim(monkeypatch)
    srv = RpcServer(object(), "Agt", "iut_rpcs", owned=False)
    srv.destroy()
    assert srv._h is None
    assert not any(c[0] == "destroy" for c in lib.calls)
    with pytest.raises(ClosedResourceError):
        srv.getpid()


def test_destroy_is_idempotent(monkeypatch):
    lib = _fake_lifecycle_shim(monkeypatch)
    srv = RpcServer(object(), "Agt", "pco")
    srv.destroy()
    srv.destroy()
    assert len([c for c in lib.calls if c[0] == "destroy"]) == 1


def test_owned_destroy_retries_after_failure(monkeypatch):
    """A failing pyte_rpc_server_destroy() means rcf_rpc.c returned
    early (its cfg_del_instance_fmt() call failed) without freeing the
    server: the handle must stay usable so a later destroy() call can
    retry and actually free it, instead of leaking the C server."""
    from pyte.errors import RpcError
    lib = _fake_lifecycle_shim(monkeypatch)
    lib.destroy_rc = 12
    srv = RpcServer(object(), "Agt", "pco")

    with pytest.raises(RpcError):
        srv.destroy()
    assert srv._h is not None, "must stay live: the C server was not freed"
    lib.calls.clear()

    lib.destroy_rc = 0
    srv.destroy()   # retry succeeds

    assert len([c for c in lib.calls if c[0] == "destroy"]) == 1
    assert srv._h is None
