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


def test_params_compound_empty_name():
    with pytest.raises(ValueError, match="empty compound argument name"):
        Params(parse_argv(["COMP.=a", "_a=1"]))


def test_params_compound_field_whitespace():
    p = Params(parse_argv(["COMP.link=mtu, speed", "link_mtu=1",
                           "link_speed=2"]))
    assert p.compound("link") == {"mtu": "1", "speed": "2"}


def test_params_raw_accessors_see_marker():
    p = Params(parse_argv(["COMP.link=mtu", "link_mtu=1"]))
    assert "COMP.link" in p and "COMP.link" in p.as_dict()


def test_params_compounds_order():
    p = Params(parse_argv(["COMP.b=x", "COMP.a=y", "b_x=1", "a_y=2"]))
    assert list(p.compounds()) == ["b", "a"]


def test_param_error_is_a_test_failure_and_a_value_error():
    from pyte.errors import ParamError, TestFail
    assert issubclass(ParamError, TestFail)
    assert issubclass(ParamError, ValueError)


@pytest.mark.parametrize("read, raw, want", [
    ("int", "abc", "n='abc': want an integer"),
    ("float", "1.5.2", "n='1.5.2': want a number"),
    ("bool", "maybe", "n='maybe': want a boolean"),
    ("flag", "true", "n='true': want TRUE or FALSE"),
])
def test_reader_errors_name_the_parameter(read, raw, want):
    from pyte.errors import ParamError
    p = Params({"n": raw})
    with pytest.raises(ParamError, match=want):
        getattr(p, read)("n")


def test_enum_error_names_the_parameter_and_the_choices():
    from pyte.errors import ParamError
    p = Params({"mode": "z"})
    assert p.enum("mode", {"z": 26}) == 26
    with pytest.raises(ParamError, match=r"mode='z': want one of \['a', 'b'\]"):
        p.enum("mode", {"a": 1, "b": 2})


def test_flag_takes_only_the_te_spelling():
    p = Params({"a": "TRUE", "b": "FALSE"})
    assert p.flag("a") is True and p.flag("b") is False
    assert p.bool("a") is True          # bool() stays loose


def test_readers_return_the_default_of_an_absent_parameter():
    p = Params({"n": "3"})
    assert p.int("n", 7) == 3
    assert p.int("missing", 7) == 7
    assert p.float("missing", 0.5) == 0.5
    assert p.bool("missing", True) is True
    assert p.flag("missing", False) is False
    assert p.enum("missing", {"a": 1}, None) is None
    with pytest.raises(KeyError, match="no parameter 'missing'"):
        p.int("missing")


def test_compound_is_a_named_mapping():
    p = Params(parse_argv(["COMP.link=mtu,speed", "link_mtu=1500",
                           "link_speed=25G"]))
    link = p.compound("link")
    assert link.name == "link"
    assert dict(link) == {"mtu": "1500", "speed": "25G"}
    assert list(link) == ["mtu", "speed"] and len(link) == 2
    assert link["mtu"] == "1500" and link.get("duplex") is None
    assert "speed" in link and "duplex" not in link
    assert p.compounds()["link"] == link


def test_compound_readers_report_the_flattened_name():
    from pyte._params import Compound
    from pyte.errors import ParamError
    lane = Compound("iperf3_tcp", {"count": "abc", "streams": "4",
                                   "reverse": "yes"})
    assert lane.int("streams") == 4
    assert lane.int("burst", 32) == 32
    with pytest.raises(ParamError,
                       match="iperf3_tcp_count='abc': want an integer"):
        lane.int("count")
    with pytest.raises(ParamError,
                       match="iperf3_tcp_reverse='yes': want TRUE or FALSE"):
        lane.flag("reverse")


def test_compound_require_and_error():
    from pyte._params import Compound
    from pyte.errors import ParamError
    lane = Compound("ping", {"dut": "iut_pf0", "count": "0"})
    assert lane.require("dut") == "iut_pf0"
    with pytest.raises(ParamError,
                       match="ping_peer: the field is required"):
        lane.require("peer")
    with pytest.raises(ParamError, match="ping_peer: the field is required"):
        lane.int("peer")
    e = lane.error("count", "must be >= 1")
    assert isinstance(e, ParamError)
    assert str(e) == "ping_count='0': must be >= 1"
    assert str(lane.error("peer", "is needed here")) == (
        "ping_peer: is needed here")


def test_compound_does_not_alias_the_callers_fields():
    from pyte._params import Compound
    fields = {"a": "1"}
    c = Compound("x", fields)
    fields["a"] = "2"
    assert c["a"] == "1"
