# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""sendmsg/recvmsg unit tests with a fake shim.

The fake shim intercepts pyte_rpc_sendmsg / pyte_rpc_recvmsg and records
what was passed so the tests can verify marshalling without a real TE install.
FakeFfi mimics the cffi API surface used by socket.py, returning plain Python
objects that the FakeLib can inspect.
"""
import sys
import types

import pytest

from pyte.rpc import socket as sockmod
from pyte.rpc.socket import Msg, RecvMsg, RpcSocket


@pytest.fixture(autouse=True)
def _clear_msg_bits():
    """Msg bit values are populated lazily from whichever shim is first
    imported; clear around each test so fake/real shims don't bleed."""
    sockmod.MSG_BITS.clear()
    yield
    sockmod.MSG_BITS.clear()


# ---------------------------------------------------------------------------
# Fake cffi / shim infrastructure
# ---------------------------------------------------------------------------

class _FfiBuf:
    """Mutable byte buffer (ffi.new("uint8_t[]", data))."""

    def __init__(self, data: bytes):
        self._data = bytearray(data)

    def __getitem__(self, idx):
        return self._data[idx]

    def __setitem__(self, idx, val):
        self._data[idx] = val

    def __bytes__(self):
        return bytes(self._data)

    def __len__(self):
        return len(self._data)


class _FfiPtrArray:
    """Array of pointers (ffi.new("const uint8_t *[]", list_of_bufs))."""

    def __init__(self, items):
        self._items = list(items)

    def __getitem__(self, idx):
        return self._items[idx]

    def __len__(self):
        return len(self._items)


class _FfiIntArray:
    """Array of ints (ffi.new("int[]", list_of_ints))."""

    def __init__(self, values):
        self._values = list(values)

    def __getitem__(self, idx):
        return self._values[idx]

    def __setitem__(self, idx, val):
        self._values[idx] = val

    def __len__(self):
        return len(self._values)


class _FfiSizeArray:
    """Array of size_t (ffi.new("size_t[]", list))."""

    def __init__(self, values):
        self._values = list(values)

    def __getitem__(self, idx):
        return self._values[idx]

    def __setitem__(self, idx, val):
        self._values[idx] = val

    def __len__(self):
        return len(self._values)


class _FfiOutPtr:
    """Single-element mutable out-parameter (ffi.new("T *"))."""

    def __init__(self, initial=None):
        self._v = initial

    def __getitem__(self, idx):
        return self._v

    def __setitem__(self, idx, val):
        self._v = val


class _FfiNull:
    pass


class FakeFfi:
    NULL = _FfiNull()

    def new(self, ctype, *args):
        # ffi.new("uint8_t[]", data) -> _FfiBuf
        if ctype.startswith("uint8_t[]") or ctype.startswith("char[]"):
            data = args[0] if args else b""
            if isinstance(data, int):
                data = bytes(data)
            return _FfiBuf(bytes(data))
        # ffi.new("int[]", values) -> _FfiIntArray
        if ctype.startswith("int[]"):
            return _FfiIntArray(args[0] if args else [])
        # ffi.new("size_t[]", values) -> _FfiSizeArray
        if ctype.startswith("size_t[]"):
            return _FfiSizeArray(args[0] if args else [])
        # ffi.new("const uint8_t *[]", items) -> _FfiPtrArray
        if "uint8_t *[]" in ctype or "char *[]" in ctype:
            return _FfiPtrArray(args[0] if args else [])
        # ffi.new("uint8_t **") etc. -> _FfiOutPtr
        if ctype.endswith("**") or ctype.endswith("*"):
            initial = args[0] if args else None
            return _FfiOutPtr(initial)
        # ffi.new("unsigned int *") etc.
        return _FfiOutPtr(args[0] if args else 0)

    @staticmethod
    def cast(ctype, p):
        return p

    @staticmethod
    def sizeof(ctype):
        return 128

    @staticmethod
    def string(b):
        if isinstance(b, (bytes, bytearray)):
            return bytes(b).split(b"\x00")[0]
        if isinstance(b, _FfiBuf):
            return bytes(b._data).split(b"\x00")[0]
        return b""

    @staticmethod
    def buffer(buf, n):
        if isinstance(buf, _FfiBuf):
            return bytes(buf._data[:n])
        if isinstance(buf, (bytes, bytearray)):
            return buf[:n]
        return b""


