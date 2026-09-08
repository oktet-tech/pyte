# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""TE error model: te_errno -> exceptions."""
from __future__ import annotations

from pyte._util import shim as _shim, shim_lib as _shim_lib

import builtins


class TeError(Exception):
    """A TE API call failed with a te_errno status."""

    def __init__(self, rc: int, where: str = ""):
        ffi, lib = _shim()
        self.rc = rc
        self.module = lib.pyte_rc_module(rc)
        self.code = lib.pyte_rc_error(rc)
        mod = ffi.string(lib.te_rc_mod2str(rc)).decode()
        err = ffi.string(lib.te_rc_err2str(rc)).decode()
        prefix = f"{where}: " if where else ""
        super().__init__(f"{prefix}{mod}-{err} (0x{rc:x})")


class _RcOrMsg:
    """Constructor mixin: accept a te_errno OR a plain message.

    ``Cls(rc, where)`` behaves like :class:`TeError`;
    ``Cls("message"[, where])`` raises with the plain (where-prefixed)
    message and rc/module/code of 0 — most tool/subsystem failures
    (bad exit status, unparseable output, lookup miss) have no
    te_errno behind them.
    """

    def __init__(self, rc_or_msg, where: str = ""):
        if isinstance(rc_or_msg, str):  # non-errno path: plain message
            Exception.__init__(
                self, f"{where}: {rc_or_msg}" if where else rc_or_msg)
            self.rc = 0
            self.module = 0
            self.code = 0
        else:
            super().__init__(rc_or_msg, where)


class CfgError(TeError):
    """Configurator request failed."""


class CfgNotFoundError(CfgError):
    """The OID does not exist (TE_ENOENT from the Configurator).

    Raised instead of the flat CfgError so callers can probe for
    absence without comparing hex rc codes.
    """


class TrcError(_RcOrMsg, TeError):
    """TRC database access failure."""


class EnvError(_RcOrMsg, TeError):
    """tapi_env binding or lookup failed.

    Message-only when raised for a lookup miss (rc 0), or carries the
    te_errno of a failed bind.
    """


class DpdkError(_RcOrMsg, TeError):
    """Preparing an agent for DPDK failed (pyte.dpdk).

    Message-only: a PCI lookup miss, an unreadable hugepage size, a
    kernel that cannot do what the mode needs.
    """


class NetError(_RcOrMsg, TeError):
    """A pyte.net operation did not reach the expected state.

    Message-only: the Configurator calls themselves succeeded, but
    what they reported is not what the caller waited for (a link that
    never came up, for instance).
    """


class ExpandError(_RcOrMsg, TeError):
    """Template expansion failed.

    Message-only (rc 0): an unresolved reference or an unsupported
    construct is found in the template text, not reported by TE.
    """


class ToolError(_RcOrMsg, TeError):
    """A pyte.tools wrapper failed: bad exit, unparseable output, ...

    The semantic base of every per-tool error, so ``except ToolError``
    catches any tool failure.  Subclasses add nothing but a docstring;
    the shared machinery (pyte.tools._tool) raises them through this
    class's dual-path constructor.
    """


class FioError(ToolError):
    """fio subprocess failed or produced unreadable output."""


class PingError(ToolError):
    """ping failed or its output cannot be parsed."""


class IperfError(ToolError):
    """iperf/iperf3 failed or its output cannot be parsed."""


class TrexError(ToolError):
    """TRex (STL) failed or its output cannot be parsed."""


class TrexBatchError(ToolError):
    """TRex batch (ASTF) run failed or its output cannot be parsed."""


class WrkError(ToolError):
    """wrk failed or its output cannot be parsed."""


class NetperfError(ToolError):
    """netperf/netserver failed or its output cannot be parsed."""


class SfntError(ToolError):
    """sfnt-pingpong failed or its output cannot be parsed."""


class NptcpError(ToolError):
    """NPtcp failed or its output cannot be parsed."""


class MemcachedError(ToolError):
    """memcached failed or mc-stats output cannot be parsed."""


class MemaslapError(ToolError):
    """memaslap failed or its output cannot be parsed."""


class MemtierError(ToolError):
    """memtier_benchmark failed or its output cannot be parsed."""


class Mke2fsError(ToolError):
    """mke2fs failed or the requested journal is missing."""


class EthtoolError(ToolError):
    """ethtool failed or its output cannot be parsed."""


class SshError(ToolError):
    """ssh/sshd failed."""


class RcfError(TeError):
    """RCF request failed."""


