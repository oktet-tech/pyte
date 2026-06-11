# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Pythonic Configurator access.

Values cross the C boundary as text; the shim converts them using the
real instance type, and get() converts integers back to int.

Notes:
    - CVT_ADDRESS values are portless IP strings (e.g. "192.0.2.1").
    - CVT_BOOL instances read back as int 0 or 1, not Python bool.
    - A literal ``*`` in a CfgSubtree name cannot be matched by
      iteration; ``*`` is reserved as a wildcard for find().

Usage::

    from pyte import cfg

    agt = cfg.agent("Agt_A")
    for iface in agt["interface"]:
        print(iface.name)
    lo = agt["interface"]["lo"]
    if lo.child("status").value != 1:
        ...
    cfg.add(f"/agent:Agt_A/env:DEMO", "value")
    cfg.set(f"/agent:Agt_A/env:DEMO", "other")
    cfg.delete(f"/agent:Agt_A/env:DEMO")
"""
from __future__ import annotations

import re
from contextlib import contextmanager

from pyte.errors import CfgError, check
from pyte.log import _enc

_INT_TYPES = ("BOOL", "INT8", "UINT8", "INT16", "UINT16",
              "INT32", "UINT32", "INT64", "UINT64")


def _take_str(out) -> str:
    """Decode and free a C-allocated char* held in a char** out-param."""
    from pyte._shim import ffi, lib
    s = ffi.string(out[0]).decode("utf-8", errors="replace")
    lib.pyte_free_string(out[0])
    return s


def _get_type(oid: str) -> int:
    from pyte._shim import ffi, lib
    out = ffi.new("int *")
    check(lib.pyte_cfg_get_type(_enc(oid), out),
          f"cfg type of {oid}", CfgError)
    return out[0]


def get(oid: str) -> str | int | None:
    """Get an instance value; integer types come back as int."""
    from pyte._shim import ffi, lib
    out = ffi.new("char **")
    t_out = ffi.new("int *")
    check(lib.pyte_cfg_get_str(_enc(oid), out, t_out),
          f"cfg get {oid}", CfgError)
    value = _take_str(out)
    t = t_out[0]
    if t == lib.PYTE_CVT_NONE:
        return None
    if any(t == getattr(lib, f"PYTE_CVT_{n}") for n in _INT_TYPES):
        return int(value)
    return value


def set(oid: str, value) -> None:  # noqa: A001 - deliberate cfg.set name
    """Set an existing instance; the type is taken from the object."""
    from pyte._shim import lib
    t = _get_type(oid)
    if isinstance(value, bool):
        value = int(value)
    check(lib.pyte_cfg_set_str(_enc(oid), t, _enc(str(value))),
          f"cfg set {oid}={value!r}", CfgError)


def add(oid: str, value=None) -> CfgNode:
    """Add an instance; value type is derived from the Python type."""
    from pyte._shim import ffi, lib

    # Try to look up the declared CVT from the object descriptor.  The
    # object OID has no instance names: strip every ":name" suffix so
    # "/agent:Agt_A/env:VAR" becomes "/agent:/env:".
    obj_oid = re.sub(r":[^/]*", ":", oid)
    t = None
    try:
        t = _get_type(obj_oid)
    except CfgError:
        pass  # Descriptor unavailable; fall back to the heuristic below.

    if t is not None and t != lib.PYTE_CVT_UNSPECIFIED:
        # Use the declared type; format value to match what pyte_cfg_put
        # expects for each CVT.
        if t == lib.PYTE_CVT_BOOL:
            wire = _enc("1" if value else "0")
        elif t == lib.PYTE_CVT_NONE:
            wire = b""
        else:
            wire = _enc(str(value) if value is not None else "")
    else:
        # Heuristic: derive type from the Python value type.
        if value is None:
            t, wire = lib.PYTE_CVT_NONE, b""
        elif isinstance(value, bool):
            t, wire = lib.PYTE_CVT_INT32, _enc(str(int(value)))
        elif isinstance(value, int):
            t, wire = lib.PYTE_CVT_INT32, _enc(str(value))
        else:
            t, wire = lib.PYTE_CVT_STRING, _enc(str(value))

    handle = ffi.new("cfg_handle *")
    check(lib.pyte_cfg_add_str(_enc(oid), t, wire, handle),
          f"cfg add {oid}={value!r}", CfgError)
    return CfgNode(oid)


def delete(oid: str, children: bool = False) -> None:
    """Delete an instance (and optionally its children)."""
    from pyte._shim import lib
    check(lib.pyte_cfg_del(_enc(oid), 1 if children else 0),
          f"cfg delete {oid}", CfgError)


def find(pattern: str) -> list[CfgNode]:
    """Find instances by wildcard pattern, e.g. "/agent:A/env:*"."""
    from pyte._shim import ffi, lib
    n = ffi.new("unsigned int *")
    handles = ffi.new("cfg_handle **")
    check(lib.pyte_cfg_find_pattern(_enc(pattern), n, handles),
          f"cfg find {pattern}", CfgError)
    nodes = []
    try:
        for i in range(n[0]):
            out = ffi.new("char **")
            check(lib.pyte_cfg_oid_str(handles[0][i], out),
                  f"cfg oid of match #{i} for {pattern}", CfgError)
            nodes.append(CfgNode(_take_str(out)))
    finally:
        lib.pyte_free_handles(handles[0])
    return nodes


def synchronize(oid: str, subtree: bool = True) -> None:
    """Re-read the (sub)tree state from the test agents."""
    from pyte._shim import lib
    check(lib.pyte_cfg_synchronize(_enc(oid), 1 if subtree else 0),
          f"cfg synchronize {oid}", CfgError)


def grab_rsrc(agent: str, name: str, target_oid: str) -> CfgNode:
    """Grab ``target_oid`` as agent resource ``/agent:X/rsrc:name``.

    Resource locks matter beyond access control: the unix agent lists
    only objects it holds EXCLUSIVELY (shared-grabbed interfaces stay
    invisible), and lock names strip the ``/agent:`` prefix, so locks
    are host-global across agents on the same host.
    """
    return add(f"/agent:{agent}/rsrc:{name}", target_oid)


def release_rsrc(agent: str, name: str) -> None:
    """Release agent resource ``/agent:X/rsrc:name`` (set it to "").

    The ``rsrc`` instance stays in place with an empty value; restore
    the resource by setting the instance back to the target OID.
    """
    set(f"/agent:{agent}/rsrc:{name}", "")


@contextmanager
def borrowed_rsrc(name: str, owner_agent: str, borrower_agent: str,
                  subpath: str):
    """Temporarily move a host-global resource between same-host agents.

    rsrc lock names strip the ``/agent:`` prefix, so locks are
    host-global across agents, and the unix agent lists only objects
    it holds EXCLUSIVELY — two same-host agents cannot both see the
    same interface: the owner must let go while the borrower uses it.

    Sequence: release owner -> grab borrower -> yield -> release
    borrower -> restore owner.  Each grab is paired with its own
    release/restore, nested so that a failure at any point unwinds
    exactly what was done (e.g. if the borrower grab fails, the owner
    is still restored).

    ``subpath`` is the per-agent OID tail (e.g. ``"interface:lo"``);
    the full ``/agent:{X}/{subpath}`` target is built only here.
    """
    set(f"/agent:{owner_agent}/rsrc:{name}", "")
    try:
        grab_rsrc(borrower_agent, name,
                  f"/agent:{borrower_agent}/{subpath}")
        try:
            yield
        finally:
            release_rsrc(borrower_agent, name)
    finally:
        set(f"/agent:{owner_agent}/rsrc:{name}",
            f"/agent:{owner_agent}/{subpath}")


def node(oid: str) -> CfgNode:
    """Wrap an OID string into a CfgNode."""
    return CfgNode(oid)


def agent(name: str) -> CfgNode:
    """The configuration subtree root of a test agent."""
    return CfgNode(f"/agent:{name}")


class CfgNode:
    """A single configuration instance identified by its OID."""

    def __init__(self, oid: str):
        self.oid = oid

    @property
    def name(self) -> str:
        """Instance name: what follows ':' in the last OID segment."""
        last = self.oid.rsplit("/", 1)[-1]
        return last.split(":", 1)[1] if ":" in last else ""

    @property
    def value(self):
        return get(self.oid)

    @value.setter
    def value(self, new_value) -> None:
        set(self.oid, new_value)

    def __getitem__(self, sub: str) -> CfgSubtree:
        return CfgSubtree(self, sub)

    def child(self, sub: str, name: str = "") -> CfgNode:
        return CfgNode(f"{self.oid}/{sub}:{name}")

    def add(self, sub: str, name: str = "", value=None) -> CfgNode:
        return add(f"{self.oid}/{sub}:{name}", value)

    def delete(self, children: bool = False) -> None:
        delete(self.oid, children)

    def __repr__(self) -> str:
        return f"CfgNode({self.oid!r})"


class CfgSubtree:
    """Children of one node under a fixed subobject name."""

    def __init__(self, parent: CfgNode, sub: str):
        self.parent = parent
        self.sub = sub

    def __iter__(self):
        return iter(find(f"{self.parent.oid}/{self.sub}:*"))

    def __getitem__(self, name: str) -> CfgNode:
        return self.parent.child(self.sub, name)

    def __repr__(self) -> str:
        return f"CfgSubtree({self.parent.oid!r}, {self.sub!r})"
