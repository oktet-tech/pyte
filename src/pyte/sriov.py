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

from pyte import cfg, log
from pyte.cfg.gen.pci import Device
from pyte.errors import CfgError, RpcError, SriovError

_SIDES = {"dut": 1, "peer": 2}
#: What ip(8) prints when the PF driver lacks a VF knob (EOPNOTSUPP).
_NOT_SUPPORTED = "Operation not supported"
#: PF device OID -> the VF function OIDs enable_vfs() grabbed on it.
_grabbed: dict[str, list[str]] = {}


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


def _fn_rsrc(fn_oid: str) -> tuple[str, str]:
    """Agent name and ``pci_fn:...`` rsrc name of a function OID."""
    parts = fn_oid.split("/")[1:]
    agent = parts[0].partition(":")[2]
    names = [p.partition(":")[2] for p in parts[1:]]
    return agent, ":".join(["pci_fn"] + [n for n in names if n])


def grab_fn(fn_oid: str) -> None:
    """Grab a PCI function as ``/agent:X/rsrc:pci_fn:<v>:<d>:<i>``.

    ``fn_oid`` is the ``.../pci:/vendor:V/device:D/instance:I`` OID.
    No-op if the resource already points at it.
    """
    agent, name = _fn_rsrc(fn_oid)
    try:
        current = cfg.get(f"/agent:{agent}/rsrc:{name}")
    except CfgError:
        current = None  # no such rsrc yet: the first grab
    if current == fn_oid:
        return
    cfg.grab_rsrc(agent, name, fn_oid)


def release_fn(fn_oid: str) -> None:
    """Release the resource taken by :func:`grab_fn`."""
    agent, name = _fn_rsrc(fn_oid)
    cfg.release_rsrc(agent, name)


def enable_vfs(pci_oid: str, n: int, grab: bool = True) -> list[str]:
    """Create ``n`` VFs on the PF and return their device OIDs.

    The ``sriov:/vf:<index>`` leaves hold vendor/device/instance
    OIDs; the instance value is the device OID.  VFs come back in
    index order and, if ``grab`` is set, are grabbed as resources so
    a test may bind their driver; :func:`release_vfs` (and
    :func:`disable_vfs`) release them.

    :raises SriovError: fewer than ``n`` VFs appeared in the tree.
    """
    pf = Device(pci_oid)
    pf.sriov.num_vfs = n
    cfg.synchronize(_hardware(pci_oid))
    entries = sorted(pf.sriov.vf, key=lambda e: int(e.name))
    if len(entries) < n:
        raise SriovError(
            f"{pci_oid}: asked for {n} VFs, only {len(entries)} "
            "appeared")
    vfs = []
    for entry in entries:
        fn_oid = entry.value
        if grab:
            grab_fn(fn_oid)
            held = _grabbed.setdefault(pci_oid, [])
            if fn_oid not in held:
                held.append(fn_oid)
        vfs.append(cfg.get(fn_oid))
    return vfs


def vf_instances(pci_oid: str) -> list[str]:
    """The ``sriov:/vf:<i>`` instance OIDs of the PF, in index order.

    These are the values :func:`enable_vfs` resolves to device OIDs;
    nothing is created or grabbed here.
    """
    entries = sorted(Device(pci_oid).sriov.vf, key=lambda e: int(e.name))
    return [entry.value for entry in entries]


def _held(fn_oid: str) -> bool:
    """Whether the rsrc of :func:`grab_fn` points at ``fn_oid``."""
    agent, name = _fn_rsrc(fn_oid)
    try:
        return cfg.get(f"/agent:{agent}/rsrc:{name}") == fn_oid
    except CfgError:
        return False    # never grabbed: no such rsrc


def release_vfs(pci_oid: str) -> None:
    """Release every grabbed VF of the PF.

    The VFs are those the PF lists now (``sriov:/vf:*``), so a
    process that did not grab them (an epilogue after the prologue)
    releases them too, plus those :func:`enable_vfs` grabbed in this
    process.  A VF nobody holds is left alone.
    """
    fns = [entry.value for entry in Device(pci_oid).sriov.vf]
    fns += [f for f in _grabbed.pop(pci_oid, []) if f not in fns]
    for fn_oid in fns:
        if _held(fn_oid):
            release_fn(fn_oid)


def disable_vfs(pci_oid: str) -> None:
    """Release the VFs of the PF (:func:`release_vfs`), remove them."""
    release_vfs(pci_oid)
    Device(pci_oid).sriov.num_vfs = 0
    cfg.synchronize(_hardware(pci_oid))


def bind(pci_oid: str, driver: str) -> None:
    """Bind the function to ``driver``; no-op if it already is."""
    dev = Device(pci_oid)
    if dev.driver == driver:
        return
    dev.driver = driver
    cfg.synchronize(_hardware(pci_oid))


def _ip_link(pco, cmd: str, *, optional: bool = False) -> None:
    """Run an ``ip link`` command, its stderr in the output.

    *optional*: a knob the PF driver does not implement is logged
    and skipped instead of failing.
    """
    try:
        pco.sh(f"{cmd} 2>&1")
    except RpcError as exc:
        out = getattr(exc, "output", "") or ""
        if optional and _NOT_SUPPORTED in out:
            log.warn(f"{cmd!r}: not supported by the PF driver, "
                     "left as it is")
            return
        raise SriovError(f"{cmd!r} failed: {exc} {out}".rstrip()) \
            from exc


def vf_set_mac(pco, pf_ifname: str, index: int, mac: str, *,
               trust: bool | None = None,
               spoofchk: bool | None = None) -> None:
    """Set the MAC of VF ``index`` of a PF netdev, and the flags asked.

    ``trust`` and ``spoofchk`` are left as the driver has them when
    None.  A flag the PF driver does not implement (sfc EF10 has no
    ndo_set_vf_trust, so ``trust on`` fails "Operation not supported")
    is logged and skipped.

    :raises SriovError: setting the MAC failed, or a flag failed for
        another reason.
    """
    base = f"ip link set dev {pf_ifname} vf {index}"
    _ip_link(pco, f"{base} mac {mac}")
    for knob, value in (("trust", trust), ("spoofchk", spoofchk)):
        if value is not None:
            _ip_link(pco, f"{base} {knob} {'on' if value else 'off'}",
                     optional=True)


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