class FakeLib:
    """Minimal shim fake covering pyte_rpc_sendmsg / pyte_rpc_recvmsg."""

    PYTE_PF_INET = 2
    PYTE_SOCK_DGRAM = 2
    PYTE_PROTO_DEF = 0

    # TE's rpc_send_recv_flags encoding (te_rpc_sys_socket.h)
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
        # recvmsg pre-configured result
        self._recv_data = b"hello"
        self._recv_addr = b"127.0.0.1\x00"
        self._recv_port = 5000
        self._recv_levels = [0]
        self._recv_types = [8]
        self._recv_datas = [b"pktinfo"]
        self._recv_flags = 0

    # -- sendmsg ----------------------------------------------------------
    def pyte_rpc_sendmsg(self, rpcs, s,
                         iov_bufs, iov_lens, n_iov,
                         addr, port,
                         cmsg_levels, cmsg_types, cmsg_datas, cmsg_lens,
                         n_cmsg, flags, sent):
        # Extract iov data from the fake objects
        iov = []
        for i in range(n_iov):
            buf = iov_bufs[i]
            length = iov_lens[i]
            iov.append((bytes(buf)[:length], length))

        cmsgs = []
        for i in range(n_cmsg):
            lvl = int(cmsg_levels[i])
            typ = int(cmsg_types[i])
            dat = bytes(cmsg_datas[i])[:cmsg_lens[i]]
            cmsgs.append((lvl, typ, dat))

        self.calls.append(("sendmsg", {
            "s": s,
            "iov": iov,
            "addr": addr,
            "port": port,
            "cmsgs": cmsgs,
            "flags": flags,
        }))
        sent[0] = sum(length for _, length in iov)
        return 0

    # -- recvmsg ----------------------------------------------------------
    def pyte_rpc_recvmsg(self, rpcs, s, bufsize, ctrl_space, flags,
                         data_out, data_len_out,
                         from_addr_out, from_port_out,
                         levels_out, types_out, datas_out, lens_out,
                         n_cmsg_out, msg_flags_out, received_out):
        self.calls.append(("recvmsg", {
            "s": s, "bufsize": bufsize, "ctrl_space": ctrl_space,
        }))
        data_buf = _FfiBuf(self._recv_data)
        data_out[0] = data_buf
        data_len_out[0] = len(self._recv_data)

        addr_buf = _FfiBuf(self._recv_addr)
        from_addr_out[0] = addr_buf
        from_port_out[0] = self._recv_port

        n = len(self._recv_levels)
        n_cmsg_out[0] = n

        if n > 0:
            levels_out[0] = _FfiIntArray(self._recv_levels)
            types_out[0] = _FfiIntArray(self._recv_types)
            data_bufs = [_FfiBuf(d) for d in self._recv_datas]
            datas_out[0] = _FfiPtrArray(data_bufs)
            lens_out[0] = _FfiSizeArray([len(d) for d in self._recv_datas])

        msg_flags_out[0] = self._recv_flags
        received_out[0] = len(self._recv_data)
        return 0

    def pyte_free_cmsgs(self, levels, types_, datas, lens, n):
        self.calls.append(("free_cmsgs", n))

    def pyte_free_string(self, p):
        self.calls.append(("free_string",))

    def pyte_rpc_errno(self, rpcs):
        return 0

    def pyte_rpc_err_msg(self, rpcs):
        return b""

    def pyte_rc_error(self, rc):
        return 0

    def pyte_rc_module(self, rc):
        return 0

    def te_rc_mod2str(self, rc):
        return b"TAPI\x00"

    def te_rc_err2str(self, rc):
        return b"EFAIL\x00"


def _install_fake(monkeypatch, lib):
    monkeypatch.setitem(
        sys.modules, "pyte._shim",
        types.SimpleNamespace(ffi=FakeFfi(), lib=lib),
    )


class FakeServer:
    """Minimal server stub whose _check_call mirrors the real contract.

    When guard_rc != 0 or ok(retval) is False: raise RpcError (the
    expect_error() / SUPPRESSED path is not exercised here — tests that
    need suppression use a subclass or set _expected directly).
    """

    _h = object()
    name = "pco"

    def _check_call(self, guard_rc, retval, ok, where):
        from pyte.errors import RpcError
        if guard_rc != 0:
            raise RpcError(guard_rc, where, "")
        if ok(retval):
            return retval
        # Mirror real _check_call: failed call with no expect_error → raise.
        raise RpcError(0, f"{where} -> {retval!r}", "remote errno 0")

    def __repr__(self):
        return "<FakeServer>"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_sendmsg_scatter(monkeypatch):
    """sendmsg assembles multiple buffers and returns total byte count."""
    lib = FakeLib()
    _install_fake(monkeypatch, lib)
    sock = RpcSocket(FakeServer(), 7)

    n = sock.sendmsg([b"hello-", b"world"], flags=Msg.DONTWAIT)

    assert n == 11
    assert len(lib.calls) == 1
    kind, args = lib.calls[0]
    assert kind == "sendmsg"
    assert args["iov"] == [(b"hello-", 6), (b"world", 5)]
    assert args["addr"] is None or isinstance(args["addr"], _FfiNull)
    assert args["cmsgs"] == []
    assert args["flags"] == FakeLib.PYTE_MSG_DONTWAIT   # TE encoding


