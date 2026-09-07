# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""tapi_env binding: named PCOs, addresses and interfaces.

Environments are declared in package.xml (the ``env`` parameter, TE's
DSL) and bound at runtime against the Configurator /net: tree.  Tests
normally use the lazily bound ``t.env``::

    with test.start() as t:
        iut = t.env.pco("pco_iut")          # RpcServer (env-owned)
        tst = t.env.pco("pco_tst")
        iut_if = t.env.iface("iut_if")      # .name/.index/.agent
        a = t.env.addr("iut_addr", port=iut)  # Addr with fresh port

Lookups are namespaced per kind (pco/addr/iface/net/host are separate
tapi_env lists), so a name only has to be unique within its kind;
'alias'='name' pairs in the env string resolve transparently.

The RpcServer objects returned by pco() are owned by tapi_env (closed
when the env is freed); destroy() on them is a no-op.
"""
from __future__ import annotations

from dataclasses import dataclass

from pyte._cleanup import cleanup_all
from pyte._util import shim as _shim, shim_lib as _shim_lib
from pyte.errors import ClosedResourceError, EnvError, check
from pyte._util import enc as _enc


# Shared impl in pyte._util; the local name stays for callers/tests.
from pyte._util import take_str as _take_str  # noqa: E402


@dataclass(frozen=True)
class Addr:
    """A named environment address."""
    ip: str          # IP text, or MAC text for ether addresses
    family: str      # "inet" | "inet6" | "ether"
    port: int        # 0 unless allocated via addr(..., port=pco)

    @property
    def pair(self) -> tuple[str, int]:
        """(ip, port) for the pyte.rpc socket API."""
        return (self.ip, self.port)


@dataclass(frozen=True)
class EnvIface:
    """A named environment interface."""
    name: str        # OS interface name
    index: int       # ifindex
    agent: str       # TA it lives on

    def cfg_iface(self):
        """Bridge to a configurator-backed pyte.net.Iface."""
        import pyte.net
        return pyte.net.Iface(self.agent, self.name)


@dataclass(frozen=True)
class EnvNet:
    """Bound subnet information of an environment net."""
    ip4_subnet: str | None   # "10.38.10.0/24" or None
    ip6_subnet: str | None


class Env:
    """A bound tapi_env environment; create with Env.bind()."""

    def __init__(self, handle, cfg: str):
        self._h = handle
        self._cfg = cfg
        #: RpcServer wrappers handed out by pco(), keyed by C handle.
        #: Aliases must share one object: silent_pass depth is
        #: per-wrapper while rpcs->silent_pass is one shared C field.
        self._pcos: dict = {}

    @classmethod
    def bind(cls, cfg: str) -> "Env":
        """Parse + bind an environment configuration string."""
        ffi, lib = _shim()
        out = ffi.new("tapi_env **")
        check(lib.pyte_env_new(out), "env new", EnvError)
        rc = lib.pyte_env_get(_enc(cfg), out[0])
        if rc != 0:
            lib.pyte_env_free(out[0])
            raise EnvError(rc, f"env bind {cfg!r}")
        return cls(out[0], cfg)

    def close(self) -> None:
        """Free the environment (closes env-created RPC servers).

        Invalidates every PCO wrapper handed out first: tapi_env_free
        frees the underlying rcf_rpc_server, so a retained wrapper
        would otherwise hold a dangling pointer.
        """
        lib = _shim_lib()
        for srv in self._pcos.values():
            srv._h = None
        self._pcos.clear()
        if self._h is not None:
            h, self._h = self._h, None   # struct is freed even on error
            check(lib.pyte_env_free(h), "env free", EnvError)

    def __enter__(self) -> "Env":
        return self

    def _handle(self):
        """The live C handle; raises after close().

        host()/net() bypass tapi_env's own accessor for their default-
        name case and walk the env's host/net list directly in C
        (pyte_shim.c); a NULL env there is a segfault, not a checked
        error, so every lookup must go through this guard rather than
        pass self._h straight through.
        """
        if self._h is None:
            raise ClosedResourceError(
                f"env {self._cfg!r} is already closed")
        return self._h

    def __exit__(self, exc_type, exc, tb) -> bool:
        cleanup_all(self.close, primary=exc)
        return False

    # -- lookups -------------------------------------------------------
    def _miss(self, kind: str, name: str, rc: int):
        """Raise for a failed lookup: friendly ENOENT, else check()."""
        lib = _shim_lib()
        if lib.pyte_rc_error(rc) == lib.pyte_rc_error(lib.PYTE_ENOENT):
            raise EnvError(f"env has no {kind} {name!r} "
                           f"(env: {self._cfg})")
        check(rc, f"env {kind} {name!r}", EnvError)

    def pco(self, name: str):
        """The named RPC server (created by the env; env-owned)."""
        ffi, lib = _shim()
        from pyte.rpc.server import RpcServer
        out = ffi.new("rcf_rpc_server **")
        rc = lib.pyte_env_get_pco(self._handle(), _enc(name), out)
        if rc != 0:
            self._miss("pco", name, rc)
        handle = out[0]
        cached = self._pcos.get(handle)
        if cached is not None:
            return cached
        ta_out = ffi.new("char **")
        check(lib.pyte_rpc_server_ta_name(handle, ta_out),
              f"pco {name!r} ta", EnvError)
        srv = RpcServer(handle, _take_str(ta_out), name, owned=False)
        self._pcos[handle] = srv
        return srv

    def addr(self, name: str, port=None) -> Addr:
        """The named address; port=RpcServer allocates a fresh port.

        Each addr(name, port=pco) call allocates a fresh port via the
        Configurator; the returned Addr is frozen and never writes back
        into the env (unlike the C TEST_GET_ADDR macro).  For "ether"
        addresses no port slot exists and port= is silently ignored.
        """
        ffi, lib = _shim()
        ip_out = ffi.new("char **")
        fam_out = ffi.new("char **")
        port_out = ffi.new("int *")
        rc = lib.pyte_env_get_addr(self._handle(), _enc(name), ip_out,
                                   fam_out, port_out)
        if rc != 0:
            self._miss("addr", name, rc)
        # Decode C strings first so they are freed even if port alloc fails.
        ip = _take_str(ip_out)
        family = _take_str(fam_out)
        p = port_out[0]
        if port is not None and family != "ether":
            alloc = ffi.new("unsigned int *")
            check(lib.pyte_allocate_port(port._handle(), alloc),
                  f"allocate_port for {name!r}", EnvError)
            p = alloc[0]
        return Addr(ip=ip, family=family, port=p)

    def iface(self, name: str) -> EnvIface:
        """The named interface: OS name, ifindex, owning agent."""
        ffi, lib = _shim()
        n_out = ffi.new("char **")
        idx = ffi.new("unsigned int *")
        rc = lib.pyte_env_get_if(self._handle(), _enc(name), n_out, idx)
        if rc != 0:
            self._miss("interface", name, rc)
        ifname = _take_str(n_out)
        ta_out = ffi.new("char **")
        check(lib.pyte_env_get_if_ta(self._handle(), _enc(name), ta_out),
              f"env if {name!r} ta", EnvError)
        return EnvIface(name=ifname, index=idx[0],
                        agent=_take_str(ta_out))

    def host(self, name: str = "") -> str:
        """TA name of the named host ("" = the first host declared in
        the env string)."""
        ffi, lib = _shim()
        out = ffi.new("char **")
        rc = lib.pyte_env_get_host_ta(self._handle(), _enc(name), out)
        if rc != 0:
            self._miss("host", name, rc)
        return _take_str(out)

    def net(self, name: str = "") -> EnvNet:
        """Bound subnets of the named net ("" = the first net declared
        in the env string).

        ENOENT (net not found) raises EnvError; ENODATA (net found but
        no subnet of that family) stores None in the result field.
        """
        ffi, lib = _shim()
        subnets = []
        for v6 in (0, 1):
            s_out = ffi.new("char **")
            pfx = ffi.new("unsigned int *")
            rc = lib.pyte_env_get_net_subnet(self._handle(), _enc(name), v6,
                                             s_out, pfx)
            if rc == 0:
                subnets.append(f"{_take_str(s_out)}/{pfx[0]}")
            elif (lib.pyte_rc_error(rc)
                  == lib.pyte_rc_error(lib.PYTE_ENOENT)):
                self._miss("net", name, rc)
            elif (lib.pyte_rc_error(rc)
                  == lib.pyte_rc_error(lib.PYTE_ENODATA)):
                subnets.append(None)
            else:
                check(rc, f"env net {name!r}", EnvError)
        return EnvNet(ip4_subnet=subnets[0], ip6_subnet=subnets[1])

    def __repr__(self) -> str:
        return f"<Env {self._cfg!r}>"
