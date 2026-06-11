# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""RPC sockets: pythonic facade over tapi_rpc_socket."""
from __future__ import annotations

from pyte.errors import check
from pyte.log import _enc
from pyte.rpc.server import SUPPRESSED

# inet6/local need sockaddr helpers not yet implemented (_mk_addr and
# _parse_addr only handle AF_INET), so only inet is exposed for now.
_FAMILIES = {
    "inet": "PYTE_PF_INET",
}
_TYPES = {
    "stream": "PYTE_SOCK_STREAM",
    "dgram": "PYTE_SOCK_DGRAM",
}


def _mk_addr(ffi, lib, addr: tuple[str, int]):
    """(ip, port) -> (struct sockaddr *, keepalive storage)."""
    ip, port = addr
    ss = ffi.new("struct sockaddr_storage *")
    sslen = ffi.new("socklen_t *")
    check(lib.pyte_sockaddr_in4(_enc(ip), port, ss, sslen),
          f"sockaddr({ip}, {port})")
    return ffi.cast("struct sockaddr *", ss), ss


def _parse_addr(ffi, lib, sa) -> tuple[str, int]:
    """struct sockaddr * -> (ip, port)."""
    ipbuf = ffi.new("char[64]")
    port = ffi.new("uint16_t *")
    check(lib.pyte_sockaddr_parse(sa, ipbuf, 64, port), "sockaddr_parse")
    return ffi.string(ipbuf).decode(), port[0]


class RpcSocket:
    """A socket living on an RPC server."""

    def __init__(self, server, fd: int):
        self.server = server
        self.fd = fd

    @classmethod
    def open(cls, server, family: str = "inet",
             type: str = "stream") -> "RpcSocket":
        from pyte._shim import ffi, lib
        out = ffi.new("int *")
        rc = lib.pyte_rpc_socket(server._h,
                                 getattr(lib, _FAMILIES[family]),
                                 getattr(lib, _TYPES[type]),
                                 lib.PYTE_PROTO_DEF, out)
        server._check_call(rc, out[0], lambda v: v >= 0,
                           f"socket({family}, {type})")
        return cls(server, out[0])

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    def __repr__(self):
        return f"<RpcSocket fd={self.fd} on {self.server!r}>"

    def close(self) -> None:
        from pyte._shim import ffi, lib
        if self.fd < 0:
            return
        out = ffi.new("int *")
        rc = lib.pyte_rpc_close(self.server._h, self.fd, out)
        self.fd = -1
        self.server._check_call(rc, out[0], lambda v: v == 0, "close()")

    def bind(self, addr: tuple[str, int]) -> None:
        from pyte._shim import ffi, lib
        sa, _keep = _mk_addr(ffi, lib, addr)
        out = ffi.new("int *")
        rc = lib.pyte_rpc_bind(self.server._h, self.fd, sa, out)
        self.server._check_call(rc, out[0], lambda v: v == 0,
                                f"bind({addr})")

    def listen(self, backlog: int = 5) -> None:
        from pyte._shim import ffi, lib
        out = ffi.new("int *")
        rc = lib.pyte_rpc_listen(self.server._h, self.fd, backlog, out)
        self.server._check_call(rc, out[0], lambda v: v == 0,
                                f"listen({backlog})")

    def connect(self, addr: tuple[str, int]) -> None:
        from pyte._shim import ffi, lib
        sa, _keep = _mk_addr(ffi, lib, addr)
        out = ffi.new("int *")
        rc = lib.pyte_rpc_connect(self.server._h, self.fd, sa, out)
        self.server._check_call(rc, out[0], lambda v: v == 0,
                                f"connect({addr})")

    def accept(self) -> "RpcSocket | None":
        from pyte._shim import ffi, lib
        ss = ffi.new("struct sockaddr_storage *")
        sslen = ffi.new("socklen_t *",
                        ffi.sizeof("struct sockaddr_storage"))
        out = ffi.new("int *")
        rc = lib.pyte_rpc_accept(self.server._h, self.fd,
                                 ffi.cast("struct sockaddr *", ss),
                                 sslen, out)
        ret = self.server._check_call(rc, out[0], lambda v: v >= 0,
                                      "accept()")
        if ret is SUPPRESSED:
            return None
        return RpcSocket(self.server, out[0])

    def getsockname(self) -> tuple[str, int] | None:
        from pyte._shim import ffi, lib
        ss = ffi.new("struct sockaddr_storage *")
        sslen = ffi.new("socklen_t *",
                        ffi.sizeof("struct sockaddr_storage"))
        sa = ffi.cast("struct sockaddr *", ss)
        out = ffi.new("int *")
        rc = lib.pyte_rpc_getsockname(self.server._h, self.fd, sa, sslen,
                                      out)
        ret = self.server._check_call(rc, out[0], lambda v: v == 0,
                                      "getsockname()")
        if ret is SUPPRESSED:
            return None
        return _parse_addr(ffi, lib, sa)

    def send(self, data: bytes, flags: int = 0) -> int | None:
        from pyte._shim import ffi, lib
        out = ffi.new("ssize_t *")
        rc = lib.pyte_rpc_send(self.server._h, self.fd, data, len(data),
                               flags, out)
        ret = self.server._check_call(rc, out[0], lambda v: v >= 0,
                                      f"send({len(data)} bytes)")
        if ret is SUPPRESSED:
            return None
        return ret

    def recv(self, size: int, flags: int = 0) -> bytes | None:
        from pyte._shim import ffi, lib
        buf = ffi.new("uint8_t[]", size)
        out = ffi.new("ssize_t *")
        rc = lib.pyte_rpc_recv(self.server._h, self.fd, buf, size, flags,
                               out)
        ret = self.server._check_call(rc, out[0], lambda v: v >= 0,
                                      f"recv({size})")
        if ret is SUPPRESSED:
            return None
        return bytes(ffi.buffer(buf, out[0]))

    def sendto(self, data: bytes, addr: tuple[str, int],
               flags: int = 0) -> int | None:
        from pyte._shim import ffi, lib
        sa, _keep = _mk_addr(ffi, lib, addr)
        out = ffi.new("ssize_t *")
        rc = lib.pyte_rpc_sendto(self.server._h, self.fd, data, len(data),
                                 flags, sa, out)
        ret = self.server._check_call(rc, out[0], lambda v: v >= 0,
                                      f"sendto({len(data)} bytes, {addr})")
        if ret is SUPPRESSED:
            return None
        return ret

    def recvfrom(self, size: int,
                 flags: int = 0) -> tuple[bytes, tuple[str, int]] | None:
        from pyte._shim import ffi, lib
        buf = ffi.new("uint8_t[]", size)
        ss = ffi.new("struct sockaddr_storage *")
        fromlen = ffi.new("socklen_t *",
                          ffi.sizeof("struct sockaddr_storage"))
        sa = ffi.cast("struct sockaddr *", ss)
        out = ffi.new("ssize_t *")
        rc = lib.pyte_rpc_recvfrom(self.server._h, self.fd, buf, size,
                                   flags, sa, fromlen, out)
        ret = self.server._check_call(rc, out[0], lambda v: v >= 0,
                                      f"recvfrom({size})")
        if ret is SUPPRESSED:
            return None
        return bytes(ffi.buffer(buf, out[0])), _parse_addr(ffi, lib, sa)
