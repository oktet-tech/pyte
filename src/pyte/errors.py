# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""TE error model: te_errno -> exceptions."""
from __future__ import annotations

import builtins


class TeError(Exception):
    """A TE API call failed with a te_errno status."""

    def __init__(self, rc: int, where: str = ""):
        from pyte._shim import ffi, lib
        self.rc = rc
        self.module = lib.pyte_rc_module(rc)
        self.code = lib.pyte_rc_error(rc)
        mod = ffi.string(lib.te_rc_mod2str(rc)).decode()
        err = ffi.string(lib.te_rc_err2str(rc)).decode()
        prefix = f"{where}: " if where else ""
        super().__init__(f"{prefix}{mod}-{err} (0x{rc:x})")


class CfgError(TeError):
    """Configurator request failed."""


class TrcError(TeError):
    """TRC database access failure."""

    def __init__(self, rc_or_msg, where: str = ""):
        if isinstance(rc_or_msg, str):  # non-errno path: plain message
            Exception.__init__(self, rc_or_msg)
            self.rc = 0
            self.module = 0
            self.code = 0
        else:
            super().__init__(rc_or_msg, where)


class EnvError(TeError):
    """tapi_env binding or lookup failed.

    Message-only when raised for a lookup miss (rc 0), or carries the
    te_errno of a failed bind (TrcError-style dual path).
    """

    def __init__(self, rc_or_msg, where: str = ""):
        if isinstance(rc_or_msg, str):
            Exception.__init__(self, rc_or_msg)
            self.rc = 0
            self.module = 0
            self.code = 0
        else:
            super().__init__(rc_or_msg, where)


class FioError(TeError):
    """fio subprocess failed or produced unreadable output.

    Message-only when raised for a failed exit or parse error (no
    te_errno behind it), like TrcError's string path.
    """

    def __init__(self, rc_or_msg, where: str = ""):
        if isinstance(rc_or_msg, str):  # non-errno path: plain message
            Exception.__init__(self, rc_or_msg)
            self.rc = 0
            self.module = 0
            self.code = 0
        else:
            super().__init__(rc_or_msg, where)


class PingError(TeError):
    """Raised when the ping tool fails or its output cannot be parsed."""

    def __init__(self, rc_or_msg, where: str = ""):
        if isinstance(rc_or_msg, str):  # non-errno path: plain message
            Exception.__init__(self, rc_or_msg)
            self.rc = 0
            self.module = 0
            self.code = 0
        else:
            super().__init__(rc_or_msg, where)


class IperfError(TeError):
    """Raised when iperf/iperf3 fails or its output cannot be parsed."""

    def __init__(self, rc_or_msg, where: str = ""):
        if isinstance(rc_or_msg, str):  # non-errno path: plain message
            Exception.__init__(self, rc_or_msg)
            self.rc = 0
            self.module = 0
            self.code = 0
        else:
            super().__init__(rc_or_msg, where)


class TrexError(TeError):
    """Raised when TRex (STL) fails or its output cannot be parsed."""

    def __init__(self, rc_or_msg, where: str = ""):
        if isinstance(rc_or_msg, str):  # non-errno path: plain message
            Exception.__init__(self, rc_or_msg)
            self.rc = 0
            self.module = 0
            self.code = 0
        else:
            super().__init__(rc_or_msg, where)


class WrkError(TeError):
    """Raised when wrk fails or its output cannot be parsed."""

    def __init__(self, rc_or_msg, where: str = ""):
        if isinstance(rc_or_msg, str):
            Exception.__init__(self, rc_or_msg)
            self.rc = 0
            self.module = 0
            self.code = 0
        else:
            super().__init__(rc_or_msg, where)


class NetperfError(TeError):
    """Raised when netperf/netserver fails or its output cannot be parsed."""

    def __init__(self, rc_or_msg, where: str = ""):
        if isinstance(rc_or_msg, str):
            Exception.__init__(self, rc_or_msg)
            self.rc = 0
            self.module = 0
            self.code = 0
        else:
            super().__init__(rc_or_msg, where)


class SfntError(TeError):
    """Raised when sfnt-pingpong fails or its output cannot be parsed."""

    def __init__(self, rc_or_msg, where: str = ""):
        if isinstance(rc_or_msg, str):
            Exception.__init__(self, rc_or_msg)
            self.rc = 0
            self.module = 0
            self.code = 0
        else:
            super().__init__(rc_or_msg, where)


