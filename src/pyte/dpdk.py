# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Host preparation for DPDK applications on a test agent.

What a DPDK-based tool (a traffic generator, a forwarder) needs done
on the machine it runs on, independent of the tool itself:

* PCI bookkeeping around a driver bind -- resolving an interface's PCI
  identity while it still has a netdev, and rebinding it to its
  original kernel driver afterwards (:func:`pci_info`,
  :func:`restore_driver`);
* hugepages (:func:`hugepage_size_kb`, :func:`hugepages_set`);
* the vfio kernel modules, IOMMU-enabled or not
  (:func:`vfio_configure`).

Everything here is a plain Configurator value change or an instance
the suite prologue created, so nothing needs explicit undoing: the
configuration backup restores it after the test.  The one exception is
a driver bind, which :func:`restore_driver` reverses.
"""
from __future__ import annotations

import dataclasses
import re

from pyte import cfg, log
from pyte.cfg.gen.module import Module
from pyte.errors import CfgNotFoundError, DpdkError

#: OID of the vfio module parameter enabling unsafe no-IOMMU mode.
_VFIO_UNSAFE_NOIOMMU_OID_FMT = \
    "/agent:{}/module:vfio/parameter:enable_unsafe_noiommu_mode"


# ---------------------------------------------------------------------
# PCI identity / driver restore
# ---------------------------------------------------------------------


@dataclasses.dataclass
class PciInfo:
    """Cached PCI identity of an interface, resolved before any bind.

    Holds the device's BDF, its Configurator OID and the kernel driver
    it was on, so that it can be rebound later without going through
    the netdev again.  Produced by :func:`pci_info`, consumed by
    :func:`restore_driver`.
    """

    bdf: str
    pci_oid: str
    kernel_driver: str


def pci_info(ta: str, ifname: str) -> PciInfo:
    """Resolve ``ifname``'s PCI OID/BDF and its current kernel driver.

    MUST be called before ``ifname`` is bound to a DPDK driver:
    resolution goes through the netdev, which disappears the moment the
    device is bound.  When the application is restarted repeatedly
    within one test, resolve once up front and cache the result,
    reusing it across all those restarts.

    :raises DpdkError: no PCI device carries that interface.
    """
    pci_oid = None
    for net in cfg.find(f"/agent:{ta}/hardware:/pci:/device:*/net:*"):
        if net.value == ifname:
            pci_oid = net.oid.rsplit("/net:", 1)[0]
            break
    if pci_oid is None:
        raise DpdkError(
            f"no PCI device with net interface {ifname} on {ta}")

    bdf = pci_oid.split("/device:", 1)[1]
    kernel_driver = cfg.get(
        f"/agent:{ta}/interface:{ifname}/deviceinfo:/drivername:")

    return PciInfo(bdf=bdf, pci_oid=pci_oid, kernel_driver=kernel_driver)


def restore_driver(info: PciInfo | None) -> None:
    """Rebind ``info``'s PCI device back to its original kernel driver.

    Deliberately tolerant of ``info`` being None so that cleanup can
    call it unconditionally, including when the test failed before the
    PCI identity was ever resolved.  :class:`PciInfo` is only ever
    constructed fully populated by :func:`pci_info`, so that single
    check covers every "nothing to restore" case.  Also a no-op when
    the device is already on its original driver.
    """
    if info is None:
        return

    driver = cfg.get(f"{info.pci_oid}/driver:")
    if driver == info.kernel_driver:
        return

    log.ring(f"Binding {info.pci_oid} back to {info.kernel_driver}")
    cfg.set(f"{info.pci_oid}/driver:", info.kernel_driver)

    ta = info.pci_oid.split("/")[1].partition(":")[2]
    cfg.synchronize(f"/agent:{ta}/hardware:")


# ---------------------------------------------------------------------
# Hugepages
# ---------------------------------------------------------------------

#: Pipefail'd shell pipeline reading the hugepage size out of
#: /proc/meminfo.  A plain Configurator read would be better, but no
#: /proc/meminfo-backed CM node exists yet.
_HUGEPAGE_SIZE_CMD = (
    "/bin/bash -o pipefail -c 'grep Hugepagesize /proc/meminfo "
    "| sed \"s/Hugepagesize://g\"'")

_HUGEPAGE_SIZE_RE = re.compile(r"\s*(-?\d+)")


def hugepage_size_kb(pco) -> int:
    """Read the agent's hugepage size in kB.

    Both a value that does not parse as a number and a missing "kB"
    suffix are errors: the unit is assumed by the caller's arithmetic,
    so it must be confirmed rather than guessed.

    :param pco: an RPC server on the agent to ask.
    :raises DpdkError: the size cannot be read as a positive kB value.
    """
    out = pco.sh(_HUGEPAGE_SIZE_CMD)
    m = _HUGEPAGE_SIZE_RE.match(out)
    if not m:
        raise DpdkError(f"cannot parse Hugepagesize from {out!r}")
    if "kB" not in out[m.end():]:
        log.warn(f"The suffix 'kB' was not found in '{out}'")
        raise DpdkError(f"'kB' suffix missing in {out!r}")
    size = int(m.group(1))
    if size <= 0:
        raise DpdkError(f"nonsensical Hugepagesize {size} kB in {out!r}")
    return size


def hugepages_set(pco, mem_mb: int, what: str | None = None) -> None:
    """Reserve ``mem_mb`` MiB of hugepage memory on ``pco``'s agent.

    nr_hugepages is ``mem_mb`` expressed in kB divided by the agent's
    hugepage size, written to ``/agent:<ta>/sys:/vm:/nr_hugepages:``.
    Nothing needs to undo this: it is a plain value change, restored
    from the configuration backup after the test.

    :param pco: an RPC server on the agent, used for the size read.
    :param mem_mb: hugepage memory to reserve, in MiB.
    :param what: what the memory is for, named in the log line only.
    """
    size_kb = hugepage_size_kb(pco)

    nr_hugepages = (mem_mb * 1024) // size_kb
    use = f" for {what}" if what else ""
    log.ring(f"Using {nr_hugepages} nr_hugepages with size {size_kb} "
             f"kB{use} (total {mem_mb} MB)")

    cfg.set(f"/agent:{pco.ta}/sys:/vm:/nr_hugepages:", nr_hugepages)


# ---------------------------------------------------------------------
# vfio
# ---------------------------------------------------------------------


def vfio_configure(ta: str) -> None:
    """Load and configure the vfio/vfio-pci kernel modules on ``ta``.

    The module instances themselves are expected to exist already
    (created, not loaded, by the suite prologue), so everything done
    here is a plain value change and is restored from the
    configuration backup after the test.  With IOMMU enabled there is
    nothing to do beyond loading the modules; with IOMMU disabled the
    vfio module's enable_unsafe_noiommu_mode parameter is set to Y
    (unless it already is).

    Failure policy when IOMMU is disabled: if that parameter does not
    exist at all -- the kernel was built without CONFIG_VFIO_NOIOMMU --
    this logs an error and raises :class:`~pyte.errors.DpdkError`
    instead of going on to load vfio-pci.  Raising is required rather
    than optional: DPDK cannot work here, so simply returning would
    let the run continue and look like a success.  Whether that also
    deserves a verdict is the caller's policy, not this function's.
    Any other failure reading the parameter is left uncaught and
    propagates as :class:`~pyte.errors.CfgError`, which is equally
    fatal.
    """
    vfio = Module(ta, "vfio")
    if vfio.loaded == 0:
        vfio.loaded = 1

    iommu = cfg.get(f"/agent:{ta}/hardware:/iommu:")
    if iommu == "on":
        log.ring(f"iommu enabled on {ta}")
    else:
        log.ring(f"iommu disabled on {ta}")

        noiommu_oid = _VFIO_UNSAFE_NOIOMMU_OID_FMT.format(ta)
        try:
            param_val = cfg.get(noiommu_oid, sync=True)
        except CfgNotFoundError as e:
            log.error(
                f"iommu is disabled on {ta}, but the vfio module has no "
                "enable_unsafe_noiommu_mode parameter (the kernel lacks "
                "CONFIG_VFIO_NOIOMMU)")
            raise DpdkError(
                f"{ta} has no enable_unsafe_noiommu_mode module "
                "parameter") from e

        if param_val == "Y":
            log.ring("module parameter vfio/enable_unsafe_noiommu_mode "
                     "is already set to Y")
        else:
            log.ring("trying to use unsafe no-iommu mode for vfio module")
            cfg.set(noiommu_oid, "Y")

    vfio_pci = Module(ta, "vfio-pci")
    if vfio_pci.loaded == 0:
        vfio_pci.loaded = 1
