# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Knob engine: typed, attribute-style views over Configurator subtrees.

A CfgObject binds a base OID (TA + the instance names of the collection
levels above it).  Descriptors translate attribute access into pyte.cfg
calls on the composed OID:

    class Phy(CfgObject):
        speed_admin = IntKnob("speed_admin")
        autoneg     = BoolKnob("autoneg")

    class Interface(CfgObject):
        mtu      = IntKnob("mtu")
        phy      = SubObject("phy", Phy)
        net_addr = Collection("net_addr", NetAddr)
        def __init__(self, ta, ifname):
            super().__init__(f"/agent:{ta}/interface:{ifname}")

The engine reuses pyte.cfg: get() is already type-faithful, set() takes
the knob's CVT to skip the type round-trip.  The CM generator emits
exactly these shapes.
"""
from __future__ import annotations

from contextlib import contextmanager

from pyte import cfg


def _cvt_int(name: str) -> int:
    """Resolve a CVT name ("INT32") to its shim PYTE_CVT_* int."""
    from pyte._shim import lib
    return getattr(lib, f"PYTE_CVT_{name}")


class CfgObject:
    """A typed view of a Configurator subtree at a fixed base OID."""

    def __init__(self, oid: str):
        self.oid = oid

    @contextmanager
    def saved(self, *attrs: str):
        """Save the named knob attributes; restore them on block exit.

        Restore runs whether the block succeeds or raises, via the
        normal typed setters.  Every named attribute must be a writable
        knob: a read-only one raises TypeError up front, since restoring
        it would otherwise fail inside the finally and mask the real
        error.
        """
        for a in attrs:
            knob = getattr(type(self), a, None)
            if isinstance(knob, _Knob) and knob.access == "read_only":
                raise TypeError(f"cannot save read-only knob {a!r}")
        old = {a: getattr(self, a) for a in attrs}
        try:
            yield self
        finally:
            for a, value in old.items():
                setattr(self, a, value)

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.oid!r})"


class _Knob:
    """Descriptor base: an attribute backed by a leaf instance value."""

    cvt_name: str | None = None  # e.g. "INT32"; None -> cfg.set looks it up

    def __init__(self, subid: str, *, access: str = "read_write"):
        if access not in ("read_write", "read_only", "read_create"):
            raise ValueError(f"invalid access {access!r}")
        self.subid = subid
        self.access = access
        self.attr = subid  # replaced by __set_name__ when used as a class attr

    def __set_name__(self, owner, name: str) -> None:
        self.attr = name

    def _oid(self, obj: CfgObject) -> str:
        return f"{obj.oid}/{self.subid}:"

    def __get__(self, obj, owner=None):
        if obj is None:
            return self
        return self.from_cfg(cfg.get(self._oid(obj)))

    def __set__(self, obj, value) -> None:
        if self.access == "read_only":
            raise AttributeError(f"{self.attr!r} ({self.subid}) is read-only")
        cvt = None if self.cvt_name is None else _cvt_int(self.cvt_name)
        cfg.set(self._oid(obj), self.to_cfg(value), cvt=cvt)

    # Typed coercion hooks (overridden by subclasses).
    def from_cfg(self, value):
        return value

    def to_cfg(self, value):
        return value


class IntKnob(_Knob):
    """Integer-valued knob (defaults to CVT_INT32; pass cvt_name for others)."""

    def __init__(self, subid, *, cvt_name="INT32", access="read_write"):
        super().__init__(subid, access=access)
        self.cvt_name = cvt_name

    def to_cfg(self, value):
        return int(value)
