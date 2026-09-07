# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""TRex stateless (STL) API — engine-side facade.

Mirrors trex_stl_lib.api (connect/add_streams/start/get_stats/stop). The
native bundled client runs agent-local: session() launches ``t-rex-64 -i``
as a tapi_job and drives a native STLClient through a single pyte.remote
python session on the same agent (ZMQ over loopback — only the RCF port is
exposed). Every Client method ships one self-contained op-function from
pyte.tools.trex._ops, logs a readable step, and returns JSON / typed stats.
"""
from __future__ import annotations

import os
import time
from contextlib import contextmanager
from typing import TYPE_CHECKING, Iterator

from pyte import log
from pyte._cleanup import cleanup_all
from pyte.errors import RemotePythonError, TrexError
from pyte.tools.trex import _ops
from pyte.tools.trex._config import ServerOpts
from pyte.tools.trex._stats import (GlobalStats, LatencyStats, PortStats,
                                    parse_global_stats, parse_latency_stats,
                                    parse_port_stats)
from pyte.tools.trex._stream import Stream

if TYPE_CHECKING:
    from pyte.rpc.server import RpcServer

#: Subpath of the TRex install dir holding the bundled STL python client.
TREX_PYLIB = "automation/trex_control_plane/interactive"
#: Default seconds to wait for the RPC server to accept a connection.
CONNECT_TIMEOUT = 30.0
#: Extra seconds the pyte.remote transport is given on top of a native
#: wait, so the agent-side client is always the one that times out first
#: and can report *why* the traffic did not finish.
WAIT_MARGIN = 30.0


def _streams(streams) -> list[Stream]:
    if isinstance(streams, Stream):
        return [streams]
    return list(streams)


class Client:
    """Engine-side handle to a connected, agent-local STL client."""

    def __init__(self, rem, cli, ports: list[int]):
        self._rem = rem        # pyte.remote session (or a fake in tests)
        self._cli = cli        # RemoteObject: the live STLClient on the agent
        self._ports = list(ports)

    def _call(self, fn, *args, timeout=None):
        """Ship one op-function, translating remote failures to TrexError.

        *timeout* bounds the pyte.remote round trip; None leaves it at
        the session default, which is right for the short control ops
        but never for a wait (see :meth:`wait_on_traffic`).
        """
        try:
            return self._rem.call(fn, self._cli, *args, timeout=timeout)
        except RemotePythonError as exc:
            raise TrexError(f"{fn.__name__} failed: {exc}") from exc

    def reset(self, ports: list[int] | None = None) -> None:
        ports = self._ports if ports is None else ports
        log.step_push(f"reset ports {ports}")
        self._call(_ops.reset, ports)
        log.step_pop("reset done")

    def add_streams(self, streams, ports: list[int]) -> None:
        specs = [s.spec() for s in _streams(streams)]
        for port in ports:
            log.step_push(f"add {len(specs)} stream(s) → port {port}")
            # Summary/len are computed engine-side (Scapy), so log before
            # shipping — no round-trip needed just to render the log line.
            for sp in specs:
                log.ring(f"stream {sp['name']!r}: {sp['summary']} "
                         f"({sp['len']} B)")
            self._call(_ops.add_streams, port, specs)
            log.step_pop()

    def start(self, ports: list[int], mult: str = "1",
              duration: float = -1, force: bool = False) -> None:
        log.step_push(f"start: ports={ports} mult={mult} duration={duration}s")
        self._call(_ops.start, ports, mult, duration, force)
        log.ring("trex: traffic started")
        log.step_pop()

    def wait_on_traffic(self, timeout: float) -> None:
        """Block until traffic stops.  *timeout* is required and finite.

        The value bounds the native STLClient wait; the pyte.remote
        transport carrying it gets ``timeout + WAIT_MARGIN``, so the
        agent-side client times out first and reports why.

        There is deliberately no "wait forever" here.  A pyte.remote
        session that times out is left unusable (its late reply may
        still be in flight), so an unbounded wait could only ever hang
        a session with no recovery path.  Pass ``duration + margin``,
        the way every caller already does.
        """
        if timeout is None:
            raise ValueError(
                "wait_on_traffic() requires an explicit timeout: a "
                "pyte.remote session cannot wait forever (it is "
                "unusable after a timeout).  Pass duration + a margin.")
        if timeout < 0:
            raise ValueError(
                f"timeout must not be negative, got {timeout!r}")
        log.step_push(f"wait_on_traffic (timeout={timeout})")
        self._call(_ops.wait_on_traffic, timeout,
                   timeout=timeout + WAIT_MARGIN)
        log.step_pop("traffic finished")

    def get_stats(self, ports: list[int] | None = None) -> dict[int, PortStats]:
        ports = self._ports if ports is None else ports
        raw = self._call(_ops.get_stats, ports)
        return {p: parse_port_stats(raw, p) for p in ports}

    def get_global_stats(self) -> GlobalStats:
        raw = self._call(_ops.get_stats, self._ports)
        return parse_global_stats(raw)

    def get_pgid_stats(self, pg_ids: list[int]) -> dict[int, LatencyStats]:
        raw = self._call(_ops.get_pgid_stats, pg_ids)
        return {pg: parse_latency_stats(raw, pg) for pg in pg_ids}

    def stop(self, ports: list[int] | None = None) -> None:
        ports = self._ports if ports is None else ports
        log.step_push(f"stop ports {ports}")
        self._call(_ops.stop, ports)
        log.step_pop("stopped")

    def poll_stats(self, every: float = 2.0,
                   ports: list[int] | None = None) -> Iterator[dict[int, PortStats]]:
        """Yield (and RING) a per-port stats snapshot every `every` seconds.

        Stops when the caller breaks or wait_on_traffic() has been awaited;
        intended for use inside the traffic window.
        """
        ports = self._ports if ports is None else ports
        while True:
            snap = self.get_stats(ports=ports)
            for p in ports:
                s = snap[p]
                log.ring(f"port{p} tx={s.tx_bps/1e9:.2f} Gbps/"
                         f"{s.tx_pps/1e6:.2f} Mpps rx={s.rx_bps/1e9:.2f} Gbps "
                         f"loss={s.loss_pct:.2f}%")
            yield snap
            time.sleep(every)

    def mi_report(self, ports: list[int] | None = None,
                  pg_ids: list[int] | None = None, tool: str = "trex") -> None:
        """Emit throughput (+ latency) MI artifacts from current stats."""
        ports = self._ports if ports is None else ports
        stats = self.get_stats(ports=ports)
        lat = self.get_pgid_stats(pg_ids) if pg_ids else {}
        from pyte.mi import Aggr, Logger, Meas, Mult
        with Logger(tool) as logger:
            for p in ports:
                s = stats[p]
                logger.add(Meas.THROUGHPUT, f"Port {p} Tx", Aggr.MEAN,
                           s.tx_bps, Mult.PLAIN)
                logger.add(Meas.THROUGHPUT, f"Port {p} Rx", Aggr.MEAN,
                           s.rx_bps, Mult.PLAIN)
            for pg, ls in lat.items():
                logger.add(Meas.LATENCY, f"pg {pg} avg", Aggr.MEAN,
                           ls.avg, Mult.MICRO)
                logger.add(Meas.LATENCY, f"pg {pg} jitter", Aggr.MEAN,
                           ls.jitter, Mult.MICRO)


@contextmanager
def session(pco: "RpcServer", opts: ServerOpts,
            connect_timeout: float = CONNECT_TIMEOUT) -> Iterator[Client]:
    """Launch ``t-rex-64 -i`` on pco's agent and yield a connected Client.

    Bring-up: open one pyte.remote session, write the cfg-YAML, launch TRex
    as a tapi_job (sh -c 'cd <dir> && exec ...'), then bootstrap the native
    STLClient over loopback. Teardown disconnects the client and destroys
    the job on every exit path.
    """
    from pyte import remote
    ports = list(range(len(opts.ports)))
    log.step_push(f"TRex STL: bring up on {pco.ta} ({len(ports)} ports)")
    job = None
    popped = False
    primary = None
    try:
        with remote.python(pco) as rem:
            cfg_path = rem.call(_ops.write_cfg, opts.cfg_yaml())
            log.ring(f"trex cfg: {cfg_path}")
            try:
                job = pco.job("/bin/sh", ["-c", opts.shell_command(cfg_path)])
                job.stdout.log(level="RING")
                job.stderr.log(level="WARN")
                job.start()
                try:
                    cli = rem.call(_ops.bootstrap,
                                   os.path.join(opts.workdir, TREX_PYLIB),
                                   "127.0.0.1", opts.sync_port,
                                   opts.async_port, connect_timeout,
                                   timeout=connect_timeout + 15)
                except RemotePythonError as exc:
                    raise TrexError(
                        f"TRex STL server did not come up on {pco.ta}: "
                        f"{exc}") from exc
                log.ring("trex: STL client connected")
                log.step_pop(f"TRex STL ready on {pco.ta}")
                popped = True
                client = Client(rem, cli, ports)
                try:
                    yield client
                finally:
                    try:
                        rem.call(_ops.disconnect, cli)
                    except Exception:   # noqa: BLE001  best-effort teardown
                        pass
            finally:
                # The mkstemp'd cfg would otherwise accumulate on a
                # shared DUT, one file per session.
                try:
                    rem.call(_ops.remove_file, cfg_path)
                except Exception:   # noqa: BLE001  best-effort teardown
                    pass
    except BaseException as exc:
        primary = exc
        raise
    finally:
        if not popped:
            log.step_pop(f"TRex STL bring-up failed on {pco.ta}")
        if job is not None:
            cleanup_all(job.destroy, primary=primary)
