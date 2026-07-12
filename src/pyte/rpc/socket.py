# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""RPC sockets: pythonic facade over tapi_rpc_socket."""
from __future__ import annotations

import enum
from dataclasses import dataclass

from pyte.errors import check
from pyte.log import _enc


class Msg(enum.Flag):
    """MSG_* send/receive flags for the data-transfer methods.

    TE's RPC layer transports flags in its own ``rpc_send_recv_flags``
    encoding (te_rpc_sys_socket.h), which does NOT match the host's
    ``MSG_*`` values: e.g. host ``MSG_DONTWAIT`` is 0x40 while TE's is
    8, so passing ``socket.MSG_*`` integers would silently mean a
    different flag on the agent.  Members are translated to PYTE_MSG_*
    shim constants at the call boundary; plain ints are rejected.
    """

    OOB = enum.auto()
    PEEK = enum.auto()
    DONTROUTE = enum.auto()
    DONTWAIT = enum.auto()
    WAITALL = enum.auto()
    NOSIGNAL = enum.auto()
    TRUNC = enum.auto()
    CTRUNC = enum.auto()
    ERRQUEUE = enum.auto()
    MCAST = enum.auto()
    BCAST = enum.auto()
    MORE = enum.auto()
    CONFIRM = enum.auto()
    EOR = enum.auto()


#: Map from Msg member to the corresponding PYTE_MSG_* shim constant.
_MSG_CONSTS = {
    Msg.OOB:       "PYTE_MSG_OOB",
    Msg.PEEK:      "PYTE_MSG_PEEK",
    Msg.DONTROUTE: "PYTE_MSG_DONTROUTE",
    Msg.DONTWAIT:  "PYTE_MSG_DONTWAIT",
    Msg.WAITALL:   "PYTE_MSG_WAITALL",
    Msg.NOSIGNAL:  "PYTE_MSG_NOSIGNAL",
    Msg.TRUNC:     "PYTE_MSG_TRUNC",
    Msg.CTRUNC:    "PYTE_MSG_CTRUNC",
    Msg.ERRQUEUE:  "PYTE_MSG_ERRQUEUE",
    Msg.MCAST:     "PYTE_MSG_MCAST",
    Msg.BCAST:     "PYTE_MSG_BCAST",
    Msg.MORE:      "PYTE_MSG_MORE",
    Msg.CONFIRM:   "PYTE_MSG_CONFIRM",
    Msg.EOR:       "PYTE_MSG_EOR",
}

#: Lazy dict: Msg member -> TE RPC bit value (populated from the shim on
#: first use so unit tests with a fake shim can supply the values).
MSG_BITS: dict[Msg, int] = {}


def _ensure_msg_bits() -> None:
    """Populate MSG_BITS lazily from the shim constants."""
    if MSG_BITS:
        return
    from pyte._shim import lib
    for member, const in _MSG_CONSTS.items():
        MSG_BITS[member] = int(getattr(lib, const))


def _msg_bits(flags: "Msg") -> int:
    """Convert a :class:`Msg` flag into the TE RPC integer bit mask."""
    if not isinstance(flags, Msg):
        raise TypeError(
            "flags must be a Msg flag (host socket.MSG_* ints do not "
            f"match TE's RPC encoding), not {type(flags).__name__}")
    _ensure_msg_bits()
    bits = 0
    for member in flags:
        bits |= MSG_BITS[member]
    return bits


def _msg_flag(bits: int) -> "Msg":
    """Decode a TE RPC integer bit mask back into a :class:`Msg` flag."""
    _ensure_msg_bits()
    flag = Msg(0)
    for member, bit in MSG_BITS.items():
        if bits & bit:
            flag |= member
    return flag


@dataclass(frozen=True)
class RecvMsg:
    """Result of :meth:`RpcSocket.recvmsg`.

    ``ancillary`` is a list of ``(level, type, data)`` tuples where
    ``level`` and ``type`` are host-native integers (e.g. ``IPPROTO_IP``,
    ``IP_PKTINFO``) and ``data`` is a :class:`bytes` payload.  Only
    TE-known socket levels (SOL_SOCKET, IPPROTO_IP, IPPROTO_IPV6,
    IPPROTO_TCP, IPPROTO_UDP) and their known cmsg types survive the RPC
    conversion; unknown level/type values arrive mangled (rebuilt with
    SOL_MAX plus a WARN in the TE log).
    ``addr`` is ``(ip, port)`` when the kernel returned a source name,
    or ``None`` on a connected socket that reported no name.
    ``flags`` are the returned ``msg_flags`` decoded into :class:`Msg`
    (e.g. ``Msg.TRUNC in rm.flags``).
    """

    data: bytes
    ancillary: list[tuple[int, int, bytes]]
    addr: tuple[str, int] | None
    flags: "Msg"