def test_sendmsg_with_addr_and_ancillary(monkeypatch):
    """sendmsg with addr and a cmsg triplet passes them through."""
    lib = FakeLib()
    _install_fake(monkeypatch, lib)
    sock = RpcSocket(FakeServer(), 7)

    IPPROTO_IP, IP_TTL = 0, 2
    n = sock.sendmsg([b"data"], addr=("127.0.0.1", 9000),
                     ancillary=[(IPPROTO_IP, IP_TTL, b"\x40")])
    assert n == 4
    _, args = lib.calls[0]
    assert args["port"] == 9000
    assert len(args["cmsgs"]) == 1
    lvl, typ, dat = args["cmsgs"][0]
    assert (lvl, typ) == (IPPROTO_IP, IP_TTL)
    assert dat == b"\x40"


def test_recvmsg_basic(monkeypatch):
    """recvmsg returns RecvMsg with data, ancillary list, addr, flags."""
    lib = FakeLib()
    lib._recv_levels = [0]
    lib._recv_types = [8]
    lib._recv_datas = [b"pktinfo_bytes"]
    _install_fake(monkeypatch, lib)
    sock = RpcSocket(FakeServer(), 7)

    msg = sock.recvmsg(64, ctrl_space=256)

    assert isinstance(msg, RecvMsg)
    assert msg.data == b"hello"
    assert msg.addr == ("127.0.0.1", 5000)
    assert msg.flags == Msg(0)
    assert len(msg.ancillary) == 1
    lvl, typ, dat = msg.ancillary[0]
    assert (lvl, typ) == (0, 8)
    assert dat == b"pktinfo_bytes"
    # Memory ownership: pyte_free_cmsgs must be called exactly once with n=1
    free_calls = [c for c in lib.calls if c[0] == "free_cmsgs"]
    assert len(free_calls) == 1
    assert free_calls[0][1] == 1


def test_recvmsg_no_cmsg(monkeypatch):
    """recvmsg with no control data returns empty ancillary list."""
    lib = FakeLib()
    lib._recv_levels = []
    lib._recv_types = []
    lib._recv_datas = []
    _install_fake(monkeypatch, lib)
    sock = RpcSocket(FakeServer(), 7)

    msg = sock.recvmsg(64)
    assert msg.ancillary == []
    assert msg.data == b"hello"


def test_sendmsg_empty_buffers_raises(monkeypatch):
    """sendmsg raises ValueError when given an empty buffer list."""
    lib = FakeLib()
    _install_fake(monkeypatch, lib)
    sock = RpcSocket(FakeServer(), 7)
    with pytest.raises(ValueError, match="non-empty"):
        sock.sendmsg([])


def test_sendmsg_bad_ancillary_raises(monkeypatch):
    """sendmsg raises ValueError for malformed ancillary triplets."""
    lib = FakeLib()
    _install_fake(monkeypatch, lib)
    sock = RpcSocket(FakeServer(), 7)
    # not a 3-tuple
    with pytest.raises(ValueError, match="ancillary"):
        sock.sendmsg([b"x"], ancillary=[(0, 1)])
    # data not bytes
    with pytest.raises(ValueError, match="ancillary"):
        sock.sendmsg([b"x"], ancillary=[(0, 1, "string")])


