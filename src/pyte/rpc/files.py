# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""RPC files: pythonic facade over tapi_rpc_unistd file calls."""
from __future__ import annotations

from pyte.log import _enc


class RpcFile:
    """A file descriptor living on an RPC server."""

    def __init__(self, server, fd: int, path: str):
        self.server = server
        self.fd = fd
        self.path = path

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    def __repr__(self):
        return f"<RpcFile {self.path!r} fd={self.fd} on {self.server!r}>"

    def close(self) -> None:
        from pyte._shim import ffi, lib
        if self.fd < 0:
            return
        out = ffi.new("int *")
        rc = lib.pyte_rpc_close(self.server._h, self.fd, out)
        self.fd = -1
        self.server._check_call(rc, out[0], lambda v: v == 0,
                                f"close({self.path})")

    def write(self, data: bytes) -> int:
        from pyte._shim import ffi, lib
        out = ffi.new("int *")
        rc = lib.pyte_rpc_write(self.server._h, self.fd, data, len(data),
                                out)
        return self.server._check_call(rc, out[0], lambda v: v >= 0,
                                       f"write({self.path}, "
                                       f"{len(data)} bytes)")

    def read(self, size: int) -> bytes:
        from pyte._shim import ffi, lib
        buf = ffi.new("uint8_t[]", size)
        out = ffi.new("int *")
        rc = lib.pyte_rpc_read(self.server._h, self.fd, buf, size, out)
        self.server._check_call(rc, out[0], lambda v: v >= 0,
                                f"read({self.path}, {size})")
        return bytes(ffi.buffer(buf, out[0]))


def open_file(server, path: str, mode: str = "r") -> RpcFile:
    """Open a file on the RPC server; mode is "r", "w" or "a"."""
    from pyte._shim import ffi, lib
    flags = {
        "r": lib.PYTE_O_RDONLY,
        "w": lib.PYTE_O_WRONLY | lib.PYTE_O_CREAT | lib.PYTE_O_TRUNC,
        "a": lib.PYTE_O_WRONLY | lib.PYTE_O_CREAT | lib.PYTE_O_APPEND,
    }[mode]
    out = ffi.new("int *")
    rc = lib.pyte_rpc_open(server._h, _enc(path), flags,
                           lib.PYTE_MODE_0644, out)
    server._check_call(rc, out[0], lambda v: v >= 0,
                       f"open({path}, {mode!r})")
    return RpcFile(server, out[0], path)


def unlink(server, path: str) -> None:
    """Remove a file on the RPC server."""
    from pyte._shim import ffi, lib
    out = ffi.new("int *")
    rc = lib.pyte_rpc_unlink(server._h, _enc(path), out)
    server._check_call(rc, out[0], lambda v: v == 0, f"unlink({path})")
