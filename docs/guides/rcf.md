# pyte.rcf — RCF direct API

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
