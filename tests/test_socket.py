# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""RpcSocket unit tests (type guards + fake-shim flag encoding)."""
import sys
import types

import pytest

from pyte.rpc import socket as sockmod
from pyte.rpc.socket import Family, Msg, RpcSocket, Shut, SockOpt, SockType


@pytest.fixture(autouse=True)
def _clear_msg_bits():
    """Prevent Msg bit values populated from one (fake/real) shim from
    bleeding into tests that use another — same pattern as iomux."""
    sockmod.MSG_BITS.clear()
    yield
    sockmod.MSG_BITS.clear()


def test_enum_values_map_to_shim_consts():
    assert Family.INET.value == "PYTE_PF_INET"
    assert SockType.STREAM.value == "PYTE_SOCK_STREAM"
    assert SockType.DGRAM.value == "PYTE_SOCK_DGRAM"
    assert SockOpt.SO_REUSEADDR.value == "PYTE_SO_REUSEADDR"
    assert SockOpt.IP_PKTINFO.value == "PYTE_IP_PKTINFO"


def test_open_rejects_non_enum():
    # Type guards run before any shim import, so no TE is needed.
    with pytest.raises(TypeError, match="family must be a Family"):
        RpcSocket.open(object(), family="inet")
    with pytest.raises(TypeError, match="type must be a SockType"):
        RpcSocket.open(object(), type="dgram")


def test_setsockopt_rejects_non_enum():
    sock = RpcSocket(object(), 5)
    with pytest.raises(TypeError, match="opt must be a SockOpt"):
        sock.setsockopt("SO_REUSEADDR", 1)


def test_new_enum_values():
    assert Shut.RD.value == "PYTE_SHUT_RD"
    assert Shut.RDWR.value == "PYTE_SHUT_RDWR"
    assert SockOpt.SO_RCVBUF.value == "PYTE_SO_RCVBUF"
    assert SockOpt.TCP_NODELAY.value == "PYTE_TCP_NODELAY"


def test_shutdown_rejects_non_enum():
    with pytest.raises(TypeError, match="how must be a Shut"):
        RpcSocket(object(), 5).shutdown("rdwr")


def test_getsockopt_rejects_non_enum():
    with pytest.raises(TypeError, match="opt must be a SockOpt"):
        RpcSocket(object(), 5).getsockopt("SO_ERROR")


# ---------------------------------------------------------------------------
# MSG_* flags: TE's RPC layer uses its own rpc_send_recv_flags encoding
# (te_rpc_sys_socket.h) which does NOT match host MSG_* values.  The Msg
# enum maps to PYTE_MSG_* shim constants; plain ints must be rejected --
# a host socket.MSG_DONTWAIT (0x40) would silently become TE's MSG_TRUNC.
# ---------------------------------------------------------------------------

class FakeServer:
    """Duck-typed RpcServer: records nothing, never suppresses."""
    _h = "srv-h"

    def _handle(self):
        return self._h

    def _check_call(self, rc, value, ok, where):
        return value


class FakeFfi:
    NULL = object()

    def new(self, spec, init=None):
        if spec.endswith("***") or spec.endswith("**"):
            return [None]
        if spec in ("size_t *", "int *", "unsigned int *", "ssize_t *",
                    "uint16_t *", "socklen_t *"):
            return [0 if init is None else init]
        if spec == "uint8_t[]":
            if isinstance(init, int):
                return bytearray(init)
            return bytes(init)
        raise NotImplementedError(f"FakeFfi.new({spec!r})")

    @staticmethod
    def buffer(data, length):
        return data[:length]

    @staticmethod
    def string(b):
        return b

    @staticmethod
    def cast(spec, val):
        return val


