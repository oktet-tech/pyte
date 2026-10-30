# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Unit tests for pyte.sriov against a dict-backed Configurator."""
import pytest

from pyte import cfg, sriov
from pyte.cfg import _engine
from pyte.errors import CfgError, RpcError, SriovError
from pyte.testing import fake_shim  # noqa: F401

PF = "/agent:A/hardware:/pci:/device:0000:03:00.0"
_CVT = {"INT32": 6, "BOOL": 1, "STRING": 10}


class FakeNode:
    def __init__(self, oid):
        self.oid = oid
        self.name = oid.rpartition(":")[2]


class FakeCfgState:
    def __init__(self, monkeypatch):
        self.store = {}
        self.syncs = []
        self.on_set = {}
        self.adds = []
        monkeypatch.setattr(cfg, "get", self.get)
        monkeypatch.setattr(cfg, "set", self.set)
        monkeypatch.setattr(cfg, "add", self.add)
        monkeypatch.setattr(cfg, "find", self.find)
        monkeypatch.setattr(cfg, "synchronize", self.synchronize)
        monkeypatch.setattr(_engine, "_cvt_int", lambda n: _CVT[n])

    def get(self, oid, sync=False):
        if oid not in self.store:
            raise CfgError(0x1234, f"get {oid}")
        return self.store[oid]

    def set(self, oid, value, cvt=None):
        self.store[oid] = value
        if oid in self.on_set:
            self.on_set[oid](value)

    def add(self, oid, value=None):
        if oid in self.store:
            raise CfgError(0x1234, f"add {oid}: exists")
        self.adds.append((oid, value))
        self.store[oid] = value

    def find(self, pattern):
        prefix = pattern.rstrip("*")
        return [FakeNode(o) for o in self.store
                if o.startswith(prefix) and o != pattern]

    def synchronize(self, oid, subtree=True):
        self.syncs.append(oid)

    def add_vfs(self, pf_bdf, n, reverse=False):
        for i in reversed(range(n)) if reverse else range(n):
            vf = f"0000:03:00.{i + 2}"
            fn = _fn(i)
            self.store[f"{PF}/sriov:/vf:{i}"] = fn
            self.store[fn] = f"/agent:A/hardware:/pci:/device:{vf}"


@pytest.fixture()
def fake_cfg(monkeypatch):
    return FakeCfgState(monkeypatch)


class FakePco:
    def __init__(self, fail_on=None):
        self.cmds = []
        self.fail_on = fail_on

    def sh(self, cmd):
        self.cmds.append(cmd)
        if cmd == self.fail_on:
            raise RpcError(0x7E03, "sh", output="RTNETLINK: no such vf")
        return ""


@pytest.fixture()
def fake_pco():
    return FakePco()


def test_bdf_from_device_oid():
    assert sriov.bdf(
        "/agent:A/hardware:/pci:/device:0000:03:00.1") == "0000:03:00.1"


def test_bdf_rejects_other_oids():
    with pytest.raises(ValueError):
        sriov.bdf("/agent:A/hardware:/pci:")


def test_netdev_first_entry_or_none(fake_cfg):
    assert sriov.netdev(PF) is None
    fake_cfg.store[f"{PF}/net:eth1"] = "eth1"
    assert sriov.netdev(PF) == "eth1"


def _fn(i):
    return f"/agent:A/hardware:/pci:/vendor:15b3/device:1018/instance:{i}"


def _enable_hook(fake_cfg, n_made, reverse=False):
    fake_cfg.on_set[f"{PF}/sriov:/num_vfs:"] = (
        lambda v: fake_cfg.add_vfs("0000:03:00.0", n_made, reverse))


def test_enable_vfs_returns_device_oids_in_order(fake_cfg):
    _enable_hook(fake_cfg, 2)
    vfs = sriov.enable_vfs(PF, 2)
    assert [sriov.bdf(v) for v in vfs] == ["0000:03:00.2", "0000:03:00.3"]
    assert fake_cfg.syncs == ["/agent:A/hardware:"]


def test_enable_vfs_orders_by_vf_index(fake_cfg):
    _enable_hook(fake_cfg, 12, reverse=True)
    vfs = sriov.enable_vfs(PF, 12)
    assert [sriov.bdf(v) for v in vfs] == [
        f"0000:03:00.{i + 2}" for i in range(12)]


