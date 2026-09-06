# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""TRex ASTF (stateful) API -- engine-side facade.

Mirrors trex.astf.api. The native bundled client runs agent-local:
session() launches ``t-rex-64 -i --astf`` as a tapi_job and drives a
native ASTFClient through a single pyte.remote python session on the
same agent (ZMQ over loopback -- only the RCF port is exposed). Every
Client method ships one self-contained op-function from
pyte.tools.trex._astf_ops, logs a readable step, and returns typed
stats.

This module owns the run's readability: the batch driver shows TRex's
raw stdout, while here the log shows the profile, its tunables, one
formatted progress line per poll, and a rendered summary.
"""
from __future__ import annotations

import os
import time
from contextlib import contextmanager
from typing import TYPE_CHECKING, Callable, Iterator

from pyte import log
from pyte.errors import RemotePythonError, TrexError
from pyte.tools.trex import _astf_ops as _ops
from pyte.tools.trex import _astf_stats as _stats
from pyte.tools.trex._config import ServerOpts

if TYPE_CHECKING:
    from pyte.rpc.server import RpcServer

#: Subpath of the TRex install dir holding the bundled ASTF client.
TREX_ASTF_PYLIB = "automation/trex_control_plane/interactive"
#: Default seconds to wait for the RPC server to accept a connection.
CONNECT_TIMEOUT = 30.0


class Client:
    """Engine-side handle to a connected, agent-local ASTF client."""

    def __init__(self, rem, cli, ports: list[int]):
        self._rem = rem
        self._cli = cli
        self._ports = list(ports)
        self._profile = None
        self._tg_names: list[str] | None = None

    def _call(self, fn, *args, timeout=None):
        try:
            return self._rem.call(fn, self._cli, *args, timeout=timeout)
        except RemotePythonError as exc:
            raise TrexError(f"{fn.__name__} failed: {exc}") from exc

    def reset(self) -> None:
        log.step_push("reset ASTF ports")
        self._call(_ops.reset)
        log.step_pop("reset done")

    def load_profile(self, text: str, name: str,
                     tunables: dict | None = None) -> None:
        """Ship a profile source to the agent and load it natively."""
        log.step_push(f"load ASTF profile {name!r}")
        if tunables:
            for key in sorted(tunables):
                log.ring(f"tunable {key}={tunables[key]}")
        else:
            log.ring("no tunables, profile defaults apply")
        try:
            path = self._rem.call(_ops.write_profile, text, ".py")
        except RemotePythonError as exc:
            log.step_pop("profile could not be written")
            raise TrexError(
                f"could not write profile {name!r} to the agent: "
                f"{exc}") from exc
        self._profile = path
        try:
            self._rem.call(_ops.load_profile, self._cli, path,
                           tunables or {})
        except RemotePythonError as exc:
            log.step_pop("profile load failed")
            raise TrexError(
                f"TRex rejected profile {name!r} with tunables "
                f"{tunables or {}}: {exc}") from exc
        log.step_pop(f"profile {name!r} loaded")

    def start(self, mult: float = 1.0, duration: float = -1.0,
              nc: bool = False, latency_pps: int = 0) -> None:
        log.step_push(f"start ASTF traffic: mult={mult} "
                      f"duration={duration} latency_pps={latency_pps}")
        self._call(_ops.start, mult, duration, nc, latency_pps)
        log.ring(f"trex: ASTF traffic started (mult={mult} "
                 f"duration={duration} latency_pps={latency_pps})")
        log.step_pop()

    def stop(self) -> None:
        log.step_push("stop ASTF traffic")
        self._call(_ops.stop)
        log.step_pop("stopped")

    def wait_on_traffic(self, timeout: float | None = None) -> None:
        log.step_push("wait_on_traffic (timeout="
                      f"{'inf' if timeout is None else timeout})")
        self._call(_ops.wait_on_traffic, timeout,
                   timeout=None if timeout is None else timeout + 30)
        log.step_pop("traffic finished")

    def clear_stats(self) -> None:
        self._call(_ops.clear_stats)

    def get_global(self) -> _stats.AstfGlobal:
        return _stats.parse_global(self._call(_ops.get_stats))

    def get_traffic(self) -> _stats.AstfTraffic:
        return _stats.parse_traffic(self._call(_ops.get_traffic_stats))

    def get_latency(self, ports: list[int] | None = None
                    ) -> dict[int, _stats.AstfLatency]:
        raw = self._call(_ops.get_latency_stats)
        ports = self._ports if ports is None else ports
        out = {}
        for p in ports:
            try:
                out[p] = _stats.parse_latency(raw, p)
            except (KeyError, TypeError):
                continue
        return out

    def get_template_stats(self) -> list[_stats.TemplateStats]:
        if self._tg_names is None:
            self._tg_names = self._call(_ops.get_tg_names)
        if not self._tg_names:
            return []
        return _stats.parse_tg_stats(
            self._call(_ops.get_tg_stats, self._tg_names))

    def poll(self, every: float = 1.0,
             until: Callable[[], bool] | None = None
             ) -> _stats.Series:
        """Sample until ``until()`` is false, RINGing one line a tick.

        Returns the accumulated Series, so callers never collect
        snapshots themselves.
        """
        series = _stats.Series()
        t0 = time.time()
        while until is None or until():
            glob = self.get_global()
            traffic = self.get_traffic()
            now = time.time() - t0
            series.add(_stats.Snapshot(t=now, glob=glob,
                                       traffic=traffic))
            log.ring(
                f"t={now:6.1f}s active={glob.active_flows} "
                f"est={glob.est_flows} "
                f"tx={glob.tx_bps / 1e9:.2f} Gbps/"
                f"{glob.tx_pps / 1e6:.2f} Mpps "
                f"rx={glob.rx_bps / 1e9:.2f} Gbps/"
                f"{glob.rx_pps / 1e6:.2f} Mpps "
                f"drops={traffic.drop_pct:.2f}%")
            if every:
                time.sleep(every)
        return series

    def log_summary(self, series: _stats.Series, t0: float,
                    t1: float) -> None:
        """RING a rendered end-of-run summary block."""
        log.step_push("ASTF run summary")
        log.ring(f"steady-state window {t0:.1f}s .. {t1:.1f}s")
        for attr, unit, scale in (("tx_bps", "Gbps", 1e9),
                                  ("rx_bps", "Gbps", 1e9),
                                  ("tx_pps", "Mpps", 1e6),
                                  ("rx_pps", "Mpps", 1e6),
                                  ("active_flows", "flows", 1.0)):
            log.ring(f"{attr}: mean "
                     f"{series.mean(attr, t0, t1) / scale:.3f} {unit}, "
                     f"median "
                     f"{series.median(attr, t0, t1) / scale:.3f} {unit}")
        traffic = self.get_traffic()
        log.ring(f"connections: attempted {traffic.connect_attempts}, "
                 f"established {traffic.connects}, "
                 f"closed {traffic.closes}, "
                 f"dropped {traffic.drops} "
                 f"({traffic.drop_pct:.2f}%)")
        for port, lat in sorted(self.get_latency().items()):
            log.ring(f"latency port {port}: avg {lat.avg:.1f}us, "
                     f"max {lat.max:.1f}us, jitter {lat.jitter:.1f}us, "
                     f"p95 {lat.percentile(95):.1f}us")
        errs = traffic.flow_table_errors()
        if errs:
            for name in sorted(errs):
                log.warn(f"flow table error {name}: {errs[name]}")
        else:
            log.ring("flow table errors: none")
        for tmpl in self.get_template_stats():
            log.ring(f"template {tmpl.name}: {tmpl.counters}")
        log.step_pop()


@contextmanager
def session(pco: "RpcServer", opts: ServerOpts,
            connect_timeout: float = CONNECT_TIMEOUT
            ) -> Iterator[Client]:
    """Launch ``t-rex-64 -i --astf`` on pco's agent, yield a Client.

    Bring-up: open one pyte.remote session, write the cfg-YAML, launch
    TRex as a tapi_job, then bootstrap the native ASTFClient over
    loopback. Teardown disconnects the client, removes the temp files
    and destroys the job on every exit path.
    """
    from pyte import remote
    from pyte.tools.trex import _ops as _stl_ops
    ports = list(range(len(opts.ports)))
    log.step_push(f"TRex ASTF: bring up on {pco.ta} "
                  f"({len(ports)} ports)")
    job = None
    popped = False
    try:
        with remote.python(pco) as rem:
            cfg_path = rem.call(_stl_ops.write_cfg, opts.cfg_yaml())
            log.ring(f"trex cfg: {cfg_path}")
            try:
                job = pco.job("/bin/sh",
                              ["-c", opts.shell_command(cfg_path)])
                job.stdout.log(level="RING")
                job.stderr.log(level="WARN")
                job.start()
                try:
                    cli = rem.call(
                        _ops.bootstrap,
                        os.path.join(opts.workdir, TREX_ASTF_PYLIB),
                        "127.0.0.1", opts.sync_port, opts.async_port,
                        connect_timeout,
                        timeout=connect_timeout + 15)
                except RemotePythonError as exc:
                    raise TrexError(
                        f"TRex ASTF server did not come up on "
                        f"{pco.ta}: {exc}") from exc
                log.ring("trex: ASTF client connected")
                log.step_pop(f"TRex ASTF ready on {pco.ta}")
                popped = True
                client = Client(rem, cli, ports)
                try:
                    yield client
                finally:
                    if client._profile is not None:
                        try:
                            rem.call(_ops.remove_file, client._profile)
                        except Exception:   # noqa: BLE001 teardown
                            pass
                    try:
                        rem.call(_ops.disconnect, cli)
                    except Exception:       # noqa: BLE001 teardown
                        pass
            finally:
                try:
                    rem.call(_stl_ops.remove_file, cfg_path)
                except Exception:           # noqa: BLE001 teardown
                    pass
    finally:
        if not popped:
            log.step_pop(f"TRex ASTF bring-up failed on {pco.ta}")
        if job is not None:
            job.destroy()
