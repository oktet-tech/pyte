# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""SR-IOV virtual functions as Configurator PCI devices.

A suite prologue creates VFs on a physical function through the
``sriov:/num_vfs:`` knob, binds functions to the driver a test needs,
and gives each VF a deterministic MAC through ``ip link`` on the
agent.  Devices are passed around as their PCI OIDs, for example
``/agent:X/hardware:/pci:/device:0000:03:00.1``.
"""
from __future__ import annotations

from pyte import cfg
from pyte.cfg.gen.pci import Device
from pyte.errors import RpcError, SriovError

_SIDES = {"dut": 1, "peer": 2}


def bdf(pci_oid: str) -> str:
    """The PCI address (last ``device:`` instance) of ``pci_oid``."""
    name, _, value = pci_oid.rpartition("/")[2].partition(":")
    if name != "device" or not value:
        raise ValueError(f"not a PCI device OID: {pci_oid}")
    return value


def _hardware(pci_oid: str) -> str:
    ta = pci_oid.split("/")[1].partition(":")[2]
    return f"/agent:{ta}/hardware:"


def netdev(pci_oid: str) -> str | None:
    """The first netdev name of the function, None if it has none."""
    for entry in Device(pci_oid).net:
        return entry.value
    return None


def enable_vfs(pci_oid: str, n: int) -> list[str]:
    """Create ``n`` VFs on the PF and return their device OIDs.

    :raises SriovError: fewer than ``n`` VFs appeared in the tree.
    """
    pf = Device(pci_oid)
    pf.sriov.num_vfs = n
    cfg.synchronize(_hardware(pci_oid))
    vfs = sorted(
        (entry.value for entry in pf.sriov.vf),
        key=lambda oid: bdf(oid))
    if len(vfs) < n:
        raise SriovError(
            f"{pci_oid}: asked for {n} VFs, only {len(vfs)} appeared")
    return vfs


def disable_vfs(pci_oid: str) -> None:
    """Remove all VFs of the PF."""
    Device(pci_oid).sriov.num_vfs = 0
    cfg.synchronize(_hardware(pci_oid))


def bind(pci_oid: str, driver: str) -> None:
    """Bind the function to ``driver``; no-op if it already is."""
    dev = Device(pci_oid)
    if dev.driver == driver:
        return
    dev.driver = driver
    cfg.synchronize(_hardware(pci_oid))


def vf_set_mac(pco, pf_ifname: str, index: int, mac: str, *,
               trust: bool = True, spoofchk: bool = False) -> None:
    """Set the MAC, trust and spoofchk of VF ``index`` of a PF netdev.

    :raises SriovError: an ``ip link`` command failed on the agent.
    """
    base = f"ip link set dev {pf_ifname} vf {index}"
    for cmd in (f"{base} mac {mac}",
                f"{base} trust {'on' if trust else 'off'}",
                f"{base} spoofchk {'on' if spoofchk else 'off'}"):
        try:
            pco.sh(cmd)
        except RpcError as exc:
            out = getattr(exc, "output", "")
            raise SriovError(f"{cmd!r} failed: {exc} {out}".rstrip()) \
                from exc


def vf_mac_for(side: str, port: int, index: int) -> str:
    """Deterministic locally administered MAC of a VF.

    ``02:5a:<side>:<port>:<index>:01``, side 01 for "dut", 02 for
    "peer".
    """
    if side not in _SIDES:
        raise ValueError(f"side must be 'dut' or 'peer', not {side!r}")
    for what, val in (("port", port), ("index", index)):
        if not 0 <= val <= 0xFF:
            raise ValueError(f"{what} out of range: {val}")
    return f"02:5a:{_SIDES[side]:02x}:{port:02x}:{index:02x}:01"
