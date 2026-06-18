# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Unit tests for pyte.cfg value decoding and backup orchestration.

Pure Python — the shim is never imported; lib-touching code is exercised
through monkeypatched seams.
"""
from pyte import cfg


# -- _to_py_kind: pure decode -----------------------------------------

def test_to_py_kind_none():
    assert cfg._to_py_kind("", "none") is None


def test_to_py_kind_bool_true_false():
    assert cfg._to_py_kind("1", "bool") is True
    assert cfg._to_py_kind("0", "bool") is False


def test_to_py_kind_int():
    assert cfg._to_py_kind("-7", "int") == -7
    assert isinstance(cfg._to_py_kind("-7", "int"), int)


def test_to_py_kind_float():
    assert cfg._to_py_kind("1.5", "float") == 1.5


def test_to_py_kind_str_passthrough():
    # ADDRESS and STRING both arrive as kind "str": MAC/IP/text untouched.
    assert cfg._to_py_kind("aa:bb:cc:dd:ee:ff", "str") == "aa:bb:cc:dd:ee:ff"
    assert cfg._to_py_kind("192.0.2.1", "str") == "192.0.2.1"


# -- get(): typing + sync via monkeypatched shim ----------------------

def _install_fake_get(monkeypatch, value: str, cvt: int):
    """Make cfg.get decode `value`/`cvt` without touching the real shim."""
    # CVT ints mirror the shim: NONE=0, BOOL=1, INT32=6, STRING=10,
    # DOUBLE=12 (see PYTE_CVT_* in shim/pyte_shim.h).
    monkeypatch.setattr(cfg, "_cvt_kind",
                        lambda c: {0: "none", 1: "bool", 6: "int",
                                   12: "float", 10: "str"}[c])
    monkeypatch.setattr(cfg, "_raw_get", lambda oid: (value, cvt))
    recorder = {}
    monkeypatch.setattr(cfg, "synchronize",
                        lambda oid, subtree=True: recorder.setdefault(
                            "sync", (oid, subtree)))
    return recorder


def test_get_bool_returns_bool(monkeypatch):
    _install_fake_get(monkeypatch, "1", 1)
    v = cfg.get("/agent:A/x:")
    assert v is True


def test_get_double_returns_float(monkeypatch):
    _install_fake_get(monkeypatch, "2.5", 12)
    assert cfg.get("/agent:A/x:") == 2.5


def test_get_sync_calls_synchronize_subtree_false(monkeypatch):
    rec = _install_fake_get(monkeypatch, "5", 6)
    cfg.get("/agent:A/x:", sync=True)
    assert rec["sync"] == ("/agent:A/x:", False)


def test_get_no_sync_does_not_synchronize(monkeypatch):
    rec = _install_fake_get(monkeypatch, "5", 6)
    cfg.get("/agent:A/x:")
    assert "sync" not in rec