def test_enable_vfs_grabs_each_function(fake_cfg):
    _enable_hook(fake_cfg, 2)
    sriov.enable_vfs(PF, 2)
    assert sorted(fake_cfg.adds) == [
        (f"/agent:A/rsrc:pci_fn:15b3:1018:{i}", _fn(i))
        for i in range(2)]


def test_enable_vfs_no_grab(fake_cfg):
    _enable_hook(fake_cfg, 2)
    sriov.enable_vfs(PF, 2, grab=False)
    assert fake_cfg.adds == []


def test_enable_vfs_short_is_error(fake_cfg):
    _enable_hook(fake_cfg, 1)
    with pytest.raises(SriovError, match="2 VFs, only 1"):
        sriov.enable_vfs(PF, 2)


def test_grab_fn_is_idempotent(fake_cfg):
    sriov.grab_fn(_fn(0))
    sriov.grab_fn(_fn(0))
    assert fake_cfg.adds == [
        ("/agent:A/rsrc:pci_fn:15b3:1018:0", _fn(0))]


def test_grab_fn_after_release_repoints(fake_cfg):
    rsrc = "/agent:A/rsrc:pci_fn:15b3:1018:0"
    sriov.grab_fn(_fn(0))
    sriov.release_fn(_fn(0))
    sriov.grab_fn(_fn(0))
    assert fake_cfg.store[rsrc] == _fn(0)
    assert len(fake_cfg.adds) == 1


def test_release_fn_empties_rsrc(fake_cfg):
    sriov.grab_fn(_fn(0))
    sriov.release_fn(_fn(0))
    assert fake_cfg.store["/agent:A/rsrc:pci_fn:15b3:1018:0"] == ""


def test_disable_vfs_zeroes_and_syncs(fake_cfg):
    sriov.disable_vfs(PF)
    assert fake_cfg.store[f"{PF}/sriov:/num_vfs:"] == 0
    assert fake_cfg.syncs == ["/agent:A/hardware:"]


def test_bind_sets_driver_and_syncs(fake_cfg):
    fake_cfg.store[f"{PF}/driver:"] = "ixgbe"
    sriov.bind(PF, "vfio-pci")
    assert fake_cfg.store[f"{PF}/driver:"] == "vfio-pci"
    assert fake_cfg.syncs == ["/agent:A/hardware:"]


def test_bind_noop_when_already_bound(fake_cfg):
    fake_cfg.store[f"{PF}/driver:"] = "vfio-pci"
    sriov.bind(PF, "vfio-pci")
    assert fake_cfg.syncs == []


def test_vf_set_mac_issues_three_commands(fake_pco):
    sriov.vf_set_mac(fake_pco, "eth1", 0, "02:5a:01:00:00:01")
    assert fake_pco.cmds == [
        "ip link set dev eth1 vf 0 mac 02:5a:01:00:00:01",
        "ip link set dev eth1 vf 0 trust on",
        "ip link set dev eth1 vf 0 spoofchk off"]


def test_vf_set_mac_flags_off_and_on(fake_pco):
    sriov.vf_set_mac(fake_pco, "eth1", 3, "02:5a:01:00:03:01",
                     trust=False, spoofchk=True)
    assert fake_pco.cmds[1:] == [
        "ip link set dev eth1 vf 3 trust off",
        "ip link set dev eth1 vf 3 spoofchk on"]


def test_vf_set_mac_wraps_rpc_error(fake_shim):  # noqa: F811
    pco = FakePco(fail_on="ip link set dev eth1 vf 0 trust on")
    with pytest.raises(SriovError) as exc:
        sriov.vf_set_mac(pco, "eth1", 0, "02:5a:01:00:00:01")
    assert "vf 0 trust on" in str(exc.value)
    assert "no such vf" in str(exc.value)
    assert len(pco.cmds) == 2


def test_vf_mac_for_is_distinct_per_side_port_index():
    assert sriov.vf_mac_for("dut", 0, 0) != sriov.vf_mac_for("peer", 0, 0)
    assert sriov.vf_mac_for("dut", 0, 0) == "02:5a:01:00:00:01"
    assert sriov.vf_mac_for("peer", 1, 10) == "02:5a:02:01:0a:01"


def test_vf_mac_for_rejects_bad_input():
    with pytest.raises(ValueError):
        sriov.vf_mac_for("other", 0, 0)
    with pytest.raises(ValueError):
        sriov.vf_mac_for("dut", 256, 0)
