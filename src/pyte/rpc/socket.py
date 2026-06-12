# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""RPC sockets: pythonic facade over tapi_rpc_socket."""
from __future__ import annotations

from dataclasses import dataclass

from pyte.errors import check
from pyte.log import _enc
from pyte.rpc.server import SUPPRESSED


@dataclass(frozen=True)
class RecvMsg:
    """Result of :meth:`RpcSocket.recvmsg`.

    ``ancillary`` is a list of ``(level, type, data)`` tuples where
    ``level`` and ``type`` are host-native integers (e.g. ``IPPROTO_IP``,
    ``IP_PKTINFO``) and ``data`` is a :class:`bytes` payload.  Only
    TE-known socket levels (SOL_SOCKET, IPPROTO_IP, IPPROTO_IPV6,
    IPPROTO_TCP, IPPROTO_UDP) and their known cmsg types survive the RPC
    conversion; unknown level/type values are dropped silently.
    ``addr`` is ``(ip, port)`` when the kernel returned a source name,
    or ``None`` on a connected socket that reported no name.
    """

    data: bytes
    ancillary: list[tuple[int, int, bytes]]
    addr: tuple[str, int] | None
    flags: int

# inet6/local need sockaddr helpers not yet implemented (_mk_addr and
# _parse_addr only handle AF_INET), so only inet is exposed for now.
_FAMILIES = {
    "inet": "PYTE_PF_INET",
}
_TYPES = {
    "stream": "PYTE_SOCK_STREAM",
    "dgram": "PYTE_SOCK_DGRAM",
}
# Minimal int-valued setsockopt surface.  To support another option,
# add a PYTE_SO_* constant passthrough to shim/pyte_shim.{h,cdef.h}
# (value = the matching RPC_SO_* from te_rpc_sys_socket.h) and a row
# here; rpc_setsockopt_int() derives the level from the option itself.
_SOCKOPTS = {
    "SO_REUSEADDR": "PYTE_SO_REUSEADDR",
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
             type: str = "stream") -> "RpcSocket | None":
        from pyte._shim import ffi, lib
        out = ffi.new("int *")
        rc = lib.pyte_rpc_socket(server._h,
                                 getattr(lib, _FAMILIES[family]),
                                 getattr(lib, _TYPES[type]),
                                 lib.PYTE_PROTO_DEF, out)
        ret = server._check_call(rc, out[0], lambda v: v >= 0,
                                 f"socket({family}, {type})")
        if ret is SUPPRESSED:
            return None
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

    def setsockopt(self, opt: str, value: int) -> None:
        """Set an int-valued socket option, e.g. ("SO_REUSEADDR", 1).

        Only the options listed in ``_SOCKOPTS`` are supported; see
        the comment there for how to extend the surface.
        """
        from pyte._shim import ffi, lib
        try:
            optname = getattr(lib, _SOCKOPTS[opt])
        except KeyError:
            raise ValueError(
                f"unsupported socket option {opt!r}") from None
        out = ffi.new("int *")
        rc = lib.pyte_rpc_setsockopt_int(self.server._h, self.fd,
                                         optname, value, out)
        self.server._check_call(rc, out[0], lambda v: v == 0,
                                f"setsockopt({opt}, {value})")

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

    def sendmsg(self, buffers, addr=None, ancillary=(), flags=0):
        """Send a scatter-gather message with optional ancillary data.

        :param buffers:   non-empty list of :class:`bytes` payloads.
        :param addr:      ``(ip, port)`` destination, or ``None`` for a
                          connected socket.
        :param ancillary: iterable of ``(level, type, data)`` cmsg triplets
                          where *level* and *type* are host-native ints and
                          *data* is :class:`bytes`.  Only TE-known socket
                          levels (SOL_SOCKET, IPPROTO_IP, IPPROTO_IPV6,
                          IPPROTO_TCP, IPPROTO_UDP) and their known cmsg
                          types are forwarded; unknown values are silently
                          dropped by the RPC layer.
        :param flags:     send flags (native int).
        :returns:         bytes sent, or ``None`` when error was suppressed.
        """
        from pyte._shim import ffi, lib

        buffers = list(buffers)
        if not buffers:
            raise ValueError(
                "sendmsg requires a non-empty list of buffers")

        ancillary = list(ancillary)
        for idx, item in enumerate(ancillary):
            if (not isinstance(item, (tuple, list)) or len(item) != 3
                    or not isinstance(item[2], (bytes, bytearray))):
                raise ValueError(
                    "ancillary items must be (int, int, bytes) triplets; "
                    f"got {item!r}")
            if not isinstance(item[0], int):
                raise ValueError(
                    f"ancillary[{idx}] level must be int, "
                    f"got {type(item[0]).__name__!r}")
            if not isinstance(item[1], int):
                raise ValueError(
                    f"ancillary[{idx}] type must be int, "
                    f"got {type(item[1]).__name__!r}")

        n_iov = len(buffers)
        # cffi array of pointers to iov data and corresponding lengths
        iov_bufs = [ffi.new("uint8_t[]", b) for b in buffers]
        iov_lens_arr = ffi.new("size_t[]", [len(b) for b in buffers])
        iov_ptrs = ffi.new("const uint8_t *[]", iov_bufs)

        # address
        if addr is not None:
            ip, port = addr
            addr_bytes = _enc(ip)
        else:
            addr_bytes = ffi.cast("char *", ffi.NULL)
            port = 0

        # control messages
        n_cmsg = len(ancillary)
        if n_cmsg:
            c_levels = ffi.new("int[]", [a[0] for a in ancillary])
            c_types = ffi.new("int[]", [a[1] for a in ancillary])
            c_data_bufs = [ffi.new("uint8_t[]", bytes(a[2]))
                           for a in ancillary]
            c_data_ptrs = ffi.new("const uint8_t *[]", c_data_bufs)
            c_lens = ffi.new("size_t[]", [len(a[2]) for a in ancillary])
        else:
            c_levels = ffi.cast("int *", ffi.NULL)
            c_types = ffi.cast("int *", ffi.NULL)
            c_data_ptrs = ffi.cast("const uint8_t **", ffi.NULL)
            c_lens = ffi.cast("size_t *", ffi.NULL)

        sent = ffi.new("ssize_t *")
        rc = lib.pyte_rpc_sendmsg(
            self.server._h, self.fd,
            iov_ptrs, iov_lens_arr, n_iov,
            addr_bytes, port,
            c_levels, c_types, c_data_ptrs, c_lens, n_cmsg,
            flags, sent)
        ret = self.server._check_call(rc, sent[0], lambda v: v >= 0,
                                      f"sendmsg({n_iov} iov, {n_cmsg} cmsg)")
        if ret is SUPPRESSED:
            return None
        return int(sent[0])

    def recvmsg(self, bufsize: int, ctrl_space: int = 0,
                flags: int = 0) -> "RecvMsg | None":
        """Receive a message with optional ancillary data.

        :param bufsize:    data buffer size in bytes.
        :param ctrl_space: bytes reserved for ancillary data (0 = none).
        :param flags:      receive flags (native int).
        :returns:          :class:`RecvMsg` or ``None`` when suppressed.

        Ancillary data level/type values are host-native integers, but only
        TE-known socket levels (SOL_SOCKET, IPPROTO_IP, IPPROTO_IPV6,
        IPPROTO_TCP, IPPROTO_UDP) and their known cmsg types survive the
        RPC conversion; unknown values are dropped silently by the RPC layer.
        """
        from pyte._shim import ffi, lib

        p_data = ffi.new("uint8_t **")
        p_data_len = ffi.new("size_t *")
        p_from_addr = ffi.new("char **")
        p_from_port = ffi.new("int *")
        p_levels = ffi.new("int **")
        p_types = ffi.new("int **")
        p_datas = ffi.new("uint8_t ***")
        p_lens = ffi.new("size_t **")
        p_n_cmsg = ffi.new("unsigned int *")
        p_msg_flags = ffi.new("int *")
        p_received = ffi.new("ssize_t *")

        rc = lib.pyte_rpc_recvmsg(
            self.server._h, self.fd, bufsize, ctrl_space, flags,
            p_data, p_data_len,
            p_from_addr, p_from_port,
            p_levels, p_types, p_datas, p_lens,
            p_n_cmsg, p_msg_flags, p_received)
        ret = self.server._check_call(rc, p_received[0], lambda v: v >= 0,
                                      f"recvmsg({bufsize})")
        if ret is SUPPRESSED:
            return None

        # extract received data
        data = bytes(ffi.buffer(p_data[0], p_data_len[0]))
        lib.pyte_free_string(ffi.cast("char *", p_data[0]))

        # extract source address
        addr_str = ffi.string(p_from_addr[0]).decode()
        lib.pyte_free_string(p_from_addr[0])
        if addr_str:
            addr = (addr_str, int(p_from_port[0]))
        else:
            addr = None

        # extract control messages
        n = int(p_n_cmsg[0])
        ancillary = []
        if n > 0:
            for i in range(n):
                lvl = int(p_levels[0][i])
                typ = int(p_types[0][i])
                dlen = int(p_lens[0][i])
                dat = bytes(ffi.buffer(p_datas[0][i], dlen))
                ancillary.append((lvl, typ, dat))
            lib.pyte_free_cmsgs(p_levels[0], p_types[0],
                                p_datas[0], p_lens[0], n)

        return RecvMsg(data=data, ancillary=ancillary, addr=addr,
                       flags=int(p_msg_flags[0]))