# inet6/local need sockaddr helpers not yet implemented (_mk_addr and
# _parse_addr only handle AF_INET), so only inet is exposed for now.
class Family(enum.Enum):
    """Socket address family; value is the PYTE_PF_* shim constant name."""

    INET = "PYTE_PF_INET"


class SockType(enum.Enum):
    """Socket type; value is the PYTE_SOCK_* shim constant name."""

    STREAM = "PYTE_SOCK_STREAM"
    DGRAM = "PYTE_SOCK_DGRAM"


class SockOpt(enum.Enum):
    """Int-valued socket option for :meth:`RpcSocket.setsockopt`.

    Value is the PYTE_* shim constant name.  To support another option,
    add a PYTE_* constant passthrough to shim/pyte_shim.{h,cdef.h} (value =
    the matching RPC_* from te_rpc_sys_socket.h) and a member here;
    rpc_setsockopt_int() derives the level from the option itself.
    """

    SO_REUSEADDR = "PYTE_SO_REUSEADDR"
    SO_REUSEPORT = "PYTE_SO_REUSEPORT"
    SO_KEEPALIVE = "PYTE_SO_KEEPALIVE"
    SO_BROADCAST = "PYTE_SO_BROADCAST"
    SO_RCVBUF = "PYTE_SO_RCVBUF"
    SO_SNDBUF = "PYTE_SO_SNDBUF"
    SO_ERROR = "PYTE_SO_ERROR"
    # SO_INCOMING_NAPI_ID: NAPI ID of the last received packet; a
    # getsockopt() probe for kernel busy-poll support (read-only).
    SO_INCOMING_NAPI_ID = "PYTE_SO_INCOMING_NAPI_ID"
    TCP_NODELAY = "PYTE_TCP_NODELAY"
    # IP_PKTINFO: receive dest address + incoming iface index as ancillary
    # data (IPPROTO_IP / IP_PKTINFO cmsg). rpc_sockopt2level() derives the
    # level from the RPC option constant, so no explicit level is needed.
    IP_PKTINFO = "PYTE_IP_PKTINFO"


class Shut(enum.Enum):
    """shutdown() direction; value is the PYTE_SHUT_* shim constant name."""

    RD = "PYTE_SHUT_RD"
    WR = "PYTE_SHUT_WR"
    RDWR = "PYTE_SHUT_RDWR"


