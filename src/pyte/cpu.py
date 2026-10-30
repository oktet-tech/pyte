# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""CPU threads of a test agent as TE resources.

DPDK applications want their own cores.  This module lists the CPU
threads the Configurator hardware tree reports for an agent, grabs
and releases them as ``/agent:X/rsrc:cpu:N:P:C:T`` resources (TE
refuses a thread somebody else holds), and picks N free threads,
preferably on the NUMA node a NIC is attached to.
"""
from __future__ import annotations

import dataclasses
from collections.abc import Iterable

from pyte import cfg
from pyte._util import shim_lib
from pyte.errors import CfgError, CpuError

_THREAD_PATTERN = "/agent:{}/hardware:/node:*/cpu:*/core:*/thread:*"


@dataclasses.dataclass(frozen=True, order=True)
class CpuId:
    """One CPU thread: NUMA node, package, core and thread indices."""

    node: int
    package: int
    core: int
    thread: int

    def oid(self, ta: str) -> str:
        """The hardware tree OID of this thread on agent ``ta``."""
        return (f"/agent:{ta}/hardware:/node:{self.node}"
                f"/cpu:{self.package}/core:{self.core}"
                f"/thread:{self.thread}")

    @property
    def rsrc_name(self) -> str:
        """The resource instance name used to grab this thread."""
        return (f"cpu:{self.node}:{self.package}:{self.core}"
                f":{self.thread}")


def _index(oid: str, kind: str) -> int:
    for part in oid.split("/"):
        name, _, value = part.partition(":")
        if name == kind:
            return int(value)
    raise ValueError(f"no {kind}: in {oid}")


def list_threads(ta: str) -> list[CpuId]:
    """All CPU threads of ``ta`` from the hardware tree, sorted."""
    return sorted(
        CpuId(_index(n.oid, "node"), _index(n.oid, "cpu"),
              _index(n.oid, "core"), _index(n.oid, "thread"))
        for n in cfg.find(_THREAD_PATTERN.format(ta)))


def pci_numa_node(pci_oid: str) -> int | None:
    """NUMA node of a PCI device, None when the agent does not know."""
    value = cfg.get(f"{pci_oid}/node:")
    if not value:
        return None
    return _index(str(value), "node")


def grab(ta: str, cpu: CpuId) -> None:
    """Grab ``cpu``; CpuError("busy") if anybody holds it already.

    As tapi_cfg_cpu_grab_by_id(): a thread this test holds (the rsrc
    is in the tree, or adding it fails EEXIST) is as busy as one
    another TE instance holds (the agent refuses the add with EPERM).
    """
    oid = f"/agent:{ta}/rsrc:{cpu.rsrc_name}"
    where = f"grab {cpu.rsrc_name} on {ta}"
    if cfg.exists(oid):
        raise CpuError("busy", where)
    try:
        cfg.add(oid, cpu.oid(ta))
    except CfgError as exc:
        lib = shim_lib()
        if exc.code in (lib.pyte_rc_error(lib.PYTE_EPERM),
                        lib.pyte_rc_error(lib.PYTE_EEXIST)):
            raise CpuError("busy", where) from exc
        raise


def release(ta: str, cpu: CpuId) -> None:
    """Release a thread previously grabbed with :func:`grab`."""
    cfg.delete(f"/agent:{ta}/rsrc:{cpu.rsrc_name}")


def _grab_on_node(ta: str, threads: list[CpuId], n: int) -> list[CpuId]:
    """Grab up to ``n`` threads of one node, one per core.

    Per core the lowest-numbered free thread wins, so thread 0 is
    preferred.  Returns what was grabbed (possibly fewer than ``n``).
    """
    got: list[CpuId] = []
    cores: dict[tuple[int, int], list[CpuId]] = {}
    for t in threads:
        cores.setdefault((t.package, t.core), []).append(t)
    try:
        for core_threads in cores.values():
            if len(got) == n:
                break
            for t in core_threads:
                try:
                    grab(ta, t)
                except CpuError:
                    continue
                got.append(t)
                break
    except BaseException:
        _release_all(ta, got)
        raise
    return got


def _release_all(ta: str, threads: list[CpuId]) -> None:
    """Release every thread, ignoring individual release failures."""
    for t in threads:
        try:
            release(ta, t)
        except CfgError:
            pass


def grab_n(ta: str, n: int, *, node: int | None = None,
           exclude: Iterable[CpuId] = ()) -> list[CpuId]:
    """Grab ``n`` free threads, all on one NUMA node, one per core.

    ``node`` is tried first, then every other node.  Busy threads and
    those in ``exclude`` are skipped.  Raises CpuError when no node
    has ``n`` free cores; nothing stays grabbed in that case.
    """
    skip = set(exclude)
    by_node: dict[int, list[CpuId]] = {}
    for t in list_threads(ta):
        if t not in skip:
            by_node.setdefault(t.node, []).append(t)
    order = sorted(by_node, key=lambda k: (k != node, k))
    for k in order:
        got = _grab_on_node(ta, by_node[k], n)
        if len(got) == n:
            return got
        _release_all(ta, got)
    where = "any node" if node is None else f"node {node}"
    raise CpuError(f"cannot grab {n} free CPU threads on {where}")
