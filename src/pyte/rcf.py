# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""RCF direct API: agent inventory, file transfer, restart, dynamic TAs.

Usage:
    from pyte import rcf
    rcf.agents()                      # ["Agt_A"]
    a = rcf.agent("Agt_A")
    a.put_bytes(b"data", "/tmp/x")
    with rcf.add_agent("Agt_DYN") as dyn:   # extra agent on the engine host
        dyn.get_bytes("/etc/hostname")

restart() works only for agents NOT running on the engine host
(rcf_ta_reboot returns TE_EINVAL otherwise) that were added/configured
as rebootable (TE_EPERM otherwise).
"""
from __future__ import annotations

import os
import random
import tempfile
from dataclasses import dataclass

from pyte.errors import RcfError, check
from pyte.log import _enc


def _split_ta_list(block: bytes) -> list[str]:
    return [n.decode(errors="replace")
            for n in block.split(b"\x00") if n]


def _pick_port() -> int:
    """A random port for a dynamic agent, below the Linux ephemeral range.

    Picks from 20000–32000 to stay clear of the Linux ephemeral range
    (32768–60999) and the rigs' RCF ports (50000/51000).  Collisions are
    still possible and surface as slow add/connect failures; pass an
    explicit port to control it.
    """
    return random.randint(20000, 32000)


def _grow_loop(call, initial: int = 4096) -> bytes:
    """Double-until-fit buffer loop for shim calls that return ESMALLBUF.

    call(size) must return (rc, data_bytes | None): rc == 0 on success
    (data_bytes contains the result), ESMALLBUF to retry with double size,
    or any other rc to propagate as an error.  Raises RuntimeError if the
    buffer grows beyond 1 MiB (RCF misbehaving).
    """
    size = initial
    while True:
        if size > 1 << 20:
            raise RuntimeError(
                "rcf.agents(): TA list exceeds 1 MiB — RCF misbehaving?")
        rc, data = call(size)
        if rc == 0:
            return data
        if rc == "ESMALLBUF":
            size *= 2
        else:
            raise rc


def agents() -> list[str]:
    from pyte._shim import ffi, lib

    def _call(size):
        buf = ffi.new("char[]", size)
        ln = ffi.new("size_t *", size)
        rc = lib.pyte_rcf_ta_list(buf, ln)
        if rc == 0:
            return 0, bytes(ffi.buffer(buf, ln[0]))
        if lib.pyte_rc_error(rc) == lib.pyte_rc_error(lib.PYTE_ESMALLBUF):
            return "ESMALLBUF", None
        check(rc, "rcf.agents()", RcfError)

    return _split_ta_list(_grow_loop(_call))


@dataclass(frozen=True)
class AgentInfo:
    type: str
    rcflib: str
    confstr: str
    flags: int


class RcfAgent:
    """One test agent as seen by RCF."""

    def __init__(self, name: str):
        self.name = name

    # -- info -----------------------------------------------------------
    @property
    def type(self) -> str:
        from pyte._shim import ffi, lib
        buf = ffi.new("char[]", lib.PYTE_RCF_MAX_NAME)
        check(lib.pyte_rcf_ta_type(_enc(self.name), buf),
              f"rcf.type({self.name})", RcfError)
        return ffi.string(buf).decode(errors="replace")

    @property
    def info(self) -> AgentInfo:
        from pyte._shim import ffi, lib
        typ = ffi.new("char **")
        rcflib = ffi.new("char **")
        confstr = ffi.new("char **")
        flags = ffi.new("unsigned int *")
        check(lib.pyte_rcf_ta_info(_enc(self.name), typ, rcflib, confstr,
                                   flags),
              f"rcf.info({self.name})", RcfError)

        def take(p):
            if p[0] == ffi.NULL:
                return ""
            try:
                return ffi.string(p[0]).decode(errors="replace")
            finally:
                lib.pyte_free_string(p[0])
        return AgentInfo(take(typ), take(rcflib), take(confstr), flags[0])

    # -- files ------------------------------------------------------------
    def put_file(self, local: str, remote: str) -> None:
        from pyte._shim import lib
        check(lib.pyte_rcf_put_file(_enc(self.name), _enc(local),
                                    _enc(remote)),
              f"put_file({local} -> {self.name}:{remote})", RcfError)

    def get_file(self, remote: str, local: str) -> None:
        from pyte._shim import lib
        check(lib.pyte_rcf_get_file(_enc(self.name), _enc(remote),
                                    _enc(local)),
              f"get_file({self.name}:{remote} -> {local})", RcfError)

    def del_file(self, remote: str) -> None:
        from pyte._shim import lib
        check(lib.pyte_rcf_del_file(_enc(self.name), _enc(remote)),
              f"del_file({self.name}:{remote})", RcfError)

    def put_bytes(self, data: bytes, remote: str) -> None:
        fd, path = tempfile.mkstemp(prefix="pyte_rcf_")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            self.put_file(path, remote)
        finally:
            os.unlink(path)

    def get_bytes(self, remote: str) -> bytes:
        fd, path = tempfile.mkstemp(prefix="pyte_rcf_")
        os.close(fd)
        try:
            self.get_file(remote, path)
            with open(path, "rb") as f:
                return f.read()
        finally:
            os.unlink(path)

    # -- control ------------------------------------------------------------
    def restart(self, boot_params: str | None = None) -> None:
        """Restart the TA process (remote, rebootable agents only)."""
        from pyte._shim import ffi, lib
        check(lib.pyte_rcf_ta_restart(
                  _enc(self.name),
                  _enc(boot_params) if boot_params else ffi.NULL),
              f"restart({self.name})", RcfError)

    def flush_logs(self) -> None:
        """Ask the Logger to pump out this TA's accumulated log now."""
        from pyte._shim import lib
        check(lib.pyte_rcf_ta_flush_logs(_enc(self.name)),
              f"flush_logs({self.name})", RcfError)

    def __repr__(self):
        return f"<RcfAgent {self.name}>"


class DynamicAgent(RcfAgent):
    """An agent added at runtime; remove() tears it down (also a CM)."""

    def __init__(self, name: str):
        super().__init__(name)
        self._removed = False

    def remove(self) -> None:
        """Delete the agent from RCF (idempotent)."""
        from pyte._shim import lib
        if self._removed:
            return
        check(lib.pyte_rcf_del_ta(_enc(self.name)),
              f"del_ta({self.name})", RcfError)
        self._removed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self.remove()
        else:
            try:
                self.remove()
            except Exception as e:
                import pyte.log as _log
                _log.error(
                    f"rcf.remove failed during exception unwind: {e}")
        return False


def agent(name: str) -> RcfAgent:
    return RcfAgent(name)


def add_agent(name: str, host: str | None = None, type: str = "linux",
              port: int = 0, rebootable: bool = False) -> DynamicAgent:
    """Add a TA at runtime. host=None: start on the engine host (no ssh)."""
    from pyte._shim import lib
    flags = lib.PYTE_RCF_TA_REBOOTABLE if rebootable else 0
    check(lib.pyte_rcf_add_ta_unix(_enc(name), _enc(type),
                                   _enc(host) if host else b"",
                                   port or _pick_port(), flags),
          f"add_agent({name})", RcfError)
    return DynamicAgent(name)
