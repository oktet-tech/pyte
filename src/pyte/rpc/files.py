# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""RPC files: pythonic facade over tapi_rpc_unistd file calls."""
from __future__ import annotations

from pyte.log import _enc
from pyte.rpc.server import SUPPRESSED


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

    def write(self, data: bytes) -> int | None:
        from pyte._shim import ffi, lib
        out = ffi.new("int *")
        rc = lib.pyte_rpc_write(self.server._h, self.fd, data, len(data),
                                out)
        ret = self.server._check_call(rc, out[0], lambda v: v >= 0,
                                      f"write({self.path}, "
                                      f"{len(data)} bytes)")
        if ret is SUPPRESSED:
            return None
        return ret

    def read(self, size: int) -> bytes | None:
        from pyte._shim import ffi, lib
        buf = ffi.new("uint8_t[]", size)
        out = ffi.new("int *")
        rc = lib.pyte_rpc_read(self.server._h, self.fd, buf, size, out)
        ret = self.server._check_call(rc, out[0], lambda v: v >= 0,
                                      f"read({self.path}, {size})")
        if ret is SUPPRESSED:
            return None
        return bytes(ffi.buffer(buf, out[0]))


def open_file(server, path: str, mode: str = "r") -> RpcFile | None:
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
    ret = server._check_call(rc, out[0], lambda v: v >= 0,
                             f"open({path}, {mode!r})")
    if ret is SUPPRESSED:
        return None
    return RpcFile(server, out[0], path)


def unlink(server, path: str) -> None:
    """Remove a file on the RPC server."""
    from pyte._shim import ffi, lib
    out = ffi.new("int *")
    rc = lib.pyte_rpc_unlink(server._h, _enc(path), out)
    server._check_call(rc, out[0], lambda v: v == 0, f"unlink({path})")


#: Chunk size for file_put()/file_get() loops.
_CHUNK = 4096


def file_put(server, path: str, data: bytes) -> None:
    """Write data to a file on the RPC server (created or truncated).

    Convenience composition of open/write/close; writes in _CHUNK
    pieces and follows short writes.  Inside expect_error() a
    suppressed failure aborts the transfer silently.
    """
    f = open_file(server, path, "w")
    if f is None:
        return
    with f:
        view = memoryview(data)
        while len(view) > 0:
            n = f.write(bytes(view[:_CHUNK]))
            if n is None:
                return
            if n == 0:
                raise RuntimeError(
                    f"file_put({path}): write() returned 0 with "
                    f"{len(view)} bytes left")
            view = view[n:]


def file_get(server, path: str) -> bytes:
    """Read a whole file from the RPC server.

    Convenience composition of open/read/close; loops in _CHUNK
    pieces until rpc_read() returns 0 (EOF).  Inside expect_error()
    a suppressed failure yields the data read so far (b"" if the
    open itself failed).
    """
    f = open_file(server, path, "r")
    if f is None:
        return b""
    chunks = []
    with f:
        while True:
            chunk = f.read(_CHUNK)
            if not chunk:
                break
            chunks.append(chunk)
    return b"".join(chunks)
