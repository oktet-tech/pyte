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


class RpcError(TeError):
    """RPC call failed; carries the remote errno."""

    def __init__(self, rc: int, where: str = "", err_msg: str = ""):
        super().__init__(rc, where)
        self.err_msg = err_msg
        if err_msg:
            self.args = (f"{self.args[0]}: {err_msg}",)


class TimeoutError(TeError, builtins.TimeoutError):
    """TE_ETIMEDOUT from a TE call (job receive, csap recv, ...)."""


class TestFail(Exception):
    """Raise (or call test.fail()) to fail the test with a message."""


class TestSkip(Exception):
    """Raise (or call test.skip()) to mark the test skipped."""


_ERRNO_NAMES = {"ECONNREFUSED", "ENOENT"}


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
