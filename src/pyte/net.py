# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""High-level network configuration (tapi_cfg) over pyte.cfg.

Usage:
    from pyte import net
    agt = net.agent(t.agent)
    lo = agt.iface("lo")
    lo.addresses                # [("127.0.0.1", 8), ("::1", 128)]
    agt.routes()                # routing table snapshot
    agt.sysctl("net.ipv4.ip_forward")

Mutations (up/down, addr_add, route_add, neigh_add, sysctl_set) need a
root agent; on a non-root rig they raise CfgError (EPERM).
"""
from __future__ import annotations

import ipaddress
import re
from contextlib import contextmanager
from dataclasses import dataclass

from pyte import cfg, log
from pyte.cfg import SubObject
from pyte.cfg.gen.agent import Agent as _GenAgent
from pyte.cfg.gen.interface import Interface as _GenInterface
from pyte.cfg.gen.interface import Phy as _GenPhy
from pyte.cfg.gen.sys import Sys as _GenSys
from pyte.errors import CfgError, check
from pyte.log import _enc


def _parse_dst(spec: str) -> tuple[str, int]:
    """'10.0.0.0/24' -> (dst, prefix); bare IP -> host route."""
    if "/" in spec:
        ip, _, plen = spec.partition("/")
        prefix = int(plen)
    else:
        ip, prefix = spec, 32
    ipaddress.IPv4Address(ip)
    if not 0 <= prefix <= 32:
        raise ValueError(f"bad prefix in route spec {spec!r}")
    return ip, prefix


def _parse_route_inst(name: str) -> tuple[str, int, dict[str, str]]:
    """Decode a /agent/route instance name: 'dst|prefix[,k=v,...]'."""
    head, *opts = name.split(",")
    dst, sep, plen = head.partition("|")
    if not sep:
        raise ValueError(f"unexpected route instance name {name!r}")
    parsed = {}
    for opt in opts:
        k, _, v = opt.partition("=")
        parsed[k] = v
    return dst, int(plen), parsed


def _sys_path(path: str) -> str:
    """Accept dotted or slashed sysctl paths."""
    return path.replace(".", "/") if "/" not in path else path


_MAC_RE = re.compile(r"^[0-9a-fA-F]{2}(:[0-9a-fA-F]{2}){5}$")


def _parse_mac(mac: str) -> bytes:
    """Validate colon-separated MAC and return 6 raw bytes."""
    if not _MAC_RE.match(mac):
        raise ValueError(f"bad MAC address {mac!r}")
    return bytes(int(b, 16) for b in mac.split(":"))


@dataclass(frozen=True)
class Route:
    dst: str
    prefix: int
    gw: str | None
    dev: str | None
    metric: int | None

    @property
    def spec(self) -> str:
        return f"{self.dst}/{self.prefix}"


@dataclass(frozen=True)
class Neigh:
    ip: str
    mac: str
    iface: str
    static: bool


class Phy(_GenPhy):
    """Ergonomic PHY view.

    speed/duplex read the OPERATIONAL value and set the ADMINISTRATIVE
    one (the common test mental model); the raw speed_admin/speed_oper/
    duplex_admin/duplex_oper knobs remain available.
    """

    @property
    def speed(self) -> int:
        return self.speed_oper

    @speed.setter
    def speed(self, value: int) -> None:
        self.speed_admin = value

    @property
    def duplex(self) -> str:
        return self.duplex_oper

    @duplex.setter
    def duplex(self, value: str) -> None:
        self.duplex_admin = value


class Iface(_GenInterface):
    """One /agent:X/interface:Y subtree (must be a grabbed resource).

    Subclasses the generated Interface: typed knobs (mtu, status,
    link_addr, ...), sub-objects (phy, stats, ...) and collections
    (net_addr, vlans, ...) are inherited; this class adds the ergonomic
    helpers and the agent attribute.
    """

    phy = SubObject("phy", Phy)   # override: return the curated Phy

    def __init__(self, agent: str, name: str):
        super().__init__(agent, name)   # builds /agent:agent/interface:name
        self.agent = agent
        # Do NOT set self.name: CfgObject.name is a read-only property
        # (the inherited property yields the ifname from the OID).

    def up(self) -> None:
        self.status = 1

    def down(self) -> None:
        self.status = 0

    @property
    def mac(self) -> str:
        """The link-layer (MAC) address (alias for link_addr)."""
        return self.link_addr

    @property
    def addresses(self) -> list[tuple[str, int]]:
        """[(ip, prefix)]: the net_addr entry's own value is the prefix."""
        return [(na.name, na.value) for na in self.net_addr]

    def addr_add(self, ip: str, prefix: int, broadcast: bool = True) -> None:
        from pyte._shim import lib
        check(lib.pyte_cfg_if_addr_add(_enc(self.agent), _enc(self.name),
                                       _enc(ip), prefix, broadcast),
              f"addr_add({ip}/{prefix})", CfgError)

    def addr_del(self, ip: str) -> None:
        del self.net_addr[ip]

    def grab(self) -> None:
        """Grab this interface as the agent's rsrc (see cfg.grab_rsrc)."""
        cfg.grab_rsrc(self.agent, self.name, self.oid)

    def release(self) -> None:
        """Release this interface's rsrc (see cfg.release_rsrc)."""
        cfg.release_rsrc(self.agent, self.name)

    def __repr__(self):
        return f"<Iface {self.agent}/{self.name}>"


