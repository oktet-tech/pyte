# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""RPC files: pythonic facade over tapi_rpc_unistd file calls."""
from __future__ import annotations

from pyte._cleanup import cleanup_all
from pyte._util import shim as _shim
from pyte._util import enc as _enc


class RpcFile:
    """A file descriptor living on an RPC server."""

    def __init__(self, server, fd: int, path: str):
        self.server = server
        self.fd = fd
        self.path = path

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        cleanup_all(self.close, primary=exc)
        return False

    def __repr__(self):
        return f"<RpcFile {self.path!r} fd={self.fd} on {self.server!r}>"

    def close(self) -> None:
        """Close the descriptor on the agent; idempotent.

        The fd is marked closed BEFORE the result is checked, so a
        failed close is not retried.  That is deliberate: retrying a
        close on a descriptor TE may already have released risks
        closing an unrelated fd the agent has since reused, which is
        worse than leaking one that the agent's own exit reclaims.
        """
        ffi, lib = _shim()
        if self.fd < 0:
            return
        out = ffi.new("int *")
        rc = lib.pyte_rpc_close(self.server._handle(), self.fd, out)
        self.fd = -1
        self.server._check_call(rc, out[0], lambda v: v == 0,
                                f"close({self.path})")

    def write(self, data: bytes) -> int:
        ffi, lib = _shim()
        out = ffi.new("int *")
        rc = lib.pyte_rpc_write(
            self.server._handle(), self.fd, data, len(data), out)
        return self.server._check_call(rc, out[0], lambda v: v >= 0,
                                       f"write({self.path}, "
                                       f"{len(data)} bytes)")

    def read(self, size: int) -> bytes:
        ffi, lib = _shim()
        buf = ffi.new("uint8_t[]", size)
        out = ffi.new("int *")
        rc = lib.pyte_rpc_read(self.server._handle(), self.fd, buf, size, out)
        self.server._check_call(rc, out[0], lambda v: v >= 0,
                                      f"read({self.path}, {size})")
        return bytes(ffi.buffer(buf, out[0]))


def open_file(server, path: str, mode: str = "r") -> RpcFile | None:
    """Open a file on the RPC server; mode is "r", "w" or "a"."""
    ffi, lib = _shim()
    flags = {
        "r": lib.PYTE_O_RDONLY,
        "w": lib.PYTE_O_WRONLY | lib.PYTE_O_CREAT | lib.PYTE_O_TRUNC,
        "a": lib.PYTE_O_WRONLY | lib.PYTE_O_CREAT | lib.PYTE_O_APPEND,
    }[mode]
    out = ffi.new("int *")
    rc = lib.pyte_rpc_open(server._handle(), _enc(path), flags,
                           lib.PYTE_MODE_0644, out)
    server._check_call(rc, out[0], lambda v: v >= 0,
                             f"open({path}, {mode!r})")
    return RpcFile(server, out[0], path)


def unlink(server, path: str) -> None:
    """Remove a file on the RPC server."""
    ffi, lib = _shim()
    out = ffi.new("int *")
    rc = lib.pyte_rpc_unlink(server._handle(), _enc(path), out)
    server._check_call(rc, out[0], lambda v: v == 0, f"unlink({path})")


#: Chunk size for file_put()/file_get() loops.
_CHUNK = 4096


def file_put(server, path: str, data: bytes) -> None:
    """Write data to a file on the RPC server (created or truncated).

    Convenience composition of open/write/close; writes in _CHUNK
    pieces and follows short writes.
    """
    with open_file(server, path, "w") as f:
        view = memoryview(data)
        while len(view) > 0:
            n = f.write(bytes(view[:_CHUNK]))
            if n == 0:
                raise RuntimeError(
                    f"file_put({path}): write() returned 0 with "
                    f"{len(view)} bytes left")
            view = view[n:]


def file_get(server, path: str) -> bytes:
    """Read a whole file from the RPC server.

    Convenience composition of open/read/close; loops in _CHUNK
    pieces until rpc_read() returns 0 (EOF).
    """
    chunks = []
    with open_file(server, path, "r") as f:
        while True:
            chunk = f.read(_CHUNK)
            if not chunk:
                break
            chunks.append(chunk)
    return b"".join(chunks)