def _mk_addr(ffi, lib, addr: tuple[str, int]):
    """(ip, port) -> owning struct sockaddr_storage cdata.

    Returns the OWNER, not a cast pointer: in cffi a cast does not keep
    the owning cdata alive, so callers cast to ``struct sockaddr *`` at
    the call site, where the returned owner stays alive in a local for
    the duration of the C call.
    """
    ip, port = addr
    ss = ffi.new("struct sockaddr_storage *")
    sslen = ffi.new("socklen_t *")
    check(lib.pyte_sockaddr_in4(_enc(ip), port, ss, sslen),
          f"sockaddr({ip}, {port})")
    return ss


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
    def open(cls, server, family: Family = Family.INET,
             type: SockType = SockType.STREAM) -> "RpcSocket":
        if not isinstance(family, Family):
            raise TypeError(
                f"family must be a Family, not "
                f"{family.__class__.__name__}")
        if not isinstance(type, SockType):
            raise TypeError(
                f"type must be a SockType, not "
                f"{type.__class__.__name__}")
        from pyte._shim import ffi, lib
        out = ffi.new("int *")
        rc = lib.pyte_rpc_socket(server._h,
                                 getattr(lib, family.value),
                                 getattr(lib, type.value),
                                 lib.PYTE_PROTO_DEF, out)
        server._check_call(rc, out[0], lambda v: v >= 0,
                                 f"socket({family.name}, {type.name})")
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

    def setsockopt(self, opt: SockOpt, value: int) -> None:
        """Set an int-valued socket option, e.g.
        ``setsockopt(SockOpt.SO_REUSEADDR, 1)``.

        Only the options in :class:`SockOpt` are supported; see its
        docstring for how to extend the surface.
        """
        if not isinstance(opt, SockOpt):
            raise TypeError(
                f"opt must be a SockOpt, not {opt.__class__.__name__}")
        from pyte._shim import ffi, lib
        optname = getattr(lib, opt.value)
        out = ffi.new("int *")
        rc = lib.pyte_rpc_setsockopt_int(self.server._h, self.fd,
                                         optname, value, out)
        self.server._check_call(rc, out[0], lambda v: v == 0,
                                f"setsockopt({opt.name}, {value})")

    def bind(self, addr: tuple[str, int]) -> None:
        from pyte._shim import ffi, lib
        ss = _mk_addr(ffi, lib, addr)
        sa = ffi.cast("struct sockaddr *", ss)
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
        ss = _mk_addr(ffi, lib, addr)
        sa = ffi.cast("struct sockaddr *", ss)
        out = ffi.new("int *")
        rc = lib.pyte_rpc_connect(self.server._h, self.fd, sa, out)
        self.server._check_call(rc, out[0], lambda v: v == 0,
                                f"connect({addr})")

    def accept(self) -> "RpcSocket":
        from pyte._shim import ffi, lib
        ss = ffi.new("struct sockaddr_storage *")
        sslen = ffi.new("socklen_t *",
                        ffi.sizeof("struct sockaddr_storage"))
        out = ffi.new("int *")
        rc = lib.pyte_rpc_accept(self.server._h, self.fd,
                                 ffi.cast("struct sockaddr *", ss),
                                 sslen, out)
        self.server._check_call(rc, out[0], lambda v: v >= 0,
                                      "accept()")
        return RpcSocket(self.server, out[0])

    def getsockname(self) -> tuple[str, int]:
        from pyte._shim import ffi, lib
        ss = ffi.new("struct sockaddr_storage *")
        sslen = ffi.new("socklen_t *",
                        ffi.sizeof("struct sockaddr_storage"))
        sa = ffi.cast("struct sockaddr *", ss)
        out = ffi.new("int *")
        rc = lib.pyte_rpc_getsockname(self.server._h, self.fd, sa, sslen,
                                      out)
        self.server._check_call(rc, out[0], lambda v: v == 0,
                                      "getsockname()")
        return _parse_addr(ffi, lib, sa)

    def getpeername(self) -> tuple[str, int]:
        from pyte._shim import ffi, lib
        ss = ffi.new("struct sockaddr_storage *")
        sslen = ffi.new("socklen_t *",
                        ffi.sizeof("struct sockaddr_storage"))
        sa = ffi.cast("struct sockaddr *", ss)
        out = ffi.new("int *")
        rc = lib.pyte_rpc_getpeername(self.server._h, self.fd, sa, sslen,
                                      out)
        self.server._check_call(rc, out[0], lambda v: v == 0,
                                      "getpeername()")
        return _parse_addr(ffi, lib, sa)

    def getsockopt(self, opt: SockOpt) -> int:
        """Read an int-valued socket option."""
        if not isinstance(opt, SockOpt):
            raise TypeError(
                f"opt must be a SockOpt, not {opt.__class__.__name__}")
        from pyte._shim import ffi, lib
        val = ffi.new("int *")
        out = ffi.new("int *")
        rc = lib.pyte_rpc_getsockopt_int(self.server._h, self.fd,
                                         getattr(lib, opt.value), val, out)
        self.server._check_call(rc, out[0], lambda v: v == 0,
                                      f"getsockopt({opt.name})")
        return val[0]

    def shutdown(self, how: Shut = Shut.RDWR) -> None:
        """Shut down part or all of a full-duplex connection."""
        if not isinstance(how, Shut):
            raise TypeError(
                f"how must be a Shut, not {how.__class__.__name__}")
        from pyte._shim import ffi, lib
        out = ffi.new("int *")
        rc = lib.pyte_rpc_shutdown(self.server._h, self.fd,
                                   getattr(lib, how.value), out)
        self.server._check_call(rc, out[0], lambda v: v == 0,
                                f"shutdown({how.name})")

    def set_blocking(self, blocking: bool) -> None:
        """Set blocking (True) or non-blocking (False) mode (via fcntl)."""
        from pyte._shim import ffi, lib
        out = ffi.new("int *")
        rc = lib.pyte_sock_set_blocking(self.server._h, self.fd,
                                        1 if blocking else 0, out)
        self.server._check_call(rc, out[0], lambda v: v == 0,
                                f"set_blocking({blocking})")

    def get_blocking(self) -> bool:
        """Return True if the socket is in blocking mode."""
        from pyte._shim import ffi, lib
        blk = ffi.new("int *")
        out = ffi.new("int *")
        rc = lib.pyte_sock_get_blocking(self.server._h, self.fd, blk, out)
        self.server._check_call(rc, out[0], lambda v: v >= 0,
                                      "get_blocking()")
        return bool(blk[0])

    def send(self, data: bytes, flags: Msg = Msg(0)) -> int:
        bits = _msg_bits(flags)
        from pyte._shim import ffi, lib
        out = ffi.new("ssize_t *")
        rc = lib.pyte_rpc_send(self.server._h, self.fd, data, len(data),
                               bits, out)
        return self.server._check_call(rc, out[0], lambda v: v >= 0,
                                       f"send({len(data)} bytes)")

    def recv(self, size: int, flags: Msg = Msg(0)) -> bytes:
        bits = _msg_bits(flags)
        from pyte._shim import ffi, lib
        buf = ffi.new("uint8_t[]", size)
        out = ffi.new("ssize_t *")
        rc = lib.pyte_rpc_recv(self.server._h, self.fd, buf, size, bits,
                               out)
        self.server._check_call(rc, out[0], lambda v: v >= 0,
                                      f"recv({size})")
        return bytes(ffi.buffer(buf, out[0]))

    def sendto(self, data: bytes, addr: tuple[str, int],
               flags: Msg = Msg(0)) -> int:
        bits = _msg_bits(flags)
        from pyte._shim import ffi, lib
        ss = _mk_addr(ffi, lib, addr)
        sa = ffi.cast("struct sockaddr *", ss)
        out = ffi.new("ssize_t *")
        rc = lib.pyte_rpc_sendto(self.server._h, self.fd, data, len(data),
                                 bits, sa, out)
        return self.server._check_call(
            rc, out[0], lambda v: v >= 0,
            f"sendto({len(data)} bytes, {addr})")

    def recvfrom(self, size: int, flags: Msg = Msg(0),
                 ) -> tuple[bytes, tuple[str, int]]:
        bits = _msg_bits(flags)
        from pyte._shim import ffi, lib
        buf = ffi.new("uint8_t[]", size)
        ss = ffi.new("struct sockaddr_storage *")
        fromlen = ffi.new("socklen_t *",
                          ffi.sizeof("struct sockaddr_storage"))
        sa = ffi.cast("struct sockaddr *", ss)
        out = ffi.new("ssize_t *")
        rc = lib.pyte_rpc_recvfrom(self.server._h, self.fd, buf, size,
                                   bits, sa, fromlen, out)
        self.server._check_call(rc, out[0], lambda v: v >= 0,
                                      f"recvfrom({size})")
        return bytes(ffi.buffer(buf, out[0])), _parse_addr(ffi, lib, sa)

    def sendmsg(self, buffers, addr=None, ancillary=(),
                flags: Msg = Msg(0)):
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
        :param flags:     send flags (:class:`Msg`).
        :returns:         bytes sent.
        """
        bits = _msg_bits(flags)
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
            bits, sent)
        self.server._check_call(rc, sent[0], lambda v: v >= 0,
                                      f"sendmsg({n_iov} iov, {n_cmsg} cmsg)")
        return int(sent[0])

    def recvmsg(self, bufsize: int, ctrl_space: int = 0,
                flags: Msg = Msg(0)) -> "RecvMsg":
        """Receive a message with optional ancillary data.

        :param bufsize:    data buffer size in bytes.
        :param ctrl_space: bytes reserved for ancillary data (0 = none).
        :param flags:      receive flags (:class:`Msg`).
        :returns:          :class:`RecvMsg`.

        Ancillary data level/type values are host-native integers, but only
        TE-known socket levels (SOL_SOCKET, IPPROTO_IP, IPPROTO_IPV6,
        IPPROTO_TCP, IPPROTO_UDP) and their known cmsg types survive the
        RPC conversion; unknown values arrive mangled (SOL_MAX + WARN).
        """
        bits = _msg_bits(flags)
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
            self.server._h, self.fd, bufsize, ctrl_space, bits,
            p_data, p_data_len,
            p_from_addr, p_from_port,
            p_levels, p_types, p_datas, p_lens,
            p_n_cmsg, p_msg_flags, p_received)
        self.server._check_call(rc, p_received[0], lambda v: v >= 0,
                                      f"recvmsg({bufsize})")

        # Extract everything under try/finally: a failure mid-extraction
        # must not leak the shim's allocations.  The address decodes
        # with errors="replace", consistent with the rest of the package
        # (a strict decode here was the plausible leak trigger).
        try:
            data = bytes(ffi.buffer(p_data[0], p_data_len[0]))
            addr_str = ffi.string(p_from_addr[0]).decode(
                "utf-8", errors="replace")
            ancillary = [
                (int(p_levels[0][i]), int(p_types[0][i]),
                 bytes(ffi.buffer(p_datas[0][i], int(p_lens[0][i]))))
                for i in range(int(p_n_cmsg[0]))]
        finally:
            lib.pyte_free_string(ffi.cast("char *", p_data[0]))
            lib.pyte_free_string(p_from_addr[0])
            if int(p_n_cmsg[0]) > 0:
                lib.pyte_free_cmsgs(p_levels[0], p_types[0],
                                    p_datas[0], p_lens[0],
                                    int(p_n_cmsg[0]))

        addr = (addr_str, int(p_from_port[0])) if addr_str else None
        return RecvMsg(data=data, ancillary=ancillary, addr=addr,
                       flags=_msg_flag(int(p_msg_flags[0])))
