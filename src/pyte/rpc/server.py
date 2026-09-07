# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""RPC servers: pythonic rcf_rpc_server handles."""
from __future__ import annotations

from contextlib import contextmanager

from pyte._cleanup import cleanup_all
from pyte._util import shim as _shim, shim_lib as _shim_lib
from pyte.errors import ClosedResourceError, RpcError, TestFail, check
from pyte._util import enc as _enc
from typing import TYPE_CHECKING

from pyte.rpc.iomux import Kind
from pyte.rpc.socket import Family, SockType

if TYPE_CHECKING:
    from pyte.rpc.iomux import IoMux
    from pyte.rpc.socket import RpcSocket

_HOSTNAME_MAX = 256


class ExpectedError:
    """Yielded by :meth:`RpcServer.expect_error`.

    After the block, ``error`` carries the caught :class:`RpcError`
    (its ``code`` is the TE error part of the remote errno).
    """

    def __init__(self):
        self.error = None


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
        self._silent_pass_depth = 0
        self._silent_pass_was = 0

    def _handle(self):
        """The live C handle; raises after destroy().

        pyte_shim passes handles straight into the rcf_rpc_* calls, so
        a NULL handle would crash the test process in C instead of
        raising.  Env-owned PCOs are the sharp case: tapi_env_free
        frees the server out from under any wrapper still holding it.
        """
        if self._h is None:
            raise ClosedResourceError(
                f"RPC server {self.ta}/{self.name} is already destroyed")
        return self._h

    @classmethod
    def create(cls, ta: str, name: str) -> "RpcServer":
        ffi, lib = _shim()
        out = ffi.new("rcf_rpc_server **")
        check(lib.pyte_rpc_server_create(_enc(ta), _enc(name), out),
              f"rpc_server_create({ta}, {name})", RpcError)
        return cls(out[0], ta, name)

    def destroy(self) -> None:
        """Destroy the RPC server; idempotent and retryable when owned.

        Env-provided PCOs are owned by tapi_env (tapi_env_free destroys
        them), so the wrapper must not call pyte_rpc_server_destroy for
        them.  That path clears the handle unconditionally: no call is
        made, and tapi_env_free will invalidate the pointer regardless,
        so a wrapper the caller believes is dead must not keep handing
        it to C.

        The owned path only clears the handle after
        pyte_rpc_server_destroy() succeeds: rcf_rpc.c returns early
        (without freeing the server) when the underlying
        cfg_del_instance_fmt() call fails, so a failure here leaves the
        C server live and the handle must stay usable for a retry.
        """
        if self._h is None:
            return
        if not self._owned:
            self._h = None
            return
        lib = _shim_lib()
        check(lib.pyte_rpc_server_destroy(self._h),
              f"rpc_server_destroy({self.name})", RpcError)
        self._h = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        cleanup_all(self.destroy, primary=exc)
        return False

    def __repr__(self):
        return f"<RpcServer {self.ta}/{self.name}>"

    # -- error plumbing used by all facades ---------------------------
    def _check_call(self, guard_rc: int, retval, ok, where: str,
                    output: str | None = None):
        """guard_rc: trampoline status; ok(retval): success predicate.

        A failed call always raises RpcError carrying the remote
        errno; there is no suppression state (expect_error() catches
        the exception instead).  ``output``, when given, is attached
        to the raised RpcError (see :attr:`RpcError.output`) -- used
        by :meth:`sh` to carry the command's captured stdout.
        """
        ffi, lib = _shim()
        check(guard_rc, where, RpcError)
        if ok(retval):
            return retval
        rpc_errno = lib.pyte_rpc_errno(self._handle())
        raise RpcError(
            rpc_errno, f"{where} -> {retval!r}",
            ffi.string(lib.pyte_rpc_err_msg(self._handle())).decode(
                errors="replace"),
            output=output)

    @contextmanager
    def expect_error(self, expected_errno: int | None = None):
        """Expect the RPC call in the block to fail (pytest.raises-style).

        Catches the :class:`RpcError` the failing call raises; when
        *expected_errno* is given (a TE error code, e.g.
        ``errors.ECONNREFUSED``) the caught error's ``code`` must
        match, otherwise the error propagates.  Execution of the
        block STOPS at the failing call — unlike the old suppression
        model, no ``None`` values flow through the rest of the block.
        Raises TestFail if the block completes without an RpcError.

        Yields an :class:`ExpectedError` whose ``error`` attribute
        carries the caught exception after the block::

            with pco.expect_error(errors.ECONNREFUSED) as info:
                sock.connect(("127.0.0.1", 1))
            log.ring(f"refused as expected: {info.error}")
        """
        info = ExpectedError()
        try:
            yield info
        except RpcError as e:
            if expected_errno is not None and e.code != expected_errno:
                raise
            info.error = e
            return
        raise TestFail("expected an RPC error, but the block succeeded")

    @contextmanager
    def silent_pass(self):
        """Suppress logging of job/filter RPCs *created* in this block.

        Sets ``rcf_rpc_server.silent_pass`` -- the same field the C
        TAPI's TRex driver flips around job creation
        (``proc->rpcs->silent_pass = true; tapi_trex_create(...);
        proc->rpcs->silent_pass = false;``, nap-trex.c:272-274). A
        successful call is not logged at all; a failing one is still
        logged at ERROR level -- that is what distinguishes
        ``silent_pass`` from the lower-level ``silent`` flag used
        internally by :class:`pyte.remote.RemoteObject` (which
        swallows errors too and is unsuitable for job creation, where
        a failure needs to be seen).

        IMPORTANT -- this only silences *creation*, not use:
        ``tapi_job_create()`` and ``tapi_job_attach_filter()`` bake the
        ambient ``silent_pass`` into the new job/channel/filter object;
        every later call that uses that object (:meth:`Filter.drain`,
        a second regexp added to the same filter, ...) re-asserts the
        object's CAPTURED flag for the duration of its own RPC and
        ignores whatever ``silent_pass`` happens to be live at that
        later point. So wrapping a later ``drain()``/``receive()``
        call in this context manager by itself does nothing -- the
        silence has to be baked in when the job/filter was created.
        Wrap :meth:`RpcServer.job` and the filters it attaches in this
        block and every future ``drain()`` on those filters is
        silenced for free. That baked-in silence is NOT limited to
        creation, though: ``job.start()``/``wait()``/``stop()``/
        ``kill()``/``destroy()`` (``rpc_job_{start,wait,stop,kill,
        destroy}``, ``te/lib/tapi_job/rpc_job.c:118,171,212``) each
        reassert ``rpcs->silent_pass = tapi_job_get_silent_pass(job)``
        around their own call, so a job born silent under this window
        stays silent for every later RPC made on it, lifecycle calls
        included, until something re-enables tracing on it.

        Nests correctly (the previous state is restored, not forced
        off) and restores on exception::

            with pco.silent_pass():
                job = pco.job(prog, args)
                flt = job.filter(stdout=True, regex=r"...")
            job.start()             # still silenced (baked in at creation)
            flt.drain()             # silenced (baked in at attach time)
        """
        lib = _shim_lib()
        h = self._handle()
        if self._silent_pass_depth == 0:
            self._silent_pass_was = lib.pyte_rpc_get_silent_pass(h)
            lib.pyte_rpc_set_silent_pass(h, 1)
        self._silent_pass_depth += 1
        try:
            yield self
        finally:
            self._silent_pass_depth -= 1
            if self._silent_pass_depth == 0:
                lib.pyte_rpc_set_silent_pass(h, self._silent_pass_was)

    # -- curated calls -------------------------------------------------
    def getpid(self) -> int:
        ffi, lib = _shim()
        out = ffi.new("int *")
        return self._check_call(
            lib.pyte_rpc_getpid(self._handle(), out), out[0],
            lambda v: v >= 0, "getpid()")

    def hostname(self) -> str:
        ffi, lib = _shim()
        buf = ffi.new("char[]", _HOSTNAME_MAX)
        out = ffi.new("int *")
        self._check_call(
            lib.pyte_rpc_gethostname(
                self._handle(), buf, _HOSTNAME_MAX - 1, out),
            out[0], lambda v: v == 0, "gethostname()")
        return ffi.string(buf).decode(errors="replace")

    def sh(self, cmd: str) -> str:
        """Run a shell command on the agent, return its stdout.

        On a non-zero exit, the captured output is decoded (before the
        C buffer is freed) and attached to the raised
        :class:`~pyte.errors.RpcError` as ``.output`` -- diagnostics a
        failing command printed are not lost (cf.
        ``subprocess.CalledProcessError.stdout``).
        """
        ffi, lib = _shim()
        pbuf = ffi.new("char **")
        flag = ffi.new("int *")
        value = ffi.new("int *")
        # ok-predicate: process exited (flag RPC_WAIT_STATUS_EXITED == 0)
        # with status 0.
        rc = lib.pyte_rpc_shell_get_all(self._handle(), pbuf, _enc(cmd), flag,
                                        value)
        try:
            output = "" if pbuf[0] == ffi.NULL \
                else ffi.string(pbuf[0]).decode(errors="replace")
            self._check_call(rc, (flag[0], value[0]),
                             lambda fv: fv == (0, 0),
                             f"sh({cmd!r})", output=output)
            return output
        finally:
            if pbuf[0] != ffi.NULL:
                lib.pyte_free_string(pbuf[0])

    def system(self, cmd: str, timeout: float | None = None) -> int:
        """Run cmd via a single rpc_system() call, return its exit status.

        A non-zero exit status is RETURNED, not raised — matching C
        rpc_system() semantics under RPC_AWAIT_IUT_ERROR, where callers
        inspect the wait status themselves.  RpcError is raised only
        when the RPC itself fails (e.g. times out) or the command did
        not exit normally (killed by a signal).

        ``timeout`` (seconds) raises the RPC timeout for this one call;
        because rpc_system() is a single RPC (unlike the multi-RPC
        :meth:`sh`), the timeout covers the whole command.  rcf_rpc
        resets the timeout to the default afterwards.
        """
        ffi, lib = _shim()
        if timeout is not None and timeout <= 0:
            raise ValueError("timeout must be > 0")
        flag = ffi.new("int *")
        value = ffi.new("int *")
        rc = lib.pyte_rpc_system(
            self._handle(), 0 if timeout is None else int(timeout * 1000),
            _enc(cmd), flag, value)
        # ok-predicate: process exited (flag RPC_WAIT_STATUS_EXITED
        # == 0); its exit status is reported via the return value.
        self._check_call(rc, (flag[0], value[0]),
                         lambda fv: fv[0] == 0,
                         f"system({cmd!r})")
        return value[0]

    def sleep(self, seconds: float) -> None:
        """Sleep on the agent side (a remote, not engine-side, delay).

        This TE has no rpc_sleep() RPC (checked tapi_rpc_unistd.h),
        so the delay runs as a remote shell ``sleep`` via
        :meth:`system` — a SINGLE rpc_system() call whose raised
        timeout provably covers the whole command.  (The multi-RPC
        :meth:`sh` would get the raised timeout only on its FIRST
        rpc; a sleep longer than the default RPC timeout could then
        fail spuriously.)
        """
        if seconds < 0:
            raise ValueError("seconds must be >= 0")
        status = self.system(f"sleep {seconds:g}", timeout=seconds + 10.0)
        if status != 0:
            from pyte.errors import RpcError
            raise RpcError(0, f"sleep({seconds:g}) exited with status "
                              f"{status}", "")

    def getenv(self, name: str) -> str | None:
        """Get an agent environment variable (None if unset)."""
        ffi, lib = _shim()
        out = ffi.new("char **")
        rc = lib.pyte_rpc_getenv(self._handle(), _enc(name), out)
        # rpc_getenv() returns NULL both for "unset" and "call
        # failed"; only the latter sets the remote errno.
        self._check_call(
            rc, out[0],
            lambda v: v != ffi.NULL or lib.pyte_rpc_errno(self._handle()) == 0,
            f"getenv({name})")
        if out[0] == ffi.NULL:
            return None
        try:
            return ffi.string(out[0]).decode(errors="replace")
        finally:
            lib.pyte_free_string(out[0])

    def setenv(self, name: str, value: str,
               overwrite: bool = True) -> None:
        """Set an agent environment variable."""
        ffi, lib = _shim()
        out = ffi.new("int *")
        rc = lib.pyte_rpc_setenv(self._handle(), _enc(name), _enc(value),
                                 1 if overwrite else 0, out)
        self._check_call(rc, out[0], lambda v: v == 0,
                         f"setenv({name}={value!r})")

    def socket(self, family: Family = Family.INET,
               type: SockType = SockType.STREAM) -> "RpcSocket":
        """Create an :class:`~pyte.rpc.socket.RpcSocket` on this server."""
        from pyte.rpc.socket import RpcSocket
        return RpcSocket.open(self, family, type)

    def iomux(self, kind: Kind = Kind.EPOLL) -> "IoMux":
        """Create an :class:`~pyte.rpc.iomux.IoMux` on this server.

        Returns an ``IoMux`` context manager that calls ``close()`` on
        exit.
        """
        from pyte.rpc.iomux import IoMux
        return IoMux.create(self, kind)

    def job(self, program: str, args: list[str] | None = None,
            env: dict[str, str] | None = None, stdin: bool = False):
        """Create a tapi_job running `program` on this RPC server.

        stdin=True allocates the input channel at creation (it must
        exist before start(); see Job.stdin).
        """
        from pyte.job import Job
        return Job.create(self, program, args or [], env, stdin=stdin)

    def run(self, program: str, args: list[str] | None = None,
            env: dict[str, str] | None = None,
            timeout: float | None = 10.0):
        """Run program to completion and capture its output.

        The subprocess.run() of tapi_job; returns a
        :class:`pyte.job.CompletedJob` (status + stdout + stderr, both
        streams also logged).  The default timeout is
        pyte.job.DEFAULT_TIMEOUT.
        """
        from pyte.job import run
        return run(self, program, args, env, timeout=timeout)

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
