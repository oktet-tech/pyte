# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tester unit tests with a fake shim."""
import sys
import types

import pytest

from pyte import tester
from pyte.errors import TeError


class FakeLib:
    PYTE_ETIMEDOUT = 1

    def __init__(self, rc=0):
        self.rc = rc
        self.calls = []

    def pyte_reqs_modify(self, reqs):
        self.calls.append(("reqs", bytes(reqs)))
        return self.rc

    def pyte_tags_add_tag(self, tag, value):
        self.calls.append(("tag", bytes(tag), bytes(value)))
        return self.rc

    # TeError construction path
    def pyte_rc_module(self, rc):
        return 0

    def pyte_rc_error(self, rc):
        return rc

    def te_rc_mod2str(self, rc):
        return b"TAPI"

    def te_rc_err2str(self, rc):
        return b"EPERM"


class FakeFfi:
    @staticmethod
    def string(b):
        return b


def _fake_shim(monkeypatch, lib):
    monkeypatch.setitem(
        sys.modules, "pyte._shim",
        types.SimpleNamespace(ffi=FakeFfi(), lib=lib))


def test_modify_reqs_passes_expression(monkeypatch):
    lib = FakeLib()
    _fake_shim(monkeypatch, lib)
    tester.modify_reqs("!FIO")
    assert lib.calls == [("reqs", b"!FIO")]


def test_add_trc_tag_value_default(monkeypatch):
    lib = FakeLib()
    _fake_shim(monkeypatch, lib)
    tester.add_trc_tag("no_fio")
    assert lib.calls == [("tag", b"no_fio", b"")]


def test_add_trc_tag_with_value(monkeypatch):
    lib = FakeLib()
    _fake_shim(monkeypatch, lib)
    tester.add_trc_tag("linux", "6.17")
    assert lib.calls == [("tag", b"linux", b"6.17")]


def test_errors_surface_as_teerror(monkeypatch):
    lib = FakeLib(rc=0xBEEF)
    _fake_shim(monkeypatch, lib)
    with pytest.raises(TeError, match="add_trc_tag"):
        tester.add_trc_tag("x")
    with pytest.raises(TeError, match="modify_reqs"):
        tester.modify_reqs("x")