class AgentNet:
    """Network view of one test agent."""

    def __init__(self, name: str):
        self.name = name

    # -- interfaces ----------------------------------------------------
    @property
    def ifaces(self) -> list[Iface]:
        return [Iface(self.name, n.name)
                for n in cfg.find(f"/agent:{self.name}/interface:*")]

    def iface(self, name: str) -> Iface:
        return Iface(self.name, name)

    # -- routes ----------------------------------------------------------
    def routes(self) -> list[Route]:
        """Routing table snapshot.

        The agent reports only routes whose output interface is a
        grabbed resource and hides the kernel's local table
        (agents/unix/conf/route), so e.g. a lo-only rig sees an empty
        table. Plain pattern find, no sync — same as TE's own
        tapi_cfg_get_route_table().
        """
        out = []
        for n in cfg.find(f"/agent:{self.name}/route:*"):
            try:
                dst, prefix, opts = _parse_route_inst(n.name)
            except ValueError:
                log.warn(f"skipping route instance {n.name!r}")
                continue          # unknown encoding: skip, don't crash
            gw = n.value
            gw = None if gw in ("", "0.0.0.0", None) else gw
            dev = None
            try:
                dev = cfg.get(f"{n.oid}/dev:") or None
            except CfgError as e:
                from pyte import errors
                if e.code != errors.ENOENT:
                    raise
            metric = int(opts["metric"]) if "metric" in opts else None
            out.append(Route(dst, prefix, gw, dev, metric))
        return out

    def route_add(self, dst: str, gw: str | None = None,
                  dev: str | None = None, metric: int = 0) -> None:
        from pyte._shim import ffi, lib
        ip, prefix = _parse_dst(dst)
        check(lib.pyte_cfg_route_add(
                  _enc(self.name), _enc(ip), prefix,
                  _enc(gw) if gw else ffi.NULL,
                  _enc(dev) if dev else ffi.NULL, metric),
              f"route_add({dst})", CfgError)

    def route_del(self, dst: str, gw: str | None = None,
                  dev: str | None = None, metric: int = 0) -> None:
        from pyte._shim import ffi, lib
        ip, prefix = _parse_dst(dst)
        check(lib.pyte_cfg_route_del(
                  _enc(self.name), _enc(ip), prefix,
                  _enc(gw) if gw else ffi.NULL,
                  _enc(dev) if dev else ffi.NULL, metric),
              f"route_del({dst})", CfgError)

    # -- neighbors -------------------------------------------------------
    def neighbors(self, iface: str | None = None) -> list[Neigh]:
        ifaces = [iface] if iface else [i.name for i in self.ifaces]
        out = []
        for ifn in ifaces:
            base = f"/agent:{self.name}/interface:{ifn}"
            cfg.synchronize(base, subtree=True)
            for sub, static in (("neigh_dynamic", False),
                                ("neigh_static", True)):
                for n in cfg.find(f"{base}/{sub}:*"):
                    out.append(Neigh(n.name, str(n.value), ifn, static))
        return out

    def neigh_add(self, ip: str, mac: str, iface: str,
                  static: bool = True) -> None:
        from pyte._shim import lib
        raw = _parse_mac(mac)
        check(lib.pyte_cfg_neigh_add(_enc(self.name), _enc(iface),
                                     _enc(ip), raw, static),
              f"neigh_add({ip})", CfgError)

    def neigh_del(self, ip: str, iface: str) -> None:
        from pyte._shim import lib
        check(lib.pyte_cfg_neigh_del(_enc(self.name), _enc(iface),
                                     _enc(ip)),
              f"neigh_del({ip})", CfgError)

    # -- base ----------------------------------------------------------
    @property
    def base(self) -> _GenAgent:
        """Typed access to the agent-level scalar settings.

        e.g. ``agt.base.dir``, ``agt.base.uname.release``,
        ``agt.base.ip4_fw``.  Mirrors the ``tapi_cfg_base_*`` getters.
        """
        return _GenAgent(self.name)

    # -- sysctl ------------------------------------------------------------
    @property
    def sys(self) -> _GenSys:
        """Typed access to CM-registered /proc/sys settings.

        e.g. ``agt.sys.net.ipv4.ip_forward``.  For arbitrary /proc/sys
        paths not registered in the CM, use ``sysctl()``.
        """
        return _GenSys(self.name)

    def sysctl(self, path: str) -> int | str:
        from pyte._shim import ffi, lib
        p = _sys_path(path)
        out = ffi.new("int *")
        rc = lib.pyte_cfg_sys_get_int(_enc(self.name), _enc(p), out)
        if rc == 0:
            return out[0]
        u64out = ffi.new("uint64_t *")
        rc = lib.pyte_cfg_sys_get_uint64(_enc(self.name), _enc(p), u64out)
        if rc == 0:
            return int(u64out[0])
        sout = ffi.new("char **")
        check(lib.pyte_cfg_sys_get_str(_enc(self.name), _enc(p), sout),
              f"sysctl({path})", CfgError)
        try:
            return ffi.string(sout[0]).decode(errors="replace")
        finally:
            lib.pyte_free_string(sout[0])

    def sysctl_set(self, path: str, value: int | str) -> int | str:
        """Set and return the previous value (for cleanup restore)."""
        from pyte._shim import ffi, lib
        p = _sys_path(path)
        if isinstance(value, int):
            old = ffi.new("int *")
            check(lib.pyte_cfg_sys_set_int(_enc(self.name), _enc(p),
                                           value, old),
                  f"sysctl_set({path})", CfgError)
            return old[0]
        prev = self.sysctl(path)
        check(lib.pyte_cfg_sys_set_str(_enc(self.name), _enc(p),
                                       _enc(str(value))),
              f"sysctl_set({path})", CfgError)
        return prev

    def __repr__(self):
        return f"<AgentNet {self.name}>"


