# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Pythonic Configurator access.

Values cross the C boundary as text; the shim converts them using the
real instance type, and get() returns the value typed by its CVT.

Notes:
    - get() returns the value typed by its CVT: BOOL -> bool,
      DOUBLE -> float, integer CVTs -> int, NONE -> None,
      STRING/ADDRESS -> str.
    - CVT_ADDRESS values are plain strings: a portless IP
      (e.g. "192.0.2.1") or a MAC (e.g. "aa:bb:cc:dd:ee:ff" for
      link-layer addresses).  Use ipaddress.ip_address() at the call
      site when an IP object is wanted.
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

from pyte._util import shim as _shim, shim_lib as _shim_lib
from pyte.errors import CfgError, check
from pyte._util import enc as _enc

_INT_CVT_NAMES = ("INT8", "UINT8", "INT16", "UINT16",
                  "INT32", "UINT32", "INT64", "UINT64")


def _to_py_kind(value: str, kind: str):
    """Decode a shim text value into a Python value by kind.

    kind is one of: "none", "bool", "int", "float", "str".
    Pure: no shim access, so it is unit-testable without TE.
    """
    if kind == "none":
        return None
    if kind == "bool":
        return int(value) != 0
    if kind == "int":
        return int(value)
    if kind == "float":
        return float(value)
    return value  # "str": STRING, ADDRESS (IP or MAC), UNSPECIFIED


def _cvt_kind(cvt: int) -> str:
    """Map a shim PYTE_CVT_* int to the kind used by _to_py_kind."""
    lib = _shim_lib()
    if cvt == lib.PYTE_CVT_NONE:
        return "none"
    if cvt == lib.PYTE_CVT_BOOL:
        return "bool"
    if cvt == lib.PYTE_CVT_DOUBLE:
        return "float"
    if any(cvt == getattr(lib, f"PYTE_CVT_{n}") for n in _INT_CVT_NAMES):
        return "int"
    return "str"


def _take_str(out) -> str:
    """Decode and free a C-allocated char* held in a char** out-param."""
    ffi, lib = _shim()
    s = ffi.string(out[0]).decode("utf-8", errors="replace")
    lib.pyte_free_string(out[0])
    out[0] = ffi.NULL
    return s


def _get_type(oid: str) -> int:
    ffi, lib = _shim()
    out = ffi.new("int *")
    check(lib.pyte_cfg_get_type(_enc(oid), out),
          f"cfg type of {oid}", CfgError)
    return out[0]


def _raw_get(oid: str) -> tuple[str, int]:
    """Shim seam: return (text value, CVT int) for an instance.

    Isolated so get() is unit-testable by monkeypatching this.
    """
    ffi, lib = _shim()
    out = ffi.new("char **")
    t_out = ffi.new("int *")
    check(lib.pyte_cfg_get_str(_enc(oid), out, t_out),
          f"cfg get {oid}", CfgError)
    return _take_str(out), t_out[0]


def get(oid: str, sync: bool = False) -> bool | float | int | str | None:
    """Get an instance value, typed by its CVT.

    BOOL -> bool, DOUBLE -> float, integer CVTs -> int, NONE -> None,
    STRING/ADDRESS -> str (ADDRESS may be an IP or a MAC string).
    sync=True re-reads the instance from the agent before returning.
    """
    if sync:
        synchronize(oid, subtree=False)
    value, cvt = _raw_get(oid)
    return _to_py_kind(value, _cvt_kind(cvt))


def _raw_set(oid: str, cvt: int, wire: str) -> None:
    """Shim seam: set an existing instance to `wire` as CVT `cvt`."""
    lib = _shim_lib()
    check(lib.pyte_cfg_set_str(_enc(oid), cvt, _enc(wire)),
          f"cfg set {oid}={wire!r}", CfgError)


def set(oid: str, value, cvt: int | None = None) -> None:  # noqa: A001
    """Set an existing instance.

    If cvt is given (a PYTE_CVT_* int) the object-type lookup is skipped;
    otherwise it is read from the object descriptor.
    """
    if cvt is None:
        cvt = _get_type(oid)
    if isinstance(value, bool):
        value = int(value)
    # None clears the value ("" on the wire); str(None) would write
    # the literal text "None".
    _raw_set(oid, cvt, "" if value is None else str(value))


def add(oid: str, value=None) -> CfgNode:
    """Add an instance; value type is derived from the Python type."""
    ffi, lib = _shim()

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
            t, wire = lib.PYTE_CVT_BOOL, _enc("1" if value else "0")
        elif isinstance(value, int):
            t, wire = lib.PYTE_CVT_INT32, _enc(str(value))
        elif isinstance(value, float):
            t, wire = lib.PYTE_CVT_DOUBLE, _enc(str(value))
        else:
            t, wire = lib.PYTE_CVT_STRING, _enc(str(value))

    handle = ffi.new("cfg_handle *")
    check(lib.pyte_cfg_add_str(_enc(oid), t, wire, handle),
          f"cfg add {oid}={value!r}", CfgError)
    return CfgNode(oid)


def delete(oid: str, children: bool = False) -> None:
    """Delete an instance (and optionally its children)."""
    lib = _shim_lib()
    check(lib.pyte_cfg_del(_enc(oid), 1 if children else 0),
          f"cfg delete {oid}", CfgError)