class RpcError(TeError):
    """RPC call failed; carries the remote errno.

    ``output``, when given, is the decoded stdout of the command whose
    failure raised this error (cf.
    ``subprocess.CalledProcessError.stdout``) -- e.g.
    :meth:`~pyte.rpc.server.RpcServer.sh` attaches its captured output
    here on a non-zero exit instead of losing it.  ``None`` (the
    default) for RPC failures with no associated command output.
    """

    _OUTPUT_EXCERPT = 200

    def __init__(self, rc: int, where: str = "", err_msg: str = "",
                 output: str | None = None):
        super().__init__(rc, where)
        self.err_msg = err_msg
        self.output = output
        if err_msg:
            self.args = (f"{self.args[0]}: {err_msg}",)
        if output:
            excerpt = output if len(output) <= self._OUTPUT_EXCERPT \
                else "..." + output[-self._OUTPUT_EXCERPT:]
            self.args = (f"{self.args[0]} (output: {excerpt!r})",)


class RemotePythonError(TeError):
    """pyte.remote: the runner died or remote code raised.

    Message-only (no te_errno behind it), like TrcError's string
    path; ``remote_traceback`` carries the agent-side traceback when
    the failure was a remote exception.

    The traceback is in that attribute and NOT in the message, which
    stays a single line: callers wrap the message into their own
    (``raise TrexError(f"... {exc}") from exc``), so a multi-line one
    would be copied into every verdict and artifact along the way.
    :func:`pyte._util.remote_tracebacks` recovers the frames from an
    exception chain where the failure is finally reported.
    """

    def __init__(self, msg: str, remote_traceback: str = ""):
        Exception.__init__(self, msg)
        self.rc = 0
        self.module = 0
        self.code = 0
        self.remote_traceback = remote_traceback


class ClosedResourceError(TeError, RuntimeError):
    """Operation on a resource that has already been closed.

    One idiom for what used to be nine copy-pasted guards raising two
    unrelated types.  Subclasses RuntimeError so the call sites that
    raised it keep working, and TeError so ``except TeError`` covers a
    closed-handle failure like any other pyte error.

    Message-only: TeError.__init__ reaches the shim on every
    construction, and a liveness guard must be raisable without one.
    """

    def __init__(self, msg: str):
        Exception.__init__(self, msg)
        self.rc = 0
        self.module = 0
        self.code = 0


class TrcClosedError(ClosedResourceError, TrcError):
    """A TRC database (or a view onto it) used after it was closed.

    trc.py raised a plain TrcError here and trc-tool catches that, so
    the unified error stays a TrcError as well as a
    ClosedResourceError.
    """


class TimeoutError(TeError, builtins.TimeoutError):
    """TE_ETIMEDOUT from a TE call (job receive, csap recv, ...)."""


class TestFail(Exception):
    """Raise (or call test.fail()) to fail the test with a message."""


class TestSkip(Exception):
    """Raise (or call test.skip()) to mark the test skipped."""


def __getattr__(name: str):
    """Expose TE error codes (errors.ECONNREFUSED, ...) lazily.

    Any ALL-CAPS ``E*`` name is forwarded to the shim's ``PYTE_<name>``
    constant, so the symbolic surface grows with the shim instead of a
    hand-curated allowlist (errors.ETIMEDOUT used to raise
    AttributeError while PYTE_ETIMEDOUT existed).
    """
    if name.startswith("E") and name.isupper():
        lib = _shim_lib()
        try:
            return getattr(lib, f"PYTE_{name}")
        except AttributeError:
            pass
    raise AttributeError(name)


def __dir__() -> list[str]:
    """Module contents plus the shim's errno constants (discoverable)."""
    names = set(globals())
    try:
        lib = _shim_lib()
        names.update(n[len("PYTE_"):] for n in dir(lib)
                     if n.startswith("PYTE_E"))
    except Exception:  # noqa: BLE001  shim absent: plain module dir
        pass
    return sorted(names)


def check(rc: int, where: str = "", cls: type[TeError] = TeError) -> None:
    """Raise if a te_errno status is non-zero.

    Timeouts always raise pyte.errors.TimeoutError regardless of cls.
    """
    if rc != 0:
        lib = _shim_lib()
        if lib.pyte_rc_error(rc) == lib.pyte_rc_error(lib.PYTE_ETIMEDOUT):
            raise TimeoutError(rc, where)
        if (issubclass(cls, CfgError)
                and lib.pyte_rc_error(rc) ==
                lib.pyte_rc_error(lib.PYTE_ENOENT)):
            raise CfgNotFoundError(rc, where)
        raise cls(rc, where)
