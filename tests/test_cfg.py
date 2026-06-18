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
