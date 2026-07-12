# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte._util: the shim accessors must resolve through sys.modules."""
import sys
import types

from pyte import _util


def test_shim_resolves_injected_fake(monkeypatch):
    """Fake-shim injection (the whole unit-test strategy) must keep
    working through the accessor: it resolves via sys.modules at call
    time, not via the pyte package attribute."""
    fake = types.SimpleNamespace(ffi="fake-ffi", lib="fake-lib")
    monkeypatch.setitem(sys.modules, "pyte._shim", fake)
    assert _util.shim() == ("fake-ffi", "fake-lib")
    assert _util.shim_lib() == "fake-lib"


def test_shim_sees_replacement_per_call(monkeypatch):
    monkeypatch.setitem(sys.modules, "pyte._shim",
                        types.SimpleNamespace(ffi=1, lib=1))
    assert _util.shim() == (1, 1)
    monkeypatch.setitem(sys.modules, "pyte._shim",
                        types.SimpleNamespace(ffi=2, lib=2))
    assert _util.shim() == (2, 2)


def test_enc_never_raises():
    assert _util.enc("café") == "café".encode()
    assert _util.enc("\udcff") == b"\\udcff"    # backslashreplace


def test_take_str_decodes_frees_and_nulls(monkeypatch):
    freed = []

    class Ffi:
        NULL = object()

        @staticmethod
        def string(b):
            return b

    class Lib:
        @staticmethod
        def pyte_free_string(p):
            freed.append(p)

    monkeypatch.setitem(sys.modules, "pyte._shim",
                        types.SimpleNamespace(ffi=Ffi(), lib=Lib()))
    out = [b"hello"]
    assert _util.take_str(out) == "hello"
    assert freed == [b"hello"]
    assert out[0] is Ffi.NULL
