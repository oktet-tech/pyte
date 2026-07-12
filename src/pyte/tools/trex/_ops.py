# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Agent-side op-functions shipped to the TRex host via pyte.remote.

Each function runs in the agent's python3 (started by pyte.remote). It
MUST be self-contained: all imports inside the body, no closures, no
module-level references, no calls to siblings here (helpers are nested
defs). Return values must be JSON-able; the live STLClient crosses back as
a RemoteObject (bootstrap) and is passed back in as ``cli``.
"""
from __future__ import annotations


def write_cfg(text):
    """Write the TRex cfg-YAML to a temp file on the agent; return its path."""
    import tempfile
    fd, path = tempfile.mkstemp(prefix="pyte_trex_", suffix=".yaml")
    import os
    with os.fdopen(fd, "w") as f:
        f.write(text)
    return path


def bootstrap(trex_lib_dir, server, sync_port, async_port, timeout):
    """Import the bundled STL client, connect (with retry), return it."""
    import sys
    import time
    if trex_lib_dir not in sys.path:
        sys.path.insert(0, trex_lib_dir)
    from trex.stl.api import STLClient
    c = STLClient(server=server, sync_port=sync_port, async_port=async_port)
    c.set_verbose("none")
    deadline = time.time() + timeout
    last = None
    while True:
        try:
            c.connect()
            return c
        except Exception as exc:   # server not up yet / transient
            last = exc
            if time.time() >= deadline:
                raise RuntimeError(
                    "STLClient.connect failed within %ss: %r"
                    % (timeout, last))
            time.sleep(0.5)


def reset(cli, ports):
    """Reset ports to a clean state (clear streams, set defaults)."""
    cli.reset(ports=ports)
    return {"ok": True}


def add_streams(cli, port, stream_specs):
    """Build native STLStreams from spec dicts; add to one port.

    The packet arrives as base64 wire bytes (built with Scapy on the
    engine) and is wrapped via STLPktBuilder(pkt_buffer=...): no Scapy
    parse and no eval of engine code on the agent. Only the optional VM
    (STLVm*, which exists solely in the trex lib) is evaluated here, in
    the trex.stl.api namespace. Returns the count of streams added.
    """
    import base64
    import trex.stl.api as _api
    from trex.stl.api import (STLStream, STLPktBuilder, STLTXCont,
                              STLTXSingleBurst, STLTXMultiBurst,
                              STLFlowStats, STLFlowLatencyStats)

    def _mode(m):
        if m["type"] == "continuous":
            kw = {}
            for k in ("pps", "bps_l2", "percentage"):
                if m.get(k) is not None:
                    kw[k] = m[k]
            return STLTXCont(**kw)
        if m["type"] == "single_burst":
            kw = {"total_pkts": m["total_pkts"]}
            if m.get("pps") is not None:
                kw["pps"] = m["pps"]
            return STLTXSingleBurst(**kw)
        if m["type"] == "multi_burst":
            kw = {"pkts_per_burst": m["pkts_per_burst"], "count": m["count"],
                  "ibg": m["ibg"]}
            if m.get("pps") is not None:
                kw["pps"] = m["pps"]
            return STLTXMultiBurst(**kw)
        raise ValueError("unknown TX mode: %r" % (m,))

    def _vm_expr(v):
        if not v.lstrip().startswith("STLVm"):
            raise ValueError("VM expression must start with STLVm: %r"
                             % (v,))
        # Empty __builtins__ is load-bearing: eval() with a globals
        # dict LACKING the key injects the full builtins module, which
        # would make the STLVm*-only containment above illusory.
        return eval(v, {"__builtins__": {}}, vars(_api))  # noqa: S307

    streams = []
    for spec in stream_specs:
        buf = base64.b64decode(spec["pkt_b64"])
        vm = ([_vm_expr(v) for v in spec["vm"]]
              if spec["vm"] else None)
        builder = STLPktBuilder(pkt_buffer=buf, vm=vm)
        fs = None
        if spec["pgid"] is not None:
            fs = (STLFlowLatencyStats(pg_id=spec["pgid"]) if spec["latency"]
                  else STLFlowStats(pg_id=spec["pgid"]))
        streams.append(STLStream(packet=builder, mode=_mode(spec["mode"]),
                                 name=spec["name"], flow_stats=fs))
    cli.add_streams(streams, ports=[port])
    return {"count": len(streams)}


def start(cli, ports, mult, duration, force):
    """Start traffic on ports at multiplier mult for duration seconds."""
    cli.start(ports=ports, mult=mult, duration=duration, force=force)
    return {"started": True}


def wait_on_traffic(cli, timeout):
    """Block until traffic stops (or timeout)."""
    cli.wait_on_traffic(timeout=timeout)
    return {"done": True}


def get_stats(cli, ports):
    """Return native get_stats() with string keys (JSON-able)."""
    s = cli.get_stats(ports=ports)
    return {str(k): v for k, v in s.items()}


def get_pgid_stats(cli, pg_ids):
    """Return native get_pgid_stats() for the given pg_ids."""
    return cli.get_pgid_stats(pg_ids=pg_ids)


def stop(cli, ports):
    """Stop traffic on ports."""
    cli.stop(ports=ports)
    return {"stopped": True}


def disconnect(cli):
    """Disconnect the STL client from the server."""
    cli.disconnect()
    return {"ok": True}