def find(pattern: str) -> list[CfgNode]:
    """Find instances by wildcard pattern, e.g. "/agent:A/env:*"."""
    ffi, lib = _shim()
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


def exists(oid: str) -> bool:
    """True iff the instance OID exists (an exact-OID find probe)."""
    return bool(find(oid))


def synchronize(oid: str, subtree: bool = True) -> None:
    """Re-read the (sub)tree state from the test agents."""
    lib = _shim_lib()
    check(lib.pyte_cfg_synchronize(_enc(oid), 1 if subtree else 0),
          f"cfg synchronize {oid}", CfgError)


def _backup_create() -> str:
    """Shim seam: snapshot the configuration; return the backup name."""
    ffi, lib = _shim()
    out = ffi.new("char **")
    check(lib.pyte_cfg_backup_create(out), "cfg backup create", CfgError)
    return _take_str(out)


def _backup_restore(name: str) -> None:
    """Shim seam: restore the named snapshot."""
    lib = _shim_lib()
    check(lib.pyte_cfg_backup_restore(_enc(name)),
          f"cfg backup restore {name}", CfgError)


def _backup_release(name: str) -> None:
    """Shim seam: release (free) the named backup."""
    lib = _shim_lib()
    check(lib.pyte_cfg_backup_release(_enc(name)),
          f"cfg backup release {name}", CfgError)


@contextmanager
def backup():
    """Snapshot the configuration; restore it on block exit.

    Restore runs whether the block succeeds or raises; the backup name
    is released afterwards.  This is TE's transactional rollback idiom.
    """
    name = _backup_create()
    try:
        yield name
    finally:
        try:
            _backup_restore(name)
        finally:
            _backup_release(name)


@contextmanager
def transaction():
    """Apply configuration changes with all-or-nothing rollback.

    Takes a configuration backup on entry.  Writes inside the block apply
    immediately (no batching).  On a clean exit the backup is released
    and the changes are KEPT; on ANY exception the backup is restored --
    rolling back every change made in the block -- and the exception
    propagates.

    Contrast with backup(), which ALWAYS restores on exit.  Batched /
    deferred-commit transactions are not provided: TE has no public API
    to abort a staged local-command sequence, so rollback-via-backup is
    the safe primitive.
    """
    name = _backup_create()
    ok = False
    try:
        yield
        ok = True
    finally:
        try:
            if not ok:
                _backup_restore(name)
        finally:
            _backup_release(name)


def wait_changes() -> None:
    """Wait for pending configuration changes to propagate to agents."""
    lib = _shim_lib()
    check(lib.pyte_cfg_wait_changes(), "cfg wait_changes", CfgError)


def grab_rsrc(agent: str, name: str, target_oid: str) -> CfgNode:
    """Grab ``target_oid`` as agent resource ``/agent:X/rsrc:name``.

    Resource locks matter beyond access control: the unix agent lists
    only objects it holds EXCLUSIVELY (shared-grabbed interfaces stay
    invisible), and lock names strip the ``/agent:`` prefix, so locks
    are host-global across agents on the same host.

    Re-entrant with :func:`release_rsrc`: releasing leaves the
    ``rsrc`` instance in place with an empty value, so a later grab
    of the same name re-points the existing instance instead of
    failing EEXIST on add.
    """
    oid = f"/agent:{agent}/rsrc:{name}"
    try:
        return add(oid, target_oid)
    except CfgError:
        # The instance already exists (a prior release_rsrc left it
        # empty): re-point it.  If add failed for another reason the
        # set fails too, chaining the add error as __context__.
        set(oid, target_oid)
        return CfgNode(oid)


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

    Standard ``finally`` semantics apply: if the body raises AND a
    release/restore step also raises during unwind, the unwind error
    replaces the body's exception (kept only as ``__context__``).
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


def net_all_assign_ip(af: str = "inet") -> None:
    """Assign subnets + node addresses to every /net (needs root TAs)."""
    if af not in ("inet", "inet6"):
        raise ValueError(f"af must be 'inet' or 'inet6', got {af!r}")
    lib = _shim_lib()
    check(lib.pyte_cfg_net_all_assign_ip(1 if af == "inet6" else 0),
          f"net_all_assign_ip({af})", CfgError)


def net_assign_subnet(net: str, af: str = "inet") -> None:
    """Attach a /net_pool subnet to /net:{net} without touching nodes.

    Root-free half of net_all_assign_ip(): enough for tapi_env
    fake/alien address allocation on rigs whose agents cannot add
    interface addresses.
    """
    if af not in ("inet", "inet6"):
        raise ValueError(f"af must be 'inet' or 'inet6', got {af!r}")
    lib = _shim_lib()
    check(lib.pyte_cfg_net_assign_subnet(_enc(net),
                                         1 if af == "inet6" else 0),
          f"net_assign_subnet({net}, {af})", CfgError)


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


from pyte.cfg._engine import (  # noqa: E402,F401 - public re-exports
    AddrKnob,
    BoolKnob,
    CfgObject,
    Collection,
    DoubleKnob,
    IntKnob,
    IpAddrKnob,
    SelfKnob,
    StrKnob,
    SubObject,
)
