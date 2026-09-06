# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.dpdk: agent preparation logic, no testbed.

Everything here runs against a monkeypatched pyte.cfg (dpdk.cfg is the
same module object the knob engine uses), a stub RPC server exposing
just .ta/.sh(), and the shared fake shim so pyte.log records instead of
emitting. vfio_configure()'s Module use is faked out too: what is
under test is the decision table, not the knob engine.
"""
import pytest

from pyte import dpdk
from pyte.dpdk import PciInfo
from pyte.errors import CfgNotFoundError, DpdkError
from pyte.testing import FakeShimLib


class FakeNode:
    """What cfg.find() yields: an OID plus the instance value."""

    def __init__(self, oid, value):
        self.oid = oid
        self.value = value


class FakeCfg:
    """Records get/set/find/synchronize; answers from ``values``."""

    def __init__(self, values=None, found=None):
        self.values = dict(values or {})
        self.found = dict(found or {})
        self.gets = []
        self.sets = []
        self.syncs = []

    def get(self, oid, sync=False):
        self.gets.append((oid, sync))
        value = self.values[oid]
        if isinstance(value, Exception):
            raise value
        return value

    def set(self, oid, value, cvt=None):
        self.sets.append((oid, value))

    def find(self, pattern):
        return self.found.get(pattern, [])

    def synchronize(self, oid, subtree=True):
        self.syncs.append(oid)


class FakePco:
    """The sliver of an RPC server pyte.dpdk uses."""

    def __init__(self, ta="Agt_A", out=""):
        self.ta = ta
        self.out = out
        self.cmds = []

    def sh(self, cmd):
        self.cmds.append(cmd)
        if isinstance(self.out, Exception):
            raise self.out
        return self.out


class FakeModule:
    """Records every module instance created and its loaded writes."""

    created = []

    def __init__(self, ta, name):
        self.ta = ta
        self.name = name
        self.loaded = 1
        FakeModule.created.append(self)


@pytest.fixture()
def fake_cfg(monkeypatch):
    def install(cfg):
        monkeypatch.setattr(dpdk, "cfg", cfg)
        return cfg
    return install


@pytest.fixture()
def fake_module(monkeypatch):
    FakeModule.created = []
    monkeypatch.setattr(dpdk, "Module", FakeModule)
    return FakeModule


# -- pci_info ----------------------------------------------------------

_PCI_PATTERN = "/agent:Agt_A/hardware:/pci:/device:*/net:*"
_PCI_OID = "/agent:Agt_A/hardware:/pci:/device:0000:03:00.0"


def test_pci_info_resolves_bdf_oid_and_driver(fake_cfg):
    fake_cfg(FakeCfg(
        values={"/agent:Agt_A/interface:eth1/deviceinfo:/drivername:":
                "i40e"},
        found={_PCI_PATTERN: [
            FakeNode(f"{_PCI_OID}/net:eth0", "eth0"),
            FakeNode(f"{_PCI_OID}/net:eth1", "eth1")]}))

    # Both net instances hang off the same device OID here, which is
    # what a multi-port lookup looks like: the value decides.
    assert dpdk.pci_info("Agt_A", "eth1") == PciInfo(
        bdf="0000:03:00.0", pci_oid=_PCI_OID, kernel_driver="i40e")


def test_pci_info_raises_when_no_device_carries_the_interface(fake_cfg):
    fake_cfg(FakeCfg(found={_PCI_PATTERN: [
        FakeNode(f"{_PCI_OID}/net:eth0", "eth0")]}))

    with pytest.raises(DpdkError,
                       match="no PCI device with net interface eth1 "
                             "on Agt_A"):
        dpdk.pci_info("Agt_A", "eth1")


# -- restore_driver ----------------------------------------------------

_INFO = PciInfo(bdf="0000:03:00.0", pci_oid=_PCI_OID, kernel_driver="i40e")


def test_restore_driver_tolerates_none(fake_cfg):
    """Cleanup calls it unconditionally, even before any resolution."""
    cfg = fake_cfg(FakeCfg())
    dpdk.restore_driver(None)
    assert cfg.gets == [] and cfg.sets == []


def test_restore_driver_is_a_noop_on_the_original_driver(fake_cfg,
                                                         fake_shim):
    cfg = fake_cfg(FakeCfg(values={f"{_PCI_OID}/driver:": "i40e"}))

    dpdk.restore_driver(_INFO)

    assert cfg.sets == [] and cfg.syncs == []
    assert fake_shim.logs == []


def test_restore_driver_rebinds_and_synchronizes(fake_cfg, fake_shim):
    cfg = fake_cfg(FakeCfg(values={f"{_PCI_OID}/driver:": "vfio-pci"}))

    dpdk.restore_driver(_INFO)

    assert cfg.sets == [(f"{_PCI_OID}/driver:", "i40e")]
    assert cfg.syncs == ["/agent:Agt_A/hardware:"]
    assert fake_shim.texts(FakeShimLib.TE_LL_RING) == [
        f"Binding {_PCI_OID} back to i40e"]


# -- hugepage_size_kb --------------------------------------------------

def test_hugepage_size_reads_meminfo_with_the_pinned_command():
    pco = FakePco(out="       2048 kB\n")

    assert dpdk.hugepage_size_kb(pco) == 2048
    assert pco.cmds == [
        "/bin/bash -o pipefail -c 'grep Hugepagesize /proc/meminfo "
        "| sed \"s/Hugepagesize://g\"'"]


def test_hugepage_size_unparseable_raises():
    pco = FakePco(out="not a number kB")
    with pytest.raises(DpdkError, match="cannot parse Hugepagesize"):
        dpdk.hugepage_size_kb(pco)


def test_hugepage_size_without_kb_suffix_warns_and_raises(fake_shim):
    """The unit is assumed by the arithmetic, so it must be confirmed."""
    pco = FakePco(out=" 2048 MB")

    with pytest.raises(DpdkError, match="'kB' suffix missing"):
        dpdk.hugepage_size_kb(pco)

    assert fake_shim.texts(FakeShimLib.TE_LL_WARN) == [
        "The suffix 'kB' was not found in ' 2048 MB'"]


# -- hugepages_set -----------------------------------------------------

def test_hugepages_set_divides_the_request_by_the_page_size(fake_cfg,
                                                            fake_shim):
    cfg = fake_cfg(FakeCfg())
    pco = FakePco(out=" 2048 kB")

    dpdk.hugepages_set(pco, 4096)

    assert cfg.sets == [("/agent:Agt_A/sys:/vm:/nr_hugepages:", 2048)]
    assert fake_shim.texts(FakeShimLib.TE_LL_RING) == [
        "Using 2048 nr_hugepages with size 2048 kB (total 4096 MB)"]


def test_hugepages_set_names_the_consumer_when_given(fake_cfg, fake_shim):
    fake_cfg(FakeCfg())

    dpdk.hugepages_set(FakePco(out=" 2048 kB"), 4096, what="TRex")

    assert fake_shim.texts(FakeShimLib.TE_LL_RING) == [
        "Using 2048 nr_hugepages with size 2048 kB for TRex "
        "(total 4096 MB)"]


def test_hugepages_set_with_huge_pages_rounds_down(fake_cfg, fake_shim):
    cfg = fake_cfg(FakeCfg())

    # 1 GiB pages: 4096 MB is 4 of them; a remainder is dropped.
    dpdk.hugepages_set(FakePco(out=" 1048576 kB"), 5000)

    assert cfg.sets == [("/agent:Agt_A/sys:/vm:/nr_hugepages:", 4)]


# -- vfio_configure ----------------------------------------------------

_IOMMU_OID = "/agent:Agt_A/hardware:/iommu:"
_NOIOMMU_OID = ("/agent:Agt_A/module:vfio/parameter:"
                "enable_unsafe_noiommu_mode")


def test_vfio_configure_with_iommu_only_loads_the_modules(
        fake_cfg, fake_module, fake_shim):
    cfg = fake_cfg(FakeCfg(values={_IOMMU_OID: "on"}))

    dpdk.vfio_configure("Agt_A")

    assert [m.name for m in fake_module.created] == ["vfio", "vfio-pci"]
    assert cfg.sets == []
    assert fake_shim.texts(FakeShimLib.TE_LL_RING) == [
        "iommu enabled on Agt_A"]


def test_vfio_configure_loads_an_unloaded_module(fake_cfg, monkeypatch,
                                                 fake_shim):
    fake_cfg(FakeCfg(values={_IOMMU_OID: "on"}))

    class Unloaded(FakeModule):
        created = []

        def __init__(self, ta, name):
            super().__init__(ta, name)
            self.loaded = 0
            Unloaded.created.append(self)

    Unloaded.created = []
    monkeypatch.setattr(dpdk, "Module", Unloaded)

    dpdk.vfio_configure("Agt_A")

    assert [m.loaded for m in Unloaded.created] == [1, 1]


def test_vfio_configure_without_iommu_sets_unsafe_mode(
        fake_cfg, fake_module, fake_shim):
    cfg = fake_cfg(FakeCfg(values={_IOMMU_OID: "off", _NOIOMMU_OID: "N"}))

    dpdk.vfio_configure("Agt_A")

    assert cfg.sets == [(_NOIOMMU_OID, "Y")]
    assert cfg.gets[-1] == (_NOIOMMU_OID, True)  # read with sync=True
    assert fake_shim.texts(FakeShimLib.TE_LL_RING) == [
        "iommu disabled on Agt_A",
        "trying to use unsafe no-iommu mode for vfio module"]


def test_vfio_configure_without_iommu_leaves_an_enabled_mode_alone(
        fake_cfg, fake_module, fake_shim):
    cfg = fake_cfg(FakeCfg(values={_IOMMU_OID: "off", _NOIOMMU_OID: "Y"}))

    dpdk.vfio_configure("Agt_A")

    assert cfg.sets == []
    assert fake_shim.texts(FakeShimLib.TE_LL_RING) == [
        "iommu disabled on Agt_A",
        "module parameter vfio/enable_unsafe_noiommu_mode is already "
        "set to Y"]


def test_vfio_configure_raises_when_the_parameter_is_missing(
        fake_cfg, fake_module, fake_shim):
    """A kernel without CONFIG_VFIO_NOIOMMU must fail loudly: returning
    would let the run continue and look like a success."""
    missing = CfgNotFoundError(FakeShimLib.PYTE_ENOENT, "cfg.get")
    fake_cfg(FakeCfg(values={_IOMMU_OID: "off", _NOIOMMU_OID: missing}))

    with pytest.raises(DpdkError,
                       match="no enable_unsafe_noiommu_mode module "
                             "parameter"):
        dpdk.vfio_configure("Agt_A")

    # vfio-pci is never loaded on that path.
    assert [m.name for m in fake_module.created] == ["vfio"]
    errors = fake_shim.texts(FakeShimLib.TE_LL_ERROR)
    assert errors == [
        "iommu is disabled on Agt_A, but the vfio module has no "
        "enable_unsafe_noiommu_mode parameter (the kernel lacks "
        "CONFIG_VFIO_NOIOMMU)"]


def test_vfio_configure_posts_no_verdict(fake_cfg, fake_module,
                                         fake_shim):
    """Whether a verdict belongs there is the caller's policy."""
    missing = CfgNotFoundError(FakeShimLib.PYTE_ENOENT, "cfg.get")
    fake_cfg(FakeCfg(values={_IOMMU_OID: "off", _NOIOMMU_OID: missing}))

    with pytest.raises(DpdkError):
        dpdk.vfio_configure("Agt_A")

    assert fake_shim.verdicts == []
