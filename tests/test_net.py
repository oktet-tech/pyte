# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
import pytest

from pyte.net import Route, _parse_route_inst, _sys_path


def test_parse_route_inst_plain():
    assert _parse_route_inst("10.0.0.0|24") == ("10.0.0.0", 24, {})


def test_parse_route_inst_with_metric():
    dst, prefix, opts = _parse_route_inst("10.0.0.0|24,metric=10")
    assert (dst, prefix) == ("10.0.0.0", 24)
    assert opts == {"metric": "10"}


def test_parse_route_inst_multi_opts():
    _, _, opts = _parse_route_inst("0.0.0.0|0,metric=100,tos=4")
    assert opts == {"metric": "100", "tos": "4"}


def test_parse_route_inst_malformed():
    with pytest.raises(ValueError):
        _parse_route_inst("no-pipe-here")


def test_sys_path_dots_and_slashes():
    assert _sys_path("net.ipv4.ip_forward") == "net/ipv4/ip_forward"
    assert _sys_path("net/ipv4/ip_forward") == "net/ipv4/ip_forward"


def test_route_dataclass_frozen():
    r = Route(dst="10.0.0.0", prefix=24, gw=None, dev="lo", metric=10)
    with pytest.raises(Exception):
        r.dst = "x"


def test_dst_spec_parsing():
    from pyte.net import _parse_dst
    assert _parse_dst("10.0.0.0/24") == ("10.0.0.0", 24)
    assert _parse_dst("10.0.0.1") == ("10.0.0.1", 32)
    with pytest.raises(ValueError):
        _parse_dst("10.0.0.0/33")
