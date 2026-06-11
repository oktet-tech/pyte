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
from dataclasses import dataclass

from pyte import cfg
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


class Iface:
    """One /agent:X/interface:Y subtree (must be a grabbed resource)."""

    def __init__(self, agent: str, name: str):
        self.agent = agent
        self.name = name
        self._node = cfg.node(f"/agent:{agent}/interface:{name}")

    @property
    def oid(self) -> str:
        return self._node.oid

    @property
    def status(self) -> int:
        return self._node.child("status").value

    def up(self) -> None:
        self._node.child("status").value = 1

    def down(self) -> None:
        self._node.child("status").value = 0

    @property
    def mtu(self) -> int:
        return self._node.child("mtu").value

    @mtu.setter
    def mtu(self, value: int) -> None:
        self._node.child("mtu").value = int(value)

    @property
    def mac(self) -> str:
        return self._node.child("link_addr").value

    @property
    def addresses(self) -> list[tuple[str, int]]:
        out = []
        for n in cfg.find(f"{self.oid}/net_addr:*"):
            prefix = n.child("prefix").value
            out.append((n.name, int(prefix)))
        return out

    def addr_add(self, ip: str, prefix: int, broadcast: bool = True) -> None:
        from pyte._shim import lib
        check(lib.pyte_cfg_if_addr_add(_enc(self.agent), _enc(self.name),
                                       _enc(ip), prefix, broadcast),
              f"addr_add({ip}/{prefix})", CfgError)

    def addr_del(self, ip: str) -> None:
        cfg.delete(f"{self.oid}/net_addr:{ip}")

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
        out = []
        for n in cfg.find(f"/agent:{self.name}/route:*"):
            try:
                dst, prefix, opts = _parse_route_inst(n.name)
            except ValueError:
                continue          # unknown encoding: skip, don't crash
            gw = n.value or None
            dev = None
            try:
                dev = cfg.get(f"{n.oid}/dev:") or None
            except CfgError:
                pass
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
            for sub, static in (("neigh_dynamic", False),
                                ("neigh_static", True)):
                for n in cfg.find(f"{base}/{sub}:*"):
                    out.append(Neigh(n.name, str(n.value), ifn, static))
        return out

    def neigh_add(self, ip: str, mac: str, iface: str,
                  static: bool = True) -> None:
        from pyte._shim import lib
        raw = bytes(int(b, 16) for b in mac.split(":"))
        if len(raw) != 6:
            raise ValueError(f"bad MAC {mac!r}")
        check(lib.pyte_cfg_neigh_add(_enc(self.name), _enc(iface),
                                     _enc(ip), raw, static),
              f"neigh_add({ip})", CfgError)

    def neigh_del(self, ip: str, iface: str) -> None:
        from pyte._shim import lib
        check(lib.pyte_cfg_neigh_del(_enc(self.name), _enc(iface),
                                     _enc(ip)),
              f"neigh_del({ip})", CfgError)

    # -- sysctl ------------------------------------------------------------
    def sysctl(self, path: str) -> int | str:
        from pyte._shim import ffi, lib
        p = _sys_path(path)
        out = ffi.new("int *")
        rc = lib.pyte_cfg_sys_get_int(_enc(self.name), _enc(p), out)
        if rc == 0:
            return out[0]
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