def agent(name: str) -> AgentNet:
    return AgentNet(name)


# -- /net topology operations (tapi_cfg_net, suite prologues) ----------

def net_remove_empty() -> None:
    """Remove /net networks with no nodes (tapi_cfg_net_remove_empty)."""
    from pyte._shim import lib
    check(lib.pyte_cfg_net_remove_empty(), "net.remove_empty", CfgError)


def net_reserve_all() -> None:
    """Reserve every /net node as an agent resource
    (tapi_cfg_net_reserve_all)."""
    from pyte._shim import lib
    check(lib.pyte_cfg_net_reserve_all(), "net.reserve_all", CfgError)


def net_all_up(force: bool = False) -> None:
    """Bring every /net node interface up (tapi_cfg_net_all_up)."""
    from pyte._shim import lib
    check(lib.pyte_cfg_net_all_up(1 if force else 0),
          f"net.all_up(force={force})", CfgError)


def net_delete_all_ip4() -> None:
    """Delete all IPv4 addresses on /net node interfaces
    (tapi_cfg_net_delete_all_ip4_addresses)."""
    from pyte._shim import lib
    check(lib.pyte_cfg_net_delete_all_ip4_addresses(),
          "net.delete_all_ip4", CfgError)


def net_all_assign_ip(af: str = "inet") -> None:
    """Assign subnets + node addresses to every /net (needs root TAs).

    Delegates to :func:`pyte.cfg.net_all_assign_ip` (same shim call).
    """
    cfg.net_all_assign_ip(af)


def net_update_pci_fn_to_interface() -> None:
    """Switch all /net nodes from PCI function to interface references
    (tapi_cfg_net_nodes_update_pci_fn_to_interface, all node types)."""
    from pyte._shim import lib
    check(lib.pyte_cfg_net_update_pci_fn_to_interface(),
          "net.update_pci_fn_to_interface", CfgError)


def alloc_net_addr(pool_oid: str) -> str:
    """Allocate the next IPv4 address from the subnet pool entry.

    pool_oid names the /net_pool entry (e.g. the OID behind a bound
    net's ip4 subnet); consecutive calls hand out consecutive
    addresses.
    """
    from pyte._shim import ffi, lib
    out = ffi.new("char **")
    check(lib.pyte_cfg_alloc_net_addr(_enc(pool_oid), out),
          f"net.alloc_net_addr({pool_oid})", CfgError)
    try:
        return ffi.string(out[0]).decode()
    finally:
        lib.pyte_free_string(out[0])


def if_add_net_addr(ta: str, ifname: str, addr: str, prefix: int) -> None:
    """Add an IPv4 address to an agent interface, no broadcast
    (tapi_cfg_base_if_add_net_addr with set_bcast=false)."""
    from pyte._shim import lib
    check(lib.pyte_cfg_if_addr_add(_enc(ta), _enc(ifname), _enc(addr),
                                   prefix, 0),
          f"net.if_add_net_addr({addr}/{prefix})", CfgError)


@contextmanager
def borrowed_iface(owner_agent: str, borrower_agent: str, name: str):
    """Temporarily move interface ``name`` between same-host agents.

    Typed sugar over ``cfg.borrowed_rsrc`` (see its docstring for the
    host-global-lock / exclusive-holder rationale and the unwind
    pairing guarantee).  After the grab the borrower's ``/agent:``
    mirror is re-synced: it was last synced before the interface was
    grabbed (e.g. when a managed agent was added), so the
    ``interface:`` subtree is not in the local DB yet.

    Yields the borrower's :class:`Iface`.
    """
    with cfg.borrowed_rsrc(name, owner_agent, borrower_agent,
                           f"interface:{name}"):
        cfg.synchronize(f"/agent:{borrower_agent}")
        yield Iface(borrower_agent, name)
