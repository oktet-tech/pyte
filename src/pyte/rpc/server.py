# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""RPC servers: pythonic rcf_rpc_server handles."""
from __future__ import annotations

from contextlib import contextmanager

from pyte.errors import RpcError, TestFail, check
from pyte.log import _enc

#: Returned by facade calls whose failure was swallowed by expect_error().
SUPPRESSED = object()

_HOSTNAME_MAX = 256


class RpcServer:
    """An RPC server (process) on a test agent.

    Operates in awaiting-error mode: failed calls raise RpcError
    instead of longjmp'ing like the C TAPI does.
    """

    def __init__(self, handle, ta: str, name: str, owned: bool = True):
        self._h = handle
        self.ta = ta
        self.name = name
        self._owned = owned
        self._expected: int | None = None
        self._expected_hit = False

    @classmethod
    def create(cls, ta: str, name: str) -> "RpcServer":
        from pyte._shim import ffi, lib
        out = ffi.new("rcf_rpc_server **")
        check(lib.pyte_rpc_server_create(_enc(ta), _enc(name), out),
              f"rpc_server_create({ta}, {name})", RpcError)
        return cls(out[0], ta, name)

    def destroy(self) -> None:
        """Destroy the RPC server.

        Env-provided PCOs are owned by tapi_env (tapi_env_free destroys
        them); the wrapper must not call pyte_rpc_server_destroy for them.
        When ``owned=False`` this method returns immediately without
        touching the shim or clearing the handle.
        """
        if not self._owned:
            return
        from pyte._shim import lib
        if self._h is not None:
            check(lib.pyte_rpc_server_destroy(self._h),
                  f"rpc_server_destroy({self.name})", RpcError)
            self._h = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.destroy()
        return False

    def __repr__(self):
        return f"<RpcServer {self.ta}/{self.name}>"

    # -- error plumbing used by all facades ---------------------------
    def _check_call(self, guard_rc: int, retval, ok, where: str):
        """guard_rc: trampoline status; ok(retval): success predicate."""
        from pyte._shim import ffi, lib
        check(guard_rc, where, RpcError)
        failed = not ok(retval)
        if not failed:
            return retval
        rpc_errno = lib.pyte_rpc_errno(self._h)
        if self._expected is not None:
            if (self._expected == 0 or
                    lib.pyte_rc_error(rpc_errno) == self._expected):
                self._expected_hit = True
                return SUPPRESSED
        raise RpcError(
            rpc_errno, f"{where} -> {retval!r}",
            ffi.string(lib.pyte_rpc_err_msg(self._h)).decode(
                errors="replace"))

    @contextmanager
    def expect_error(self, expected_errno: int = 0):
        """Assert that an RPC call inside the block fails.

        expected_errno: TE error code to require (0 = any error).
        Raises TestFail if the block completes without a failure.
        Facade calls whose failure is swallowed return None (or
        SUPPRESSED for raw _check_call users).
        """
        prev, prev_hit = self._expected, self._expected_hit
        self._expected = expected_errno
        self._expected_hit = False
        try:
            yield self
            hit = self._expected_hit
        finally:
            self._expected, self._expected_hit = prev, prev_hit
        if not hit:
            raise TestFail("expected an RPC error, but calls succeeded")

    # -- curated calls -------------------------------------------------
    def getpid(self) -> int | None:
        from pyte._shim import ffi, lib
        out = ffi.new("int *")
        ret = self._check_call(lib.pyte_rpc_getpid(self._h, out), out[0],
                               lambda v: v >= 0, "getpid()")
        if ret is SUPPRESSED:
            return None
        return ret

    def hostname(self) -> str | None:
        from pyte._shim import ffi, lib
        buf = ffi.new("char[]", _HOSTNAME_MAX)
        out = ffi.new("int *")
        ret = self._check_call(
            lib.pyte_rpc_gethostname(self._h, buf, _HOSTNAME_MAX - 1, out),
            out[0], lambda v: v == 0, "gethostname()")
        if ret is SUPPRESSED:
            return None
        return ffi.string(buf).decode(errors="replace")

    def sh(self, cmd: str) -> str:
        """Run a shell command on the agent, return its stdout."""
        from pyte._shim import ffi, lib
        pbuf = ffi.new("char **")
        flag = ffi.new("int *")
        value = ffi.new("int *")
        # ok-predicate: process exited (flag RPC_WAIT_STATUS_EXITED == 0)
        # with status 0.
        rc = lib.pyte_rpc_shell_get_all(self._h, pbuf, _enc(cmd), flag,
                                        value)
        try:
            ret = self._check_call(rc, (flag[0], value[0]),
                                   lambda fv: fv == (0, 0),
                                   f"sh({cmd!r})")
            if ret is SUPPRESSED or pbuf[0] == ffi.NULL:
                return ""
            return ffi.string(pbuf[0]).decode(errors="replace")
        finally:
            if pbuf[0] != ffi.NULL:
                lib.pyte_free_string(pbuf[0])

    def sleep(self, seconds: float) -> None:
        """Sleep on the agent side (a remote, not engine-side, delay).

        This TE has no rpc_sleep() RPC (checked tapi_rpc_unistd.h),
        so the delay runs as a remote shell ``sleep``.  The RPC
        timeout is raised for this one call to cover the sleep;
        rcf_rpc resets it to the default afterwards (rpcs->timeout
        is per-call).
        """
        from pyte._shim import lib
        if seconds < 0:
            raise ValueError("seconds must be >= 0")
        lib.pyte_rpc_set_timeout(self._h, int(seconds * 1000) + 10000)
        self.sh(f"sleep {seconds:g}")

    def getenv(self, name: str) -> str | None:
        """Get an agent environment variable (None if unset)."""
        from pyte._shim import ffi, lib
        out = ffi.new("char **")
        rc = lib.pyte_rpc_getenv(self._h, _enc(name), out)
        # rpc_getenv() returns NULL both for "unset" and "call
        # failed"; only the latter sets the remote errno.
        ret = self._check_call(
            rc, out[0],
            lambda v: v != ffi.NULL or lib.pyte_rpc_errno(self._h) == 0,
            f"getenv({name})")
        if ret is SUPPRESSED or out[0] == ffi.NULL:
            return None
        try:
            return ffi.string(out[0]).decode(errors="replace")
        finally:
            lib.pyte_free_string(out[0])

    def setenv(self, name: str, value: str,
               overwrite: bool = True) -> None:
        """Set an agent environment variable."""
        from pyte._shim import ffi, lib
        out = ffi.new("int *")
        rc = lib.pyte_rpc_setenv(self._h, _enc(name), _enc(value),
                                 1 if overwrite else 0, out)
        self._check_call(rc, out[0], lambda v: v == 0,
                         f"setenv({name}={value!r})")

    def socket(self, family="inet", type="stream"):
        from pyte.rpc.socket import RpcSocket
        return RpcSocket.open(self, family, type)

    def iomux(self, kind=None):
        """Create an :class:`~pyte.rpc.iomux.IoMux` on this server.

        *kind* is a :class:`~pyte.rpc.iomux.Kind` (default ``Kind.EPOLL``).
        Returns an ``IoMux`` context manager that calls ``close()`` on exit.
        """
        from pyte.rpc.iomux import IoMux, Kind
        return IoMux.create(self, kind if kind is not None else Kind.EPOLL)

    def job(self, program: str, args: list[str] | None = None,
            env: dict[str, str] | None = None):
        """Create a tapi_job running `program` on this RPC server."""
        from pyte.job import Job
        return Job.create(self, program, args or [], env)

    def open(self, path: str, mode: str = "r"):
        from pyte.rpc.files import open_file
        return open_file(self, path, mode)

    def unlink(self, path: str) -> None:
        from pyte.rpc.files import unlink
        unlink(self, path)

    def file_put(self, path: str, data: bytes) -> None:
        from pyte.rpc.files import file_put
        file_put(self, path, data)

    def file_get(self, path: str) -> bytes:
        from pyte.rpc.files import file_get
        return file_get(self, path)
