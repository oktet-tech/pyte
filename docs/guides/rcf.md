# pyte.rcf — RCF direct API

`pyte.rcf` talks to RCF itself (no RPC server needed): agent
inventory, engine<->agent file transfer, TA restart, log flush and
dynamic agent add/remove.

## Agent inventory and file transfer

`agt.type` (e.g. `"linux"`) and `agt.info` (`AgentInfo(type, rcflib,
confstr, flags)`) are simple metadata reads.  The showcase test
`ts/rcf/file_transfer.py` exercises the file-transfer and log-flush
surface (`t.agent` is the current test's agent name; `pco` is a
`t.rpc_server(...)` handle used only to verify the transferred size
from the agent side; `RcfError` is `pyte.errors.RcfError`, raised by
a second `del_file()` on an already-deleted remote path):

```{literalinclude} /_snippets/rcf-file-transfer.py
:language: python
```

`put_file(local, remote)` / `get_file(remote, local)` move an on-disk
file the same way `put_bytes`/`get_bytes` move an in-memory buffer
(via a temporary file).

## Restarting a remote agent

`restart()` (`rcf_ta_reboot(RCF_REBOOT_TYPE_AGENT)`) only works on a
remote agent added with `rebootable=True`.  From the showcase test
`ts/rcf/agent_restart.py` (`host` is a remote TA hostname, e.g. from
`TE_IUT`; the test itself skips outright when no remote host is
configured; the probe path is made unique with stdlib `os.getpid()`,
imported at the top of the test):

```{literalinclude} /_snippets/rcf-restart.py
:language: python
```

## Dynamic agents (raw)

`rcf.add_agent(name)` adds an extra agent straight into RCF —
Configurator-invisible, good for RCF-level testing only.  From the
showcase test `ts/rcf/dynamic_agent.py` (`cfg` is `pyte.cfg`, used
here just to observe that the Configurator does not know about the
agent):

```{literalinclude} /_snippets/rcf-dynamic-agent.py
:language: python
```

## Managed dynamic agents

`managed=True` makes a dynamic agent cfg-visible instead — no
in-scope showcase test exercises this path (it is demonstrated in
`ts/dynamic/managed_agent.py`), so the example stays hand-written:

```python
with rcf.add_agent("Agt_MGD", managed=True) as dyn:   # cfg-visible agent
    ...   # /agent:Agt_MGD exists; RPC servers, jobs and pyte.net work
```

Details:

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
