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

from pyte._util import shim_lib as _shim_lib

from contextlib import contextmanager

from pyte import cfg


def _cvt_int(name: str) -> int:
    """Resolve a CVT name ("INT32") to its shim PYTE_CVT_* int."""
    lib = _shim_lib()
    return getattr(lib, f"PYTE_CVT_{name}")


def _check_access(access: str) -> str:
    """Validate a knob/collection access string; return it unchanged.

    Shared by _Knob and Collection so a typo (e.g. "raed_only") raises
    ValueError up front instead of silently behaving as read_write --
    Collection._writable/BoundCollection._writable only string-match
    the literal "read_only".
    """
    if access not in ("read_write", "read_only", "read_create"):
        raise ValueError(f"invalid access {access!r}")
    return access


class CfgObject:
    """A typed view of a Configurator subtree at a fixed base OID."""

    def __init__(self, oid: str):
        self.oid = oid

    @property
    def name(self) -> str:
        """The instance name: what follows ':' in the last OID segment."""
        last = self.oid.rsplit("/", 1)[-1]
        return last.split(":", 1)[1] if ":" in last else ""

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
            if not isinstance(knob, _Knob):
                raise TypeError(f"{a!r} is not a writable knob")
            if knob.access == "read_only":
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

    def __init__(self, subid: str, *, cvt_name: str | None = None,
                 access: str = "read_write", sync: bool = False):
        self.subid = subid
        self.access = _check_access(access)
        self.sync = sync  # volatile knobs re-read from the agent on get
        if cvt_name is not None:
            self.cvt_name = cvt_name  # overrides the subclass class default
        self.attr = subid  # replaced by __set_name__ when used as a class attr

    def __set_name__(self, owner, name: str) -> None:
        self.attr = name

    def _oid(self, obj: CfgObject) -> str:
        return f"{obj.oid}/{self.subid}:"

    def __get__(self, obj, owner=None):
        if obj is None:
            return self
        return self.from_cfg(cfg.get(self._oid(obj), sync=self.sync))

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

    cvt_name = "INT32"

    def to_cfg(self, value):
        return int(value)


class BoolKnob(_Knob):
    """Boolean knob (CVT_BOOL)."""

    cvt_name = "BOOL"

    def to_cfg(self, value):
        if isinstance(value, str):
            # bool("0") is True: a stringly bool silently inverts.
            raise TypeError(
                f"BoolKnob takes a bool, not the string {value!r}")
        return bool(value)


class DoubleKnob(_Knob):
    """Floating-point knob (CVT_DOUBLE)."""

    cvt_name = "DOUBLE"

    def to_cfg(self, value):
        return float(value)


class StrKnob(_Knob):
    """String knob (CVT_STRING)."""

    cvt_name = "STRING"

    def to_cfg(self, value):
        return str(value)


class AddrKnob(_Knob):
    """CVT_ADDRESS knob returning a plain string.

    CVT_ADDRESS is overloaded: the value may be an IP or a MAC
    (link-layer addresses such as link_addr).  Use IpAddrKnob only where
    the OID is known to carry an IP.
    """

    cvt_name = "ADDRESS"

    def to_cfg(self, value):
        # None clears the address (""); str(None) would write "None".
        return "" if value is None else str(value)


class IpAddrKnob(_Knob):
    """CVT_ADDRESS knob typed as ipaddress; only for IP-bearing OIDs."""

    cvt_name = "ADDRESS"

    def from_cfg(self, value):
        import ipaddress
        # An empty or unset address (None or "") yields None.
        return ipaddress.ip_address(value) if value else None

    def to_cfg(self, value):
        # Round-trip of from_cfg: an unset address reads as None, so
        # writing None back (e.g. saved() restore) must clear it, not
        # write the literal text "None".
        return "" if value is None else str(value)


