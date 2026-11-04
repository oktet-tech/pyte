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


def test_params_as_dict_lists_every_parameter():
    """as_dict() lets a caller see every name, e.g. to reject typos."""
    raw = {"a": "1", "pf_lane": "idle", "c": ""}
    p = Params(raw)
    d = p.as_dict()
    assert d == raw
    d["a"] = "changed"                  # a copy: Params stays as it was
    assert p["a"] == "1" and raw["a"] == "1"


def test_var_reference_resolved(monkeypatch):
    monkeypatch.setenv("TE_TEST_VAR_env__iut_only", "'net':IUT{}")
    p = parse_argv(["env=VAR.env.iut_only"])
    assert p["env"] == "'net':IUT{}"


def test_var_prefix_must_match_exactly():
    assert parse_argv(["a=VARIANT1"])["a"] == "VARIANT1"
    assert parse_argv(["a=VAR"])["a"] == "VAR"


def test_var_reference_missing_raises():
    with pytest.raises(ValueError, match="TE_TEST_VAR_no__such"):
        parse_argv(["env=VAR.no.such"])


def test_params_compounds():
    p = Params(parse_argv(["te_test_id=1", "COMP.link=mtu,speed",
                           "link_mtu=1500", "link_speed=25G",
                           "duration=60"]))
    assert p.compounds() == {"link": {"mtu": "1500", "speed": "25G"}}
    assert p.compound("link") == {"mtu": "1500", "speed": "25G"}
    assert p.plain() == {"duration": "60"}
    assert p["link_mtu"] == "1500"


def test_params_no_compounds():
    p = Params(parse_argv(["te_test_id=1", "a=1"]))
    assert p.compounds() == {} and p.plain() == {"a": "1"}


def test_params_compound_missing():
    with pytest.raises(KeyError, match="no compound argument 'x'"):
        Params(parse_argv(["COMP.link=mtu", "link_mtu=1"])).compound("x")


def test_params_compound_field_missing():
    with pytest.raises(ValueError, match="'link'.*'mtu'.*'link_mtu'"):
        Params(parse_argv(["COMP.link=mtu,speed", "link_speed=25G"]))


def test_params_compound_name_with_underscores():
    p = Params(parse_argv(["COMP.iperf3_tcp_jumbo=dut,pkt_size",
                           "iperf3_tcp_jumbo_dut=iut_pf0",
                           "iperf3_tcp_jumbo_pkt_size=9000"]))
    assert list(p.compounds()) == ["iperf3_tcp_jumbo"]
    assert p.compound("iperf3_tcp_jumbo")["pkt_size"] == "9000"


def test_params_compound_empty_marker_and_te_names():
    p = Params(parse_argv(["te_test_id=1", "te_test_name=n", "te_rand_seed=3",
                           "te_other=x", "COMP.x="]))
    assert p.compounds() == {"x": {}}
    assert p.plain() == {"te_other": "x"}
