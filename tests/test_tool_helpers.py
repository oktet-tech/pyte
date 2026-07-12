# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools._tool / _units shared-helper unit tests (offline)."""
import enum

import pytest

from pyte.tools import _tool, _units


# -- argv builders ------------------------------------------------------

def test_opt_emits_flag_value_pair():
    assert _tool.opt("-p", 8080) == ["-p", "8080"]
    assert _tool.opt("-t", "tcp") == ["-t", "tcp"]


def test_opt_none_emits_nothing():
    assert _tool.opt("-p", None) == []


def test_opt_eq_emits_joined_form():
    assert _tool.opt_eq("--threads=", 4) == ["--threads=4"]
    assert _tool.opt_eq("--key-prefix=", "k") == ["--key-prefix=k"]
    assert _tool.opt_eq("--requests=", None) == []


def test_switch_emits_flag_when_on():
    assert _tool.switch("-D", True) == ["-D"]
    assert _tool.switch("-D", False) == []
    assert _tool.switch("--random-data", None) == []


def test_suffixed_appends_unit():
    assert _tool.suffixed("--time=", 30, "s") == ["--time=30s"]
    assert _tool.suffixed("--time=", None, "s") == []


def test_builders_compose_argv_in_explicit_order():
    argv = [*_tool.opt("-p", 1), *_tool.switch("-D", True),
            *_tool.opt_eq("--x=", None), *_tool.opt("-c", 4)]
    assert argv == ["-p", "1", "-D", "-c", "4"]


# -- coerce_enum (promoted from fio) -----------------------------------

class Mode(enum.Enum):
    READ = "read"
    RANDWRITE = "randwrite"


def test_coerce_enum_passthrough_and_string():
    assert _tool.coerce_enum(Mode, "mode", Mode.READ) is Mode.READ
    assert _tool.coerce_enum(Mode, "mode", "read") is Mode.READ
    assert _tool.coerce_enum(Mode, "mode", "RANDWRITE") is Mode.RANDWRITE


def test_coerce_enum_bad_name_lists_valid():
    with pytest.raises(ValueError, match="randwrite"):
        _tool.coerce_enum(Mode, "mode", "sideways")


def test_coerce_enum_bad_type():
    with pytest.raises(TypeError, match="mode must be Mode or str"):
        _tool.coerce_enum(Mode, "mode", 3)


# -- address helpers (promoted from memcached/memaslap) -----------------

class _Addr:
    """Duck-typed pyte.env.Addr: exposes .pair."""

    def __init__(self, host, port):
        self.pair = (host, port)


def test_addr_host_port_accepts_tuple_and_addr():
    assert _tool.addr_host_port(("10.0.0.1", 11211)) == ("10.0.0.1", 11211)
    assert _tool.addr_host_port(_Addr("h", 5)) == ("h", 5)


def test_addr_host_port_rejects_bare_port():
    with pytest.raises(TypeError, match="host"):
        _tool.addr_host_port(11211)


def test_addr_port_accepts_int_tuple_and_addr():
    assert _tool.addr_port(11211) == 11211
    assert _tool.addr_port(("10.0.0.1", 11211)) == 11211
    assert _tool.addr_port(_Addr("h", 5)) == 5


# -- ipversion validation (dedup of three frozenset copies) -------------

def test_check_ipversion_accepts_4_6_none():
    _tool.check_ipversion(None)
    _tool.check_ipversion("4")
    _tool.check_ipversion("6")


def test_check_ipversion_rejects_others():
    with pytest.raises(ValueError, match="ipversion"):
        _tool.check_ipversion("5")
    with pytest.raises(ValueError, match="ipversion"):
        _tool.check_ipversion(4)      # int is not the tool flag form


# -- unit parsing (promoted from wrk/fio) --------------------------------

def test_parse_unit_time():
    assert _units.parse_unit("456.78us", _units.TIME_US) == 456.78
    assert _units.parse_unit("2.50ms", _units.TIME_US) == 2500.0
    assert _units.parse_unit("1.5s", _units.TIME_US) == 1.5e6


def test_parse_unit_metric_binary_percent():
    assert _units.parse_unit("12.34k", _units.METRIC) == 12340.0
    assert _units.parse_unit("3.50M", _units.BINARY) == 3.5 * 1024 ** 2
    assert _units.parse_unit("89.00%", _units.TIME_US) == 89.0


def test_parse_unit_unknown_suffix():
    with pytest.raises(ValueError, match="unknown unit"):
        _units.parse_unit("3fortnights", _units.TIME_US)


def test_parse_size_fio_semantics():
    assert _units.parse_size(None) is None
    assert _units.parse_size(4096) == 4096
    assert _units.parse_size("4k") == 4096
    assert _units.parse_size("16M") == 16 * 1024 ** 2
    assert _units.parse_size("1g") == 1024 ** 3


def test_parse_size_rejects_bad_input():
    with pytest.raises(ValueError):
        _units.parse_size("1.5g")     # whole numbers only
    with pytest.raises(ValueError):
        _units.parse_size("4x")
    with pytest.raises(ValueError):
        _units.parse_size(0)
    with pytest.raises(ValueError):
        _units.parse_size("-4k")
