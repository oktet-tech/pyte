# pyte.net — network configuration

`pyte.net` is a hybrid layer over `pyte.cfg`: where TE encodes real
logic in TAPI C functions (route/neighbor add/delete, address add,
sysctl access via `tapi_cfg_sys`) it goes through small shim wrappers
(`pyte_cfg_route_add` et al.); everything that is a plain Configurator
read/write (status, MTU, MAC, address/route/neighbor listings, single
address delete) is pure Python over the `/agent` tree.  IPv4 only.

```python
from pyte import net

agt = net.agent(t.agent)
for i in agt.ifaces:                 # grabbed interfaces only
    print(i.name, i.status, i.mtu, i.mac, i.addresses)

lo = agt.iface("lo")
lo.addr_add("192.0.2.1", prefix=32)  # shim; root needed
lo.addr_del("192.0.2.1")             # pure cfg.delete()

agt.routes()                          # [Route(dst, prefix, gw, dev, metric)]
agt.route_add("198.51.100.0/24", gw="192.0.2.254", metric=10)
agt.route_del("198.51.100.0/24", gw="192.0.2.254", metric=10)

agt.neighbors("lo")                   # [Neigh(ip, mac, iface, static)]
agt.neigh_add("192.0.2.9", "02:00:00:00:00:09", iface="lo")
agt.neigh_del("192.0.2.9", "lo")

agt.sysctl("net.ipv4.ip_forward")     # dotted or slashed paths
old = agt.sysctl_set("net.ipv4.ip_forward", 1)   # returns previous value

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
