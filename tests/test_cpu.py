# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Unit tests for pyte.cpu against a fake Configurator."""
import pytest

from pyte import cpu
from pyte.errors import CfgError
from pyte.testing import fake_shim  # noqa: F401

_EPERM = 0x7E03


class FakeNode:
    def __init__(self, oid):
        self.oid = oid
        self.value = None
        self.name = oid.rpartition(":")[2]


class FakeCfg:
    """Hardware tree plus rsrc add/delete with busy (EPERM) CPUs."""

    def __init__(self, nodes=2, cores=2, threads=2):
        self.oids = [
            cpu.CpuId(n, 0, c, t).oid("A")
            for n in range(nodes) for c in range(cores)
            for t in range(threads)]
        self.values = {}
        self.added = {}
        self.busy = set()
        self.deleted = []

    def find(self, pattern):
        assert pattern == (
            "/agent:A/hardware:/node:*/cpu:*/core:*/thread:*")
        return [FakeNode(o) for o in reversed(self.oids)]

    def get(self, oid, sync=False):
        return self.values[oid]

    def add(self, oid, value=None):
        if value in self.busy:
            raise CfgError(_EPERM, f"cfg add {oid}")
        self.added[oid] = value
        return FakeNode(oid)

    def delete(self, oid, children=False):
        self.deleted.append(oid)
        del self.added[oid]


@pytest.fixture()
def fake_cfg(monkeypatch, fake_shim):  # noqa: F811
    fake_shim.PYTE_EPERM = _EPERM
    fc = FakeCfg()
    monkeypatch.setattr(cpu, "cfg", fc)
    return fc


def test_list_threads_sorted(fake_cfg):
    ids = cpu.list_threads("A")
    assert ids[0] == cpu.CpuId(0, 0, 0, 0) and len(ids) == 8
    assert ids == sorted(ids)


def test_grab_n_prefers_requested_node_one_thread_per_core(fake_cfg):
    got = cpu.grab_n("A", 2, node=1)
    assert [c.node for c in got] == [1, 1]
    assert len({c.core for c in got}) == 2
    assert [c.thread for c in got] == [0, 0]
    assert (fake_cfg.added[f"/agent:A/rsrc:{got[0].rsrc_name}"]
            == got[0].oid("A"))


def test_grab_n_falls_back_to_other_node_when_busy(fake_cfg):
    fake_cfg.busy.update(
        c.oid("A") for c in cpu.list_threads("A") if c.node == 0)
    got = cpu.grab_n("A", 2, node=0)
    assert {c.node for c in got} == {1}


def test_grab_n_skips_exclude(fake_cfg):
    got = cpu.grab_n("A", 2, node=0, exclude=[cpu.CpuId(0, 0, 0, 0)])
    assert cpu.CpuId(0, 0, 0, 0) not in got
    assert {c.node for c in got} == {0}


def test_grab_n_releases_on_failure(fake_cfg):
    with pytest.raises(cpu.CpuError) as exc:
        cpu.grab_n("A", 5, node=0)
    assert "5" in str(exc.value) and "node 0" in str(exc.value)
    assert not fake_cfg.added


def test_grab_busy_is_cpu_error(fake_cfg):
    c = cpu.CpuId(0, 0, 0, 0)
    fake_cfg.busy.add(c.oid("A"))
    with pytest.raises(cpu.CpuError, match="busy"):
        cpu.grab("A", c)


def test_grab_other_error_propagates(fake_cfg, monkeypatch):
    def boom(oid, value=None):
        raise CfgError(0x7E99, "cfg add")
    monkeypatch.setattr(fake_cfg, "add", boom)
    with pytest.raises(CfgError):
        cpu.grab("A", cpu.CpuId(0, 0, 0, 0))


def test_release_deletes_rsrc(fake_cfg):
    c = cpu.grab_n("A", 1, node=0)[0]
    cpu.release("A", c)
    assert fake_cfg.deleted == [f"/agent:A/rsrc:{c.rsrc_name}"]


def test_pci_numa_node_parses_oid(fake_cfg):
    pci = "/agent:A/hardware:/pci:/device:0000:03:00.0"
    fake_cfg.values[pci + "/node:"] = "/agent:A/hardware:/node:1"
    assert cpu.pci_numa_node(pci) == 1


def test_pci_numa_node_empty_is_none(fake_cfg):
    pci = "/agent:A/hardware:/pci:/device:0000:03:00.0"
    fake_cfg.values[pci + "/node:"] = ""
    assert cpu.pci_numa_node(pci) is None


def test_grab_n_releases_on_unexpected_error(fake_cfg, monkeypatch):
    real_add = fake_cfg.add
    calls = []

    def flaky(oid, value=None):
        calls.append(oid)
        if len(calls) == 2:
            raise CfgError(0x7E99, "cfg add")
        return real_add(oid, value)
    monkeypatch.setattr(fake_cfg, "add", flaky)
    with pytest.raises(CfgError) as exc:
        cpu.grab_n("A", 2, node=0)
    assert not isinstance(exc.value, cpu.CpuError)
    assert not fake_cfg.added


def test_rollback_release_is_best_effort(fake_cfg, monkeypatch):
    real_delete = fake_cfg.delete
    first = []

    def bad_delete(oid, children=False):
        if not first:
            first.append(oid)
            raise CfgError(0x7E98, "cfg delete")
        real_delete(oid, children)
    monkeypatch.setattr(fake_cfg, "delete", bad_delete)
    with pytest.raises(cpu.CpuError):
        cpu.grab_n("A", 5, node=0)
    assert len(fake_cfg.added) == 1
