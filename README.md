<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- Copyright (C) 2026 Konstantin Ushakov -->
# pyte — Python wrappers for the TE engine side

pyte lets you write TE tests in Python.  Tests are real Python
processes executed by Tester (argv `name=value` parameters, exit-code
contract — see `pyte.test.start()`), and they talk to the running Test
Engine through the same engine-side shared libraries C tests use:
RCF/RPC, Configurator, tapi_job and TAD.  The bridge is a small C shim
compiled as a cffi API-mode extension (`pyte._shim`) at `uv sync` time
against the TE installation pointed to by `TE_INSTALL`.  Zero TE
source changes.

Modules: `pyte.test` (lifecycle), `pyte.log`, `pyte.errors`,
`pyte.rpc` (RpcServer/RpcSocket/files/sh/expect_error), `pyte.cfg`
(CfgNode object model), `pyte.net` (interfaces/routes/neighbors/
sysctl), `pyte.job` (Job/Channel/Filter), `pyte.tad`
(layer DSL + Csap), `pyte.rcf` (agent inventory/files/restart/
dynamic TAs).

## Architecture

- **Shim** (`shim/pyte_shim.{c,h}` + `shim/pyte_shim_cdef.h`): every
  exported function returns `te_errno` and writes results through
  out-parameters.  TAPI code reports some failures by `longjmp` to the
  enclosing `TEST_START` frame — which does not exist in Python — so
  each wrapper body runs inside `PYTE_GUARD`, a trampoline that pushes
  a `tapi_jmp` point, confines any longjmp to that C frame and turns
  it into a `te_errno` return.
- **RPC handles** are permanently re-armed with `RPC_AWAIT_ERROR`
  before each call, so a failed remote call never longjmps; the Python
  facade (`RpcServer._check_call`) inspects the return value and the
  remote errno and raises `pyte.errors.RpcError` instead.
- **Errors**: Python checks every `te_errno` with
  `pyte.errors.check()`, raising `TeError`/`CfgError`/`RpcError`
  (`TimeoutError` for `TE_ETIMEDOUT`).
- **Lazy `_shim` imports rule**: Python modules import the extension
  with `from pyte._shim import ffi, lib` *inside* functions, never at
  module top level.  This keeps pure-Python parts (`pyte.tad.dsl`,
  `pyte._params`) importable and unit-testable without a built shim
  or a TE installation.
- **Configurator values cross as text**: the shim converts to/from
  the real `CVT_*` instance type; `pyte.cfg.get()` turns integer
  types back into `int`.
- **TAD**: `pyte.tad.dsl` is a Scapy-style layer DSL that compiles to
  NDN ASN.1 *text*; the shim parses it against the proper `ndn_*`
  type.  The exact text shapes were calibrated against TE's
  `asn_parse_value_text()` and are pinned by unit tests
  (`tests/test_tad_dsl.py`); use `pyte.tad.validate()` to check
  hand-written NDN text.
- **Packet ownership**: TE's receive callback hands each parsed
  packet (asn_value) to the callback owner, so the shim stores the
  pointer without copying and Python's `Packet` frees it via
  `pyte_pkt_free()` (explicitly or in `__del__`).

## pyte.net — network configuration

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

## pyte.rcf — RCF direct API

`pyte.rcf` talks to RCF itself (no RPC server needed): agent
inventory, engine<->agent file transfer, TA restart, log flush and
dynamic agent add/remove.

```python
from pyte import rcf

rcf.agents()                          # ["Agt_A", ...] running agents
agt = rcf.agent("Agt_A")
agt.type                              # "linux"
agt.info                              # AgentInfo(type, rcflib, confstr, flags)

agt.put_file("/local/path", "/remote/path")   # engine -> agent
agt.get_file("/remote/path", "/local/path")   # agent -> engine
agt.del_file("/remote/path")
agt.put_bytes(b"payload", "/remote/path")     # tempfile sugar
agt.get_bytes("/remote/path")

agt.flush_logs()                      # Logger pumps out the TA log now
agt.restart()                         # rcf_ta_reboot(RCF_REBOOT_TYPE_AGENT)

with rcf.add_agent("Agt_DYN") as dyn:          # extra agent at runtime
    dyn.put_bytes(b"x", "/tmp/probe")
# remove() ran on context exit

with rcf.add_agent("Agt_MGD", managed=True) as dyn:   # cfg-visible agent
    ...   # /agent:Agt_MGD exists; RPC servers, jobs and pyte.net work
```

