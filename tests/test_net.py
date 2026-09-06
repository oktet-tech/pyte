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


def test_curated_phy_speed_round_trips_admin(monkeypatch):
    """speed reads back the value it just set, even if oper disagrees."""
    from pyte import cfg, net
    from pyte.cfg import _engine
    values = {"/agent:A/interface:eth0/phy:/speed_admin:": 10000,
              "/agent:A/interface:eth0/phy:/speed_oper:": 1000}
    monkeypatch.setattr(cfg, "get", lambda oid, sync=False: values[oid])
    monkeypatch.setattr(
        cfg, "set", lambda oid, value, cvt=None: values.__setitem__(oid, value))
    monkeypatch.setattr(_engine, "_cvt_int", lambda name: 6)
    phy = net.Iface("A", "eth0").phy
    phy.speed = 25000            # set -> speed_admin
    assert phy.speed == 25000    # get -> speed_admin (round-trips)
    assert phy.negotiated_speed == 1000   # get -> speed_oper (unaffected)


def test_curated_phy_duplex_round_trips_admin(monkeypatch):
    """duplex reads back the value it just set, even if oper disagrees."""
    from pyte import cfg, net
    values = {"/agent:A/interface:eth0/phy:/duplex_admin:": "full",
              "/agent:A/interface:eth0/phy:/duplex_oper:": "unknown"}
    monkeypatch.setattr(cfg, "get", lambda oid, sync=False: values[oid])
    monkeypatch.setattr(
        cfg, "set", lambda oid, value, cvt=None: values.__setitem__(oid, value))
    phy = net.Iface("A", "eth0").phy
    phy.duplex = "half"                       # set -> duplex_admin
    assert phy.duplex == "half"               # get -> duplex_admin (round-trips)
    assert phy.negotiated_duplex == "unknown"  # get -> duplex_oper (unaffected)


# -- AgentNet.base (generated agent scalars) --------------------------

def test_agentnet_base_is_typed_generated_agent():
    from pyte import net
    from pyte.cfg.gen.agent import Agent
    b = net.agent("A").base
    assert isinstance(b, Agent)
    assert b.oid == "/agent:A"


def test_agentnet_base_reads_scalar(monkeypatch):
    from pyte import cfg, net
    gets = []
    monkeypatch.setattr(cfg, "get",
                        lambda oid, sync=False: gets.append(oid) or "/tmp")
    val = net.agent("A").base.dir
    assert val == "/tmp"
    assert gets[-1] == "/agent:A/dir:"


def test_agentnet_base_uname_subobject(monkeypatch):
    from pyte import cfg, net
    monkeypatch.setattr(cfg, "get", lambda oid, sync=False: "Linux")
    u = net.agent("A").base.uname
    assert u.oid == "/agent:A/uname:"
    assert u.release == "Linux"   # /agent:A/uname:/release:


# -- link_ready() / await_link_up() / cpu_counts() ---------------------
#
# Configurator-only logic: a monkeypatched pyte.cfg is enough. Sleeps
# are monkeypatched out so the polling loop runs at full speed.


class _CfgStub:
    """Answers cfg.get() from a queue per OID; records find patterns."""

    def __init__(self, answers=None, found=None):
        self.answers = {oid: list(vals)
                        for oid, vals in (answers or {}).items()}
        self.found = dict(found or {})
        self.gets = []
        self.finds = []

    def get(self, oid, sync=False):
        self.gets.append((oid, sync))
        values = self.answers[oid]
        value = values.pop(0) if len(values) > 1 else values[0]
        if isinstance(value, Exception):
            raise value
        return value

    def find(self, pattern):
        self.finds.append(pattern)
        return self.found.get(pattern, [])


_OPER = "/agent:A/interface:eth0/oper_status:"
_PHY = "/agent:A/interface:eth0/phy:/state:"


@pytest.fixture()
def cfg_stub(monkeypatch):
    from pyte import net

    def install(stub):
        monkeypatch.setattr(net, "cfg", stub)
        return stub
    return install


@pytest.fixture()
def no_sleep(monkeypatch):
    from pyte import net
    slept = []
    monkeypatch.setattr(net.time, "sleep", slept.append)
    return slept


def test_link_ready_false_when_oper_status_is_down(cfg_stub):
    from pyte import net
    stub = cfg_stub(_CfgStub({_OPER: [0]}))
    assert net.agent("A").link_ready("eth0") is False
    # The PHY state is not even consulted.
    assert stub.gets == [(_OPER, True)]


def test_link_ready_true_when_phy_state_is_up(cfg_stub):
    from pyte import net
    cfg_stub(_CfgStub({_OPER: [1], _PHY: [1]}))
    assert net.agent("A").link_ready("eth0") is True


