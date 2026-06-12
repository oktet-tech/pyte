# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""IoMux unit tests with a fake shim."""
import sys
import types

import pytest

import pyte.rpc.iomux as _iomux_mod
from pyte.rpc.iomux import EVENT_BITS, IoMux, _evt_bits, _evt_names


class FakeLib:
    """Minimal fake shim lib for iomux tests.

    pyte_iomux_call returns a single int[2*n] array interleaving
    [fd0, evt0, fd1, evt1, ...] — matching the real shim design.
    call_result is (n, interleaved_list) where interleaved_list has
    2*n elements.
    """
    PYTE_ETIMEDOUT = 1
    PYTE_IOMUX_SELECT = 1
    PYTE_IOMUX_PSELECT = 2
    PYTE_IOMUX_POLL = 3
    PYTE_IOMUX_PPOLL = 4
    PYTE_IOMUX_EPOLL = 5
    PYTE_IOMUX_EPOLL_PWAIT = 6
    PYTE_IOMUX_EPOLL_PWAIT2 = 8
    PYTE_IOMUX_EVT_RD = 0x1
    PYTE_IOMUX_EVT_PRI = 0x2
    PYTE_IOMUX_EVT_WR = 0x4
    PYTE_IOMUX_EVT_EXC = 0x80
    PYTE_IOMUX_EVT_ERR = 0x100
    PYTE_IOMUX_EVT_HUP = 0x200
    PYTE_IOMUX_EVT_RDHUP = 0x400
    PYTE_IOMUX_EVT_ET = 0x800
    PYTE_IOMUX_EVT_ONESHOT = 0x1000
    PYTE_IOMUX_EVT_NVAL = 0x2000

    def __init__(self):
        self.calls = []
        # (n, interleaved): n events; interleaved = [fd0,evt0,fd1,evt1,...]
        self.call_result = (0, [])

    def pyte_iomux_create(self, rpcs, kind, out):
        self.calls.append(("create", kind))
        out[0] = object()
        return 0

    def pyte_iomux_add(self, h, fd, evt):
        self.calls.append(("add", fd, evt))
        return 0

    def pyte_iomux_mod(self, h, fd, evt):
        self.calls.append(("mod", fd, evt))
        return 0

    def pyte_iomux_del(self, h, fd):
        self.calls.append(("del", fd))
        return 0

    def pyte_iomux_call(self, h, timeout_ms, n_out, revts_p):
        self.calls.append(("call", timeout_ms))
        n, interleaved = self.call_result
        n_out[0] = n
        revts_p[0] = interleaved if n > 0 else None
        return 0

    def pyte_iomux_destroy(self, h):
        self.calls.append(("destroy",))
        return 0

    def pyte_free_ints(self, p):
        self.calls.append(("free",))


class FakeFfi:
    NULL = None

    @staticmethod
    def new(ctype):
        return [None]

    @staticmethod
    def unpack(p, n):
        # p is the interleaved list; unpack n elements from it
        return list(p[:n])

    @staticmethod
    def string(b):
        return b


def _fake_shim(monkeypatch, lib):
    monkeypatch.setitem(sys.modules, "pyte._shim",
                        types.SimpleNamespace(ffi=FakeFfi(), lib=lib))
    # Clear cached EVENT_BITS so they are re-populated from the fake lib.
    _iomux_mod.EVENT_BITS.clear()


class FakeServer:
    _h = object()
    name = "pco"

    def __repr__(self):
        return "<FakeServer>"


@pytest.fixture(autouse=True)
def _reset_event_bits():
    """Clear the module-level EVENT_BITS cache after each test to prevent
    bleed between tests that use different (fake vs real) shims."""
    yield
    _iomux_mod.EVENT_BITS.clear()


def test_evt_bits_roundtrip(monkeypatch):
    lib = FakeLib()
    _fake_shim(monkeypatch, lib)
    assert _evt_bits("in") == EVENT_BITS["in"]
    assert _evt_bits("in,out") == (EVENT_BITS["in"] | EVENT_BITS["out"])
    with pytest.raises(ValueError, match="bogus"):
        _evt_bits("bogus")


def test_evt_names_decodes_bits(monkeypatch):
    lib = FakeLib()
    _fake_shim(monkeypatch, lib)
    # Ensure EVENT_BITS is populated before reading it
    _evt_bits("in")
    names = _evt_names(EVENT_BITS["in"] | EVENT_BITS["err"])
    assert names == {"in", "err"}


def test_iomux_sequence_and_timeout(monkeypatch):
    lib = FakeLib()
    _fake_shim(monkeypatch, lib)
    mux = IoMux.create(FakeServer(), "epoll")
    mux.add(7, "in")
    mux.mod(7, "out")
    assert mux.wait(0.5) == []           # timeout -> empty list (n==0)
    # Two events: fd=7 (in/RD=0x1), fd=9 (err=0x100)
    lib.call_result = (2, [7, 0x1, 9, 0x100])
    res = mux.wait(1.0)
    assert res == [(7, {"in"}), (9, {"err"})]
    mux.delete(7)
    mux.close()
    kinds = [c[0] for c in lib.calls]
    assert kinds == ["create", "add", "mod", "call", "call", "free",
                     "del", "destroy"]
    assert ("add", 7, 0x1) in lib.calls and ("mod", 7, 0x4) in lib.calls


def test_iomux_close_idempotent(monkeypatch):
    lib = FakeLib()
    _fake_shim(monkeypatch, lib)
    mux = IoMux.create(FakeServer(), "epoll")
    mux.close()
    mux.close()
    assert [c for c in lib.calls if c[0] == "destroy"] == [("destroy",)]