Managed vs raw dynamic agents:

- `managed=True` registers the agent in the Configurator's `/rcf`
  subtree (`tapi_cfg_rcf_add_ta`): the Configurator itself starts the
  TA when the `status` node goes to 1 and synchronizes
  `/agent:<name>`, so the agent is first-class — visible in
  `cfg.find("/agent:*")`, usable with `RpcServer`, `pyte.job` and
  `pyte.net`.  Needs `cm_rcf.yml` registered in the rig's `cs.conf`.
  `remove()` first flips `/rcf:/agent:<name>/status:` to 0 (the only
  change the Configurator allows on a running `/rcf` agent; it stops
  the TA and syncs `/agent:<name>` away), then deletes the
  `/rcf:/agent:<name>` subtree.
- `managed=False` (default) adds the agent straight into RCF
  (`rcf_add_ta_unix`) — cheap and Configurator-invisible.  Good for
  RCF-level testing only (file ops, restart); anything that goes
  through cfg (RPC server creation reads `/agent:<name>/rpcprovider`)
  will not see the agent.
- Connection parameters become `/rcf:/agent:<name>/conf:<key>`
  instances; the keys mirror `conf/rcf.conf` (`host`, `port`, `user`,
  `key`, `sudo`, ...; see `engine/configurator/conf_rcf.c`).  An empty
  `host` means the engine host without SSH; `sudo` is presence-only
  (its value must be empty) and is accepted only with `managed=True`.

Caveats:

- `restart()` is refused by RCF for agents running on the engine host
  (`TE_EINVAL`) and for agents not marked rebootable (`TE_EPERM`).
  Only a remote agent added with `rebootable=True` (or configured with
  the `rebootable` attribute in the RCF config) can be restarted.
  `restart()` goes straight to RCF; the Configurator's view of that
  agent becomes stale (boot-state agent vs. old cfg tree).  TE's
  supported path for configured agents is `cfg_reboot_ta()`; pyte's
  `restart()` is intended for DYNAMIC agents that carry no Configurator
  state.
- `add_agent(host=None)` passes an empty rcfunix host, which starts
  the agent on the engine host without SSH — the same mechanism the
  localhost rig uses.  Such an agent is *not* restartable (see above).
  The listen port defaults to a random port below the Linux ephemeral
  range (20000–32000); collisions surface as slow add/connect failures.
- File operations run in RCF session 0 (the header's "TA session
  or 0"), serialized with other session-0 traffic.
- `flush_logs()` wraps `log_flush_ten()`, an IPC request that makes
  the Logger pump the TA's accumulated log into the run log.  It does
  NOT call `rcf_ta_get_log()` — that API is Logger-only and would
  divert the log bulk into a private file, losing it from the run log.
  `flush_logs()` is an IPC to the Logger — it works only inside a test
  run with the Logger alive; calling it outside a run raises `RcfError`.
- `remove()`/the `DynamicAgent` context manager deletes the agent
  from RCF; deleting an agent from the static RCF configuration is
  refused (`TE_EPERM`).

## Extending pyte (the pattern)

Worked example — how `rpc_listen()` was added:

1. **C wrapper** in `shim/pyte_shim.c`, declaration in
   `shim/pyte_shim.h`.  Guarded, te_errno + out-param, awaiting-error
   re-armed:

   ```c
   te_errno
   pyte_rpc_listen(rcf_rpc_server *rpcs, int s, int backlog, int *out)
   {
       RPC_AWAIT_ERROR(rpcs);
       PYTE_GUARD(*out = rpc_listen(rpcs, s, backlog));
       return 0;
   }
   ```

   `PYTE_GUARD`'s statement must not return early (see the macro
   comment in `pyte_shim.h`); use `PYTE_GUARD_RC` for calls that
   already return `te_errno`.

2. **cdef line** in `shim/pyte_shim_cdef.h` (kept in sync with the
   header, minus `extern`):

   ```c
   te_errno pyte_rpc_listen(rcf_rpc_server *rpcs, int s, int backlog,
                            int *out);
   ```

