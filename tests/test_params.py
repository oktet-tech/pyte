# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
import pytest

from pyte._params import Params, parse_argv


def test_parse_argv_basic():
    p = parse_argv(["a=1", "b=hello world", "c="])
    assert p == {"a": "1", "b": "hello world", "c": ""}


def test_parse_argv_value_with_equals():
    assert parse_argv(["expr=a=b"]) == {"expr": "a=b"}


def test_parse_argv_malformed():
    with pytest.raises(ValueError):
        parse_argv(["no-equals-here"])


def test_params_typed():
    p = Params({"n": "42", "f": "1.5", "yes": "TRUE", "no": "off",
                "mode": "fast"})
    assert p.int("n") == 42
    assert p.float("f") == 1.5
    assert p.bool("yes") is True
    assert p.bool("no") is False
    assert p.enum("mode", {"fast": 1, "slow": 2}) == 1
    with pytest.raises(KeyError):
        p["absent"]


def test_parse_argv_duplicate_first_wins():
    """First occurrence of a duplicate name is kept, matching TE C behaviour."""
    assert parse_argv(["a=1", "a=2"]) == {"a": "1"}


def test_params_int_hex():
    """int() with base-0 parsing accepts hex literals."""
    p = Params({"n": "0x10"})
    assert p.int("n") == 16


def test_params_bool_garbage():
    """bool() raises ValueError for unrecognised strings."""
    p = Params({"flag": "maybe"})
    with pytest.raises(ValueError):
        p.bool("flag")


def test_params_get_default():
    """get() returns the default when the key is absent."""
    p = Params({"a": "1"})
    assert p.get("missing") is None
    assert p.get("missing", "fallback") == "fallback"
    assert p.get("a", "fallback") == "1"


def test_params_contains():
    """__contains__ works for present and absent keys."""
    p = Params({"a": "1"})
    assert "a" in p
    assert "b" not in p
