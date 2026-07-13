# pyte.env — tapi_env binding

`pyte.env` wraps `tapi_env`, TE's environment binding layer: it parses
a DSL env string declared in `package.xml` (the `env` session variable),
binds it against the `/net` Configurator tree, and gives tests named
PCOs, interfaces, addresses, hosts and subnets.

Env strings follow TE's grammar; a typical single-agent string looks
like:

```
'net':IUT{'iut_host'{{'pco_iut':IUT},if:'iut_if'}},'rpcs'='pco_iut'
```

Tester passes the value via the `env` parameter; `pyte._params` resolves
the `VAR.*` reference.

`t.env` is a lazy property on the running test: it binds the `env`
parameter on first access and is freed automatically at test end.  For
ad-hoc use: `pyte.env.Env.bind(cfg_str)` returns an `Env` that works
as a context manager.

Lookups are namespaced per kind (pco/addr/iface/net/host are separate
tapi_env lists), so a name only needs to be unique within its kind.
`'alias'='name'` pairs in the env string resolve transparently.
Missing names raise `EnvError`.

- `e.pco(name)` — returns a non-owning `RpcServer`; `destroy()` on
  it is a no-op; tapi_env owns the server and closes it on `e.close()`.
- `e.addr(name, port=None)` — returns a frozen `Addr(.ip, .family,
  .port, .pair)`.  `port=<RpcServer>` allocates a fresh unique port per
  call via the Configurator; no write-back into the env.  Ether
  addresses silently skip port allocation.
- `e.iface(name)` — returns `EnvIface(.name, .index, .agent)`;
  `.cfg_iface()` bridges to a `pyte.net.Iface`.
- `e.host(name="")` — TA name; `""` = the first host declared in the
  env string.
- `e.net(name="")` — `EnvNet(.ip4_subnet, .ip6_subnet)` where each
  field is a `"10.38.10.0/24"`-style string or `None` when no subnet of
  that family is assigned.  `""` = the first net declared in the env
  string.  `ENOENT` (net not found) raises; `ENODATA` (net found but no
  subnet for that family) stores `None`.

Infrastructure:

- `/net:net1` + `/net_pool:ip4`/`ip6` in `cs.conf`; the prologue
  attaches a subnet (single-agent rigs) or builds a veth peer2peer
  topology with full address assignment (two-agent rigs).
- `/local:/ip4_alien:` in `cs.conf` provides the alien address; without
  it tapi_env silently binds 0.0.0.0.

## PCO, interface and alias lookups

From the showcase test `ts/env/basic.py`:

```{literalinclude} /_snippets/env-basic.py
:language: python
```

## Address kinds and port allocation

From the showcase test `ts/env/addrs.py` (`pco` is used only as the
`port=` argument for allocating a fresh port per `t.env.addr()` call):

```{literalinclude} /_snippets/env-addrs.py
:language: python
```

## Two-agent environments

`ts/env/peer2peer.py` binds `pco_iut`/`pco_tst` and exchanges data
over a real socket between the two agents (`RpcSocket`/`SockType` come
from `pyte.rpc`; see that guide for socket operations); `sock_type`
comes from the test's `sock_type` parameter (`"stream"` or `"dgram"`)
and the test is `<req id="ROOT"/>`-gated:

```{literalinclude} /_snippets/env-peer2peer.py
:language: python
```