class FakeLib:
    """TE's real rpc_send_recv_flags encoding (te_rpc_sys_socket.h)."""

    PYTE_MSG_OOB       = 1
    PYTE_MSG_PEEK      = 2
    PYTE_MSG_DONTROUTE = 4
    PYTE_MSG_DONTWAIT  = 8
    PYTE_MSG_WAITALL   = 0x10
    PYTE_MSG_NOSIGNAL  = 0x20
    PYTE_MSG_TRUNC     = 0x40
    PYTE_MSG_CTRUNC    = 0x80
    PYTE_MSG_ERRQUEUE  = 0x100
    PYTE_MSG_MCAST     = 0x200
    PYTE_MSG_BCAST     = 0x400
    PYTE_MSG_MORE      = 0x800
    PYTE_MSG_CONFIRM   = 0x1000
    PYTE_MSG_EOR       = 0x2000

    def __init__(self):
        self.calls = []

    def pyte_rpc_send(self, srv, fd, data, length, flags, out):
        self.calls.append(("send", flags))
        out[0] = length
        return 0

    def pyte_rpc_recv(self, srv, fd, buf, size, flags, out):
        self.calls.append(("recv", flags))
        out[0] = 0
        return 0

    def pyte_rpc_recvmsg(self, srv, fd, bufsize, ctrl_space, flags,
                         p_data, p_data_len, p_from_addr, p_from_port,
                         p_levels, p_types, p_datas, p_lens,
                         p_n_cmsg, p_msg_flags, p_received):
        self.calls.append(("recvmsg", flags))
        p_data[0] = b"hello"
        p_data_len[0] = 5
        p_from_addr[0] = b""
        p_from_port[0] = 0
        p_n_cmsg[0] = 0
        p_msg_flags[0] = self.PYTE_MSG_TRUNC | self.PYTE_MSG_CTRUNC
        p_received[0] = 5
        return 0

    def pyte_free_string(self, p):
        pass


def _fake_shim(monkeypatch):
    lib = FakeLib()
    monkeypatch.setitem(sys.modules, "pyte._shim",
                        types.SimpleNamespace(ffi=FakeFfi(), lib=lib))
    return lib


def test_msg_members_map_to_shim_consts():
    assert sockmod._MSG_CONSTS[Msg.DONTWAIT] == "PYTE_MSG_DONTWAIT"
    assert sockmod._MSG_CONSTS[Msg.PEEK] == "PYTE_MSG_PEEK"
    assert sockmod._MSG_CONSTS[Msg.TRUNC] == "PYTE_MSG_TRUNC"
    assert set(sockmod._MSG_CONSTS) == set(Msg)


def test_send_encodes_msg_flags_via_shim(monkeypatch):
    """Msg members are translated to TE's RPC bits, not host MSG_*."""
    lib = _fake_shim(monkeypatch)
    sock = RpcSocket(FakeServer(), 5)

    sock.send(b"x", flags=Msg.DONTWAIT | Msg.PEEK)

    assert lib.calls == [("send", lib.PYTE_MSG_DONTWAIT | lib.PYTE_MSG_PEEK)]


def test_send_default_flags_are_zero(monkeypatch):
    lib = _fake_shim(monkeypatch)
    RpcSocket(FakeServer(), 5).send(b"x")
    assert lib.calls == [("send", 0)]


def test_send_rejects_plain_int_flags():
    """Host socket.MSG_* ints must not be silently misencoded."""
    import socket as stdlib_socket
    sock = RpcSocket(FakeServer(), 5)
    with pytest.raises(TypeError, match="Msg"):
        sock.send(b"x", flags=stdlib_socket.MSG_DONTWAIT)
    with pytest.raises(TypeError, match="Msg"):
        sock.recv(16, flags=1)


def test_recvmsg_decodes_flags_to_msg(monkeypatch):
    """RecvMsg.flags arrives in TE encoding and is decoded to Msg."""
    lib = _fake_shim(monkeypatch)
    sock = RpcSocket(FakeServer(), 5)

    rm = sock.recvmsg(16)

    assert lib.calls == [("recvmsg", 0)]
    assert rm.data == b"hello"
    assert isinstance(rm.flags, Msg)
    assert rm.flags == Msg.TRUNC | Msg.CTRUNC


def test_mk_addr_returns_owning_storage():
    """_mk_addr must return the owning cdata, not a cast pointer: a
    cffi cast does not keep the owner alive, so returning the cast
    made every future caller a use-after-free landmine."""
    sentinel = object()

    class Ffi:
        def new(self, spec, *a):
            if spec == "struct sockaddr_storage *":
                return sentinel
            return [0]

    class Lib:
        def pyte_sockaddr_in4(self, ip, port, ss, sslen):
            assert ss is sentinel
            return 0

    ss = sockmod._mk_addr(Ffi(), Lib(), ("192.0.2.1", 80))
    assert ss is sentinel