def test_recvmsg_multi_cmsg(monkeypatch):
    """recvmsg with two cmsg records returns both triplets in order."""
    lib = FakeLib()
    lib._recv_levels = [1, 41]   # SOL_SOCKET=1, IPPROTO_IPV6=41
    lib._recv_types = [8, 50]    # SO_TIMESTAMP=8, IPV6_PKTINFO=50
    lib._recv_datas = [b"ts_data", b"v6info"]
    _install_fake(monkeypatch, lib)
    sock = RpcSocket(FakeServer(), 7)

    msg = sock.recvmsg(64, ctrl_space=512)

    assert isinstance(msg, RecvMsg)
    assert len(msg.ancillary) == 2
    assert msg.ancillary[0] == (1, 8, b"ts_data")
    assert msg.ancillary[1] == (41, 50, b"v6info")
    # pyte_free_cmsgs called once with n=2
    free_calls = [c for c in lib.calls if c[0] == "free_cmsgs"]
    assert len(free_calls) == 1
    assert free_calls[0][1] == 2


def test_sendmsg_negative_retval_returns_via_check_call(monkeypatch):
    """sendmsg with retval -1 and guard rc 0 causes RpcError via _check_call.

    The shim now stores the raw retval in *sent and returns 0 (guard_rc=0).
    _check_call sees retval=-1, ok(retval) is False, and raises RpcError.
    This verifies the sendto-style passthrough (not TE_EFAIL conversion).
    """
    from pyte.errors import RpcError

    class FailLib(FakeLib):
        def pyte_rpc_sendmsg(self, rpcs, s,
                             iov_bufs, iov_lens, n_iov,
                             addr, port,
                             cmsg_levels, cmsg_types, cmsg_datas, cmsg_lens,
                             n_cmsg, flags, sent):
            self.calls.append(("sendmsg", {}))
            sent[0] = -1   # negative retval, like a failed remote syscall
            return 0       # guard rc 0: no longjmp, remote errno is in rpcs

    lib = FailLib()
    _install_fake(monkeypatch, lib)
    sock = RpcSocket(FakeServer(), 7)

    with pytest.raises(RpcError):
        sock.sendmsg([b"data"])


def test_ancillary_level_type_must_be_int(monkeypatch):
    """sendmsg raises ValueError when level or type is not an int."""
    lib = FakeLib()
    _install_fake(monkeypatch, lib)
    sock = RpcSocket(FakeServer(), 7)

    # level is a string instead of int
    with pytest.raises(ValueError, match="level"):
        sock.sendmsg([b"x"], ancillary=[("IPPROTO_IP", 2, b"\x40")])

    # type is a float instead of int
    with pytest.raises(ValueError, match="type"):
        sock.sendmsg([b"x"], ancillary=[(0, 2.0, b"\x40")])


# -- recvmsg memory hygiene ---------------------------------------------------

def test_recvmsg_bad_addr_bytes_decode_with_replace(monkeypatch):
    """A non-UTF-8 source address must not raise (and leak the C
    buffers): decode with errors=\"replace\" like the rest of pyte."""
    lib = FakeLib()
    lib._recv_addr = b"\xff\xfe\x00"
    lib._recv_levels = []
    lib._recv_types = []
    lib._recv_datas = []
    _install_fake(monkeypatch, lib)
    sock = RpcSocket(FakeServer(), 7)

    msg = sock.recvmsg(64)

    assert msg.addr == ("��", 5000)
    frees = [c for c in lib.calls if c[0] == "free_string"]
    assert len(frees) == 2   # data + from_addr


def test_recvmsg_frees_buffers_when_extraction_raises(monkeypatch):
    """If extraction fails mid-way, every C allocation is still freed."""

    class BoomArray:
        def __getitem__(self, idx):
            raise RuntimeError("boom during extraction")

    class BoomLib(FakeLib):
        def pyte_rpc_recvmsg(self, rpcs, s, bufsize, ctrl_space, flags,
                             data_out, data_len_out,
                             from_addr_out, from_port_out,
                             levels_out, types_out, datas_out, lens_out,
                             n_cmsg_out, msg_flags_out, received_out):
            super().pyte_rpc_recvmsg(
                rpcs, s, bufsize, ctrl_space, flags,
                data_out, data_len_out, from_addr_out, from_port_out,
                levels_out, types_out, datas_out, lens_out,
                n_cmsg_out, msg_flags_out, received_out)
            lens_out[0] = BoomArray()   # poison the cmsg length array
            return 0

    lib = BoomLib()
    _install_fake(monkeypatch, lib)
    sock = RpcSocket(FakeServer(), 7)

    with pytest.raises(RuntimeError, match="boom"):
        sock.recvmsg(64, ctrl_space=256)

    frees = [c for c in lib.calls if c[0] == "free_string"]
    assert len(frees) == 2, "data and from_addr must be freed on failure"
    assert [c for c in lib.calls if c[0] == "free_cmsgs"], \
        "cmsg arrays must be freed on failure"