class NptcpError(TeError):
    """Raised when NPtcp fails or its output cannot be parsed."""

    def __init__(self, rc_or_msg, where: str = ""):
        if isinstance(rc_or_msg, str):
            Exception.__init__(self, rc_or_msg)
            self.rc = 0
            self.module = 0
            self.code = 0
        else:
            super().__init__(rc_or_msg, where)


class MemcachedError(TeError):
    """Raised when memcached fails or mc-stats output cannot be parsed."""

    def __init__(self, rc_or_msg, where: str = ""):
        if isinstance(rc_or_msg, str):
            Exception.__init__(self, rc_or_msg)
            self.rc = 0
            self.module = 0
            self.code = 0
        else:
            super().__init__(rc_or_msg, where)


class MemaslapError(TeError):
    """Raised when memaslap fails or its output cannot be parsed."""

    def __init__(self, rc_or_msg, where: str = ""):
        if isinstance(rc_or_msg, str):
            Exception.__init__(self, rc_or_msg)
            self.rc = 0
            self.module = 0
            self.code = 0
        else:
            super().__init__(rc_or_msg, where)


class MemtierError(TeError):
    """Raised when memtier_benchmark fails or its output cannot be parsed."""

    def __init__(self, rc_or_msg, where: str = ""):
        if isinstance(rc_or_msg, str):
            Exception.__init__(self, rc_or_msg)
            self.rc = 0
            self.module = 0
            self.code = 0
        else:
            super().__init__(rc_or_msg, where)


class Mke2fsError(TeError):
    """Raised when mke2fs fails or the requested journal is missing."""

    def __init__(self, rc_or_msg, where: str = ""):
        if isinstance(rc_or_msg, str):
            Exception.__init__(self, rc_or_msg)
            self.rc = 0
            self.module = 0
            self.code = 0
        else:
            super().__init__(rc_or_msg, where)


class EthtoolError(TeError):
    """Raised when ethtool fails or its output cannot be parsed."""

    def __init__(self, rc_or_msg, where: str = ""):
        if isinstance(rc_or_msg, str):
            Exception.__init__(self, rc_or_msg)
            self.rc = 0
            self.module = 0
            self.code = 0
        else:
            super().__init__(rc_or_msg, where)


class SshError(TeError):
    """Raised when ssh/sshd fails."""

    def __init__(self, rc_or_msg, where: str = ""):
        if isinstance(rc_or_msg, str):
            Exception.__init__(self, rc_or_msg)
            self.rc = 0
            self.module = 0
            self.code = 0
        else:
            super().__init__(rc_or_msg, where)


class RcfError(TeError):
    """RCF request failed."""


class RpcError(TeError):
    """RPC call failed; carries the remote errno."""

    def __init__(self, rc: int, where: str = "", err_msg: str = ""):
        super().__init__(rc, where)
        self.err_msg = err_msg
        if err_msg:
            self.args = (f"{self.args[0]}: {err_msg}",)


class RemotePythonError(TeError):
    """pyte.remote: the runner died or remote code raised.

    Message-only (no te_errno behind it), like TrcError's string
    path; ``remote_traceback`` carries the agent-side traceback when
    the failure was a remote exception.
    """

    def __init__(self, msg: str, remote_traceback: str = ""):
        Exception.__init__(self, msg)
        self.rc = 0
        self.module = 0
        self.code = 0
        self.remote_traceback = remote_traceback


class TimeoutError(TeError, builtins.TimeoutError):
    """TE_ETIMEDOUT from a TE call (job receive, csap recv, ...)."""


class TestFail(Exception):
    """Raise (or call test.fail()) to fail the test with a message."""


class TestSkip(Exception):
    """Raise (or call test.skip()) to mark the test skipped."""


_ERRNO_NAMES = {"ECONNREFUSED", "ENOENT", "ENODATA", "EPERM"}


def __getattr__(name: str):
    """Expose TE error codes (errors.ECONNREFUSED, ...) lazily."""
    if name in _ERRNO_NAMES:
        from pyte._shim import lib
        return getattr(lib, f"PYTE_{name}")
    raise AttributeError(name)


def check(rc: int, where: str = "", cls: type[TeError] = TeError) -> None:
    """Raise if a te_errno status is non-zero.

    Timeouts always raise pyte.errors.TimeoutError regardless of cls.
    """
    if rc != 0:
        from pyte._shim import lib
        if lib.pyte_rc_error(rc) == lib.pyte_rc_error(lib.PYTE_ETIMEDOUT):
            raise TimeoutError(rc, where)
        raise cls(rc, where)