def test_link_ready_false_when_phy_state_is_not_up(cfg_stub):
    from pyte import net
    cfg_stub(_CfgStub({_OPER: [1], _PHY: [0]}))
    assert net.agent("A").link_ready("eth0") is False


def test_link_ready_reads_both_values_with_sync(cfg_stub):
    """Both reads must go to the agent, not to the cached tree."""
    from pyte import net
    stub = cfg_stub(_CfgStub({_OPER: [1], _PHY: [1]}))
    net.agent("A").link_ready("eth0")
    assert stub.gets == [(_OPER, True), (_PHY, True)]


def test_link_ready_true_when_the_interface_has_no_phy(cfg_stub,
                                                       fake_shim):
    """A bridge has no phy:/state: at all: oper_status alone decides."""
    from pyte import net
    from pyte.errors import CfgNotFoundError
    from pyte.testing import FakeShimLib

    missing = CfgNotFoundError(FakeShimLib.PYTE_ENOENT, "cfg.get")
    cfg_stub(_CfgStub({_OPER: [1], _PHY: [missing]}))
    assert net.agent("A").link_ready("eth0") is True


def test_link_ready_true_when_phy_state_is_unsupported(cfg_stub,
                                                       fake_shim):
    """Some drivers answer EOPNOTSUPP rather than "no such instance"."""
    from pyte import net
    from pyte.errors import CfgError

    unsupported = CfgError(0x51, "cfg.get")
    fake_shim.err_names[0x51] = b"EOPNOTSUPP"
    cfg_stub(_CfgStub({_OPER: [1], _PHY: [unsupported]}))
    assert net.agent("A").link_ready("eth0") is True


def test_link_ready_propagates_any_other_error(cfg_stub, fake_shim):
    from pyte import net
    from pyte.errors import CfgError

    boom = CfgError(0x52, "cfg.get")
    fake_shim.err_names[0x52] = b"EPERM"
    cfg_stub(_CfgStub({_OPER: [1], _PHY: [boom]}))
    with pytest.raises(CfgError):
        net.agent("A").link_ready("eth0")


def test_await_link_up_returns_on_the_first_check(cfg_stub, no_sleep):
    from pyte import net
    cfg_stub(_CfgStub({_OPER: [1], _PHY: [1]}))

    net.agent("A").await_link_up("eth0")

    # No wait before the first check; only the settle delay.
    assert no_sleep == [1.0]


def test_await_link_up_returns_on_the_nth_attempt(cfg_stub, no_sleep):
    from pyte import net
    cfg_stub(_CfgStub({_OPER: [0, 0, 1], _PHY: [1]}))

    net.agent("A").await_link_up("eth0", wait_s=0.5)

    # Two failed checks (one wait each), then up plus its settle wait.
    assert no_sleep == [0.5, 0.5, 1.0]


def test_await_link_up_rejects_a_flapping_link(cfg_stub, no_sleep):
    """Up, then down on the settle recheck: that attempt does not count."""
    from pyte import net
    stub = cfg_stub(_CfgStub({_OPER: [1, 0, 1, 1], _PHY: [1]}))

    net.agent("A").await_link_up("eth0")

    # 4 oper_status reads: up/down (attempt 0), then up/up (attempt 1).
    assert len([g for g in stub.gets if g[0] == _OPER]) == 4


def test_await_link_up_skips_the_recheck_when_asked(cfg_stub, no_sleep):
    from pyte import net
    cfg_stub(_CfgStub({_OPER: [1], _PHY: [1]}))

    net.agent("A").await_link_up("eth0", after_up_s=0)

    assert no_sleep == []


def test_await_link_up_times_out(cfg_stub, no_sleep):
    from pyte import net
    from pyte.errors import NetError

    stub = cfg_stub(_CfgStub({_OPER: [0]}))
    with pytest.raises(NetError, match="A/eth0: timed out waiting for "
                                       "the link to come up"):
        net.agent("A").await_link_up("eth0", checks=3)

    # The immediate check plus the three extra rounds.
    assert len(stub.gets) == 4
    assert no_sleep == [1.0, 1.0, 1.0]


def test_cpu_counts_counts_cores_and_threads(cfg_stub):
    from pyte import net
    cores = "/agent:A/hardware:/node:*/cpu:*/core:*"
    stub = cfg_stub(_CfgStub(found={cores: [1, 2, 3],
                                    f"{cores}/thread:*": [1, 2, 3, 4, 5,
                                                          6]}))

    assert net.agent("A").cpu_counts() == (3, 6)
    assert stub.finds == [cores, f"{cores}/thread:*"]


def test_cpu_counts_logs_nothing(cfg_stub, fake_shim):
    from pyte import net
    cfg_stub(_CfgStub(found={}))
    assert net.agent("A").cpu_counts() == (0, 0)
    assert fake_shim.logs == []