class SelfKnob(_Knob):
    """A knob bound to the object's OWN value (its base OID).

    Use for an object that carries a scalar value AND has children, e.g.
    ``/agent/interface/net_addr:<ip>`` whose own value is the prefix
    length and which also has a ``broadcast`` child.  Unlike a normal
    knob it composes no ``/subid:`` segment.
    """

    def __init__(self, *, cvt_name: str | None = None,
                 access: str = "read_write", sync: bool = False):
        super().__init__("", cvt_name=cvt_name, access=access, sync=sync)

    def _oid(self, obj: CfgObject) -> str:
        return obj.oid


class SubObject:
    """A singleton child object (CVT none, empty instance name).

    Returns the child class bound to ``{parent oid}/{subid}:`` so the
    child's own knobs compose the real TE form, e.g. ``.../phy:/autoneg:``.
    """

    def __init__(self, subid: str, cls: type[CfgObject]):
        self.subid = subid
        self.cls = cls

    def __set__(self, obj, value):
        raise AttributeError(
            f"cannot assign to the container {self.subid!r}; assign to "
            f"one of its knobs instead (e.g. obj.{self.subid}.<knob>)")

    def __get__(self, obj, owner=None):
        if obj is None:
            return self
        return self.cls(f"{obj.oid}/{self.subid}:")


class Collection:
    """An instance-named child collection (e.g. net_addr, vlans, rule).

    ``access="read_only"`` models CM collections the agent populates
    itself (e.g. interface IRQs): add/del raise up front instead of
    failing deep in the agent.
    """

    def __init__(self, subid: str, cls: type[CfgObject],
                 access: str = "read_write"):
        self.subid = subid
        self.cls = cls
        self.access = _check_access(access)

    def __set__(self, obj, value):
        raise AttributeError(
            f"cannot assign to the container {self.subid!r}; use "
            f"obj.{self.subid}[name] / .add() instead")

    def __get__(self, obj, owner=None):
        if obj is None:
            return self
        return BoundCollection(obj.oid, self.subid, self.cls,
                               access=self.access)


class BoundCollection:
    """Children of one object under a fixed collection subid.

    Indexable (``coll[name]``), iterable (``for child in coll``),
    probeable (``name in coll``, ``coll.get(name)``) and — unless the
    CM declares the collection read-only — mutable
    (``coll.add(name, value)`` / ``del coll[name]``).
    """

    def __init__(self, parent_oid: str, subid: str, cls: type[CfgObject],
                 access: str = "read_write"):
        self._parent_oid = parent_oid
        self._subid = subid
        self._cls = cls
        self._access = access

    def _child_oid(self, name: str) -> str:
        return f"{self._parent_oid}/{self._subid}:{name}"

    def _writable(self, what: str) -> None:
        if self._access == "read_only":
            raise TypeError(
                f"collection {self._subid!r} is read-only; cannot {what}")

    def __getitem__(self, name: str) -> CfgObject:
        """Return the entry's typed view by name.

        Composes the OID but does NOT verify the entry exists (a later
        knob read does that).  Use ``name in coll`` / :meth:`get` to
        probe, or iterate to enumerate what actually exists.
        """
        return self._cls(self._child_oid(name))

    def __contains__(self, name: str) -> bool:
        return bool(cfg.find(self._child_oid(name)))

    def get(self, name: str, default=None):
        """The entry's typed view when it exists, else *default*."""
        if name in self:
            return self[name]
        return default

    def __iter__(self):
        for node in cfg.find(f"{self._parent_oid}/{self._subid}:*"):
            yield self._cls(node.oid)

    def add(self, name: str, value=None) -> CfgObject:
        self._writable(f"add {name!r}")
        cfg.add(self._child_oid(name), value)
        return self[name]

    def __delitem__(self, name: str) -> None:
        from pyte.errors import CfgNotFoundError
        self._writable(f"delete {name!r}")
        try:
            cfg.delete(self._child_oid(name), children=True)
        except CfgNotFoundError:
            raise KeyError(name) from None

    def __repr__(self) -> str:
        return (f"BoundCollection({self._parent_oid!r}, {self._subid!r}, "
                f"{self._cls.__name__})")