3. **Facade method** (here in `src/pyte/rpc/socket.py`) routing the
   trampoline status and the call result through `_check_call`:

   ```python
   def listen(self, backlog: int = 5) -> None:
       from pyte._shim import ffi, lib
       out = ffi.new("int *")
       rc = lib.pyte_rpc_listen(self.server._h, self.fd, backlog, out)
       self.server._check_call(rc, out[0], lambda v: v == 0,
                               f"listen({backlog})")
   ```

   Non-RPC wrappers just call `pyte.errors.check(rc, where)`.

4. **Rebuild** the extension:

   ```sh
   TE_INSTALL=/path/to/te/inst uv sync --reinstall-package pyte
   ```

5. **Test**: a unit test if the logic is pure Python, plus a showcase
   test in `ts/` for end-to-end behaviour.

## Known caveats

- uv caches editable builds: after any change under `shim/` rebuild
  with `uv sync --reinstall-package pyte`, plain `uv sync` will not
  recompile.
- Python signal handlers only run between bytecodes, so they do not
  fire while a C call blocks.  The SIGUSR1 "kill stuck test" handler
  installed by `test.start()` cannot preempt a blocked RPC call or
  CSAP/job receive — this is a design caveat of the shim approach.
- Received job data is text: TE's ta_job delivers messages as strings
  and truncates at interior NUL bytes, and `JobMessage.data` is
  UTF-8-decoded (errors replaced).  Send paths (`InputChannel.send`,
  `Csap.send`) are binary-safe, and received CSAP packet payloads come
  back as `bytes` (they cross RCF hex-encoded inside NDN text).
- `cfg`: `CVT_ADDRESS` values are portless IP strings
  (e.g. `"192.0.2.1"`); `CVT_BOOL` instances read back as int 0/1,
  not Python bool.
- The RCF session cache in `pyte.tad.csap._sessions` assumes agents
  live for the whole run; if an agent restarts, the cache must be
  cleared (or the test process restarted).
- Inside `RpcServer.expect_error()`, value-returning facade calls
  whose failure was swallowed return `None` (raw `_check_call` users
  see the `SUPPRESSED` sentinel).  This includes the open facades:
  `RpcServer.socket()`/`RpcSocket.open()` and
  `RpcServer.open()`/`open_file()` return `None`, not a wrapper
  around fd -1.
- `RpcSocket.setsockopt()` deliberately exposes a minimal int-valued
  option surface (currently `SO_REUSEADDR`).  To add an option:
  passthrough the `RPC_SO_*` constant from `te_rpc_sys_socket.h` as
  `PYTE_SO_*` in `shim/pyte_shim.h` + the cdef, then add a row to
  `_SOCKOPTS` in `src/pyte/rpc/socket.py`.
- `RpcServer.sleep()` is a remote shell `sleep` with RPC-timeout
  headroom: this TE has no `rpc_sleep()` RPC.
- `pyte.errors.check()` raises `pyte.errors.TimeoutError` for
  `TE_ETIMEDOUT` regardless of the exception class passed in.
- `pyte.tad.validate(text, kind)` wraps the shim's `pyte_asn_check()`
  dev/calibration helper; use it to sanity-check NDN text for the
  `from_asn`/`send_asn`/`listen(str)` escape hatches:

  ```python
  from pyte import tad
  tad.validate("{ layers { udp:{}, ip4:{} } }", "csap")
  tad.validate("{ pdus { udp:{ dst-port plain:9 } } }", "template")
  ```

  It raises `ValueError` with the failing symbol position on bad text
  (needs the built shim, but no agent).  Outside `test.start()` (e.g.
  in a REPL) expect harmless "Logging backend is unset" warnings from
  the jump-point bookkeeping.

## How to run

```sh
# Unit tests (no TE engine needed; pure-Python parts only)
uv run pytest lib/pyte/tests

# The showcase suite (from the repo root; builds TE + shim first)
./scripts/run.sh --cfg=localhost

# A subset
./scripts/run.sh --cfg=localhost --tester-run=python-ts/rpc/socket_echo

# Lint
uv run ruff check lib ts
```

Logs: `log.txt` in the directory you ran from; add `--log-html=DIR`
for a browsable version.  The raw log is `tmp_raw_log`.
