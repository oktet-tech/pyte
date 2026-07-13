# pyte.net — network configuration

`pyte.net` is a hybrid layer over `pyte.cfg`: where TE encodes real
logic in TAPI C functions (route/neighbor add/delete, address add,
sysctl access via `tapi_cfg_sys`) it goes through small shim wrappers
(`pyte_cfg_route_add` et al.); everything that is a plain Configurator
read/write (status, MTU, MAC, address/route/neighbor listings, single
address delete) is pure Python over the `/agent` tree.  IPv4 only.

## Read-only queries

`agt` below is `net.agent(t.agent)`, the wrapper over the current
test's agent (from the showcase test `ts/net/net_info.py`; `cfg` is
`pyte.cfg`, used here only to cross-check the parsed route count
against the raw tree):

```{literalinclude} /_snippets/net-info.py
:language: python
```

## Mutations — require a root agent

Adding/removing addresses and routes, changing MTU, and flipping
sysctls need a root agent.  `agt`/`lo` continue from the same
`net.agent(t.agent)` / `agt.iface("lo")` pair (from the showcase test
`ts/net/net_setup.py`, `<req id="ROOT"/>`):

```{literalinclude} /_snippets/net-setup.py
:language: python
```

Neighbor mutation and interface grab/release round out the API but
are not shown as showcase snippets here: static neighbors cannot be
added on `lo` (see the caveats below), and `Iface.grab()`/`release()`/
`net.borrowed_iface()` are exercised in the dynamic-agent showcase
(`ts/dynamic/managed_agent.py`), outside this guide's scope:

```python
agt.neighbors("lo")                   # [Neigh(ip, mac, iface, static)]
agt.neigh_add("192.0.2.9", "02:00:00:00:00:09", iface="lo")
agt.neigh_del("192.0.2.9", "lo")

lo.grab(); lo.release()               # /agent:X/rsrc: sugar over pyte.cfg
with net.borrowed_iface("Agt_A", "Agt_MGD", "lo") as lo:
    ...                               # lo temporarily moved to Agt_MGD
```

Caveats:

- Mutations (`up`/`down`, `mtu =`, `addr_add`, `route_add`,
  `neigh_add`, `sysctl_set`) need a root agent; on a non-root rig they
  raise `CfgError` (EPERM from the agent).
- Interfaces are visible only when grabbed as agent resources (the
  localhost rig grabs just `lo`), and only by an EXCLUSIVE holder;
  rsrc lock names are host-global across agents, so two same-host
  agents cannot both hold the same interface.  `Iface.grab()` /
  `Iface.release()` manage the `/agent:X/rsrc:` entry, and
  `net.borrowed_iface(owner, borrower, name)` temporarily moves an
  interface between same-host agents with correctly paired unwind
  (re-syncing the borrower's mirror).  The resource-type-agnostic
  layer lives in `pyte.cfg`: `grab_rsrc()`, `release_rsrc()` and the
  `borrowed_rsrc()` context manager (any OID can be a resource —
  build typed wrappers for PCI etc. on top of it).
- `sysctl()` tries the int read first and transparently falls back to
  string for non-numeric values (`tapi_cfg_sys` is typed, the kernel
  tree is not); `sysctl_set()` returns the previous value so cleanups
  can restore it.
- Route identity in the Configurator tree is `dst|prefix[,metric,tos]`;
  gw and dev do not participate in matching.  `route_del()` must repeat
  the metric (and tos, if set) used at add time; gw/dev are passed to
  the kernel lookup but do not affect which instance is deleted.
