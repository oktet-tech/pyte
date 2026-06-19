# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
import dataclasses

import pytest

from pyte.net import Route, _parse_dst, _parse_mac, _parse_route_inst, _sys_path


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
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.dst = "x"


def test_dst_spec_parsing():
    assert _parse_dst("10.0.0.0/24") == ("10.0.0.0", 24)
    assert _parse_dst("10.0.0.1") == ("10.0.0.1", 32)
    with pytest.raises(ValueError):
        _parse_dst("10.0.0.0/33")


def test_parse_dst_bad_ip():
    with pytest.raises(ValueError):
        _parse_dst("999.1.1.1")


def test_route_spec():
    r = Route(dst="10.0.0.0", prefix=24, gw=None, dev=None, metric=None)
    assert r.spec == "10.0.0.0/24"


def test_parse_mac_good():
    raw = _parse_mac("02:ab:cd:ef:12:34")
    assert raw == bytes([0x02, 0xab, 0xcd, 0xef, 0x12, 0x34])
    assert len(raw) == 6


def test_parse_mac_dashed_rejected():
    with pytest.raises(ValueError, match="bad MAC"):
        _parse_mac("02-ab-cd-ef-12-34")


def test_parse_mac_short_rejected():
    with pytest.raises(ValueError, match="bad MAC"):
        _parse_mac("02:ab:cd:ef:12")


# -- Sys + Phy curated facades ----------------------------------------

def test_agentnet_sys_is_typed_generated_sys():
    from pyte import net
    from pyte.cfg.gen.sys import Sys
    s = net.agent("A").sys
    assert isinstance(s, Sys)
    assert s.oid == "/agent:A/sys:"


def test_iface_phy_is_curated_phy():
    from pyte import net
    assert isinstance(net.Iface("A", "eth0").phy, net.Phy)


def test_curated_phy_speed_reads_oper_sets_admin(monkeypatch):
    from pyte import cfg, net
    from pyte.cfg import _engine
    sets = []
    monkeypatch.setattr(cfg, "get", lambda oid, sync=False: 10000)
    monkeypatch.setattr(cfg, "set",
                        lambda oid, value, cvt=None: sets.append((oid, value)))
    monkeypatch.setattr(_engine, "_cvt_int", lambda name: 6)
    phy = net.Iface("A", "eth0").phy
    assert phy.speed == 10000   # get -> speed_oper
    phy.speed = 25000           # set -> speed_admin
    assert sets[-1] == ("/agent:A/interface:eth0/phy:/speed_admin:", 25000)


def test_curated_phy_duplex_reads_oper_sets_admin(monkeypatch):
    from pyte import cfg, net
    sets = []
    monkeypatch.setattr(cfg, "get", lambda oid, sync=False: "full")
    monkeypatch.setattr(cfg, "set",
                        lambda oid, value, cvt=None: sets.append((oid, value)))
    phy = net.Iface("A", "eth0").phy
    assert phy.duplex == "full"  # get -> duplex_oper
    phy.duplex = "half"          # set -> duplex_admin
    assert sets[-1] == ("/agent:A/interface:eth0/phy:/duplex_admin:", "half")
