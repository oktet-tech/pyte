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
from pyte._cleanup import cleanup_all
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
#: Extra seconds the pyte.remote transport is given on top of a native
#: wait, so the agent-side client is always the one that times out first
#: and can report *why* the traffic did not finish.
WAIT_MARGIN = 30.0

#: Decade thresholds and prefixes for :func:`_rate`, largest first.
_SI_STEPS = ((1e9, "G"), (1e6, "M"), (1e3, "K"), (1.0, ""))


def _op_detail(name: str, args: tuple) -> str:
    """Argument detail for an op's VERB line, or "" when it has none.

    Only arguments that are both small and diagnostic are rendered: a
    multiplier, a timeout, a group count. The stats ops take nothing
    worth printing, and an op that carried a profile source or a
    counter dict would turn one log line into a page.
    """
    if name == "start":
        return " ".join(
            f"{key}={value}" for key, value in
            zip(("mult", "duration", "nc", "latency_pps"), args))
    if name == "wait_on_traffic" and args:
        return f"timeout={args[0]}"
    if name == "get_tg_stats" and args:
        return f"{len(args[0])} template group(s)"
    return ""


def _rate(value: float, unit: str) -> str:
    """``value`` in ``unit``, scaled to the largest prefix that fits.

    A fixed unit cannot render this suite's runs: the vendored ASTF
    profiles run at their own connection rate times a small
    multiplier, which on a 10G link is a few kilobits per second,
    while a rate search climbs into the gigabits. Printing gigabits
    throughout reports the first as a flat 0.00 for every sample --
    which is what the first live run's progress lines looked like,
    and is indistinguishable from no traffic at all.
    """
    for step, prefix in _SI_STEPS:
        if abs(value) >= step:
            return f"{value / step:.2f} {prefix}{unit}"
    return f"0.00 {unit}"


class Client:
    """Engine-side handle to a connected, agent-local ASTF client."""

    def __init__(self, rem, cli, ports: list[int]):
        self._rem = rem
        self._cli = cli
        self._ports = list(ports)
        self._profile = None
        self._tg_names: list[str] | None = None

    def _call(self, fn, *args, timeout=None):
        """Ship one op-function, translating remote failures to TrexError.

        Every shipped op is announced at VERB under a fixed ``astf op:``
        prefix, so the whole group is one filter away. Only the methods
        that change state open a step bracket, which left the stats
        polls -- the bulk of the traffic in a run -- invisible: a
        bring-up failure gave a traceback and no record of which call
        was in flight. VERB sits below RING, so this is silent at the
        normal level and there for whoever raises it.

        The VERB line and the TrexError below both name ``fn.__name__``,
        so the last op announced is exactly the one the failure names.
        """
        log.verb(" ".join(
            x for x in (f"astf op: {fn.__name__}",
                        _op_detail(fn.__name__, args)) if x))
        try:
            return self._rem.call(fn, self._cli, *args, timeout=timeout)
        except RemotePythonError as exc:
            raise TrexError(f"{fn.__name__} failed: {exc}") from exc

    def reset(self) -> None:
        log.step_push("reset (ASTF ports)")
        self._call(_ops.reset)
        log.step_pop("reset done")

    def load_profile(self, text: str, name: str,
                     tunables: dict | None = None) -> None:
        """Ship a profile source to the agent and load it natively."""
        log.step_push(f"load_profile {name!r}")
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
        log.step_push(f"start mult={mult} duration={duration} "
                      f"latency_pps={latency_pps}")
        self._call(_ops.start, mult, duration, nc, latency_pps)
        log.ring("trex: ASTF traffic started")
        log.step_pop("traffic started")

    def stop(self) -> None:
        log.step_push("stop (ASTF traffic)")
        self._call(_ops.stop)
        log.step_pop("stopped")

    def wait_on_traffic(self, timeout: float) -> None:
        """Block until traffic stops.  *timeout* is required and finite.

        The value bounds the native ASTFClient wait; the pyte.remote
        transport carrying it gets ``timeout + WAIT_MARGIN``, so the
        agent-side client times out first and reports why.

        There is deliberately no "wait forever" here: a pyte.remote
        session that times out is left unusable, so an unbounded wait
        could only ever hang a session with no recovery path.  Passing
        None used to mean the 30 s session default, not forever.
        """
        if timeout is None:
            raise ValueError(
                "wait_on_traffic() requires an explicit timeout: a "
                "pyte.remote session cannot wait forever (it is "
                "unusable after a timeout).  Pass duration + a margin.")
        if timeout < 0:
            raise ValueError(
                f"timeout must not be negative, got {timeout!r}")
        log.step_push(f"wait_on_traffic timeout={timeout}")
        self._call(_ops.wait_on_traffic, timeout,
                   timeout=timeout + WAIT_MARGIN)
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
                f"tx={_rate(glob.tx_bps, 'bps')}/"
                f"{_rate(glob.tx_pps, 'pps')} "
                f"rx={_rate(glob.rx_bps, 'bps')}/"
                f"{_rate(glob.rx_pps, 'pps')} "
                f"drops={traffic.drop_pct:.2f}%")
            if every:
                time.sleep(every)
        return series

    def log_summary(self, series: _stats.Series, t0: float,
                    t1: float) -> None:
        """RING a rendered end-of-run summary block."""
        log.step_push("log_summary (ASTF run summary)")
        log.ring(f"steady-state window {t0:.1f}s .. {t1:.1f}s")
        for attr, unit in (("tx_bps", "bps"), ("rx_bps", "bps"),
                           ("tx_pps", "pps"), ("rx_pps", "pps"),
                           ("active_flows", "flows")):
            log.ring(f"{attr}: mean "
                     f"{_rate(series.mean(attr, t0, t1), unit)}, "
                     f"median "
                     f"{_rate(series.median(attr, t0, t1), unit)}")
        traffic = self.get_traffic()
        log.ring(f"connections: attempted {traffic.connect_attempts}, "
                 f"established {traffic.connects}, "
                 f"closed {traffic.closes}, "
                 f"dropped {traffic.drops} "
                 f"({traffic.drop_pct:.2f}%)")
        # The line above is the client side, which is what
        # AstfTraffic's connection properties and the drop percentage
        # the tests key on all read. The server's own view is logged
        # beside it rather than folded in: the two count different
        # events (a server accepts where a client attempts, and it
        # counts UDP under udps_accepts where the client counts
        # udps_connects) so they cannot be summed, but a device that
        # drops connections the client never notices shows up as a
        # difference here and nowhere else.
        srv = traffic.server
        log.ring("server side: accepted "
                 f"{int(srv.get('tcps_accepts', 0))}, connects "
                 f"{int(srv.get('tcps_connects', 0))}, closed "
                 f"{int(srv.get('tcps_closed', 0))}, drops "
                 f"{int(srv.get('tcps_drops', 0))}, conndrops "
                 f"{int(srv.get('tcps_conndrops', 0))}, udp accepted "
                 f"{int(srv.get('udps_accepts', 0))}, udp closed "
                 f"{int(srv.get('udps_closed', 0))}")
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
        log.step_pop("summary logged")


@contextmanager
def session(pco: "RpcServer", opts: ServerOpts,
            connect_timeout: float = CONNECT_TIMEOUT
            ) -> Iterator[Client]:
    """Launch ``t-rex-64 -i --astf`` on pco's agent, yield a Client.

    Bring-up: open one pyte.remote session, write the cfg-YAML, launch
    TRex as a tapi_job, bootstrap the native ASTFClient over loopback,
    then acquire the ports. Teardown disconnects the client, removes
    the temp files and destroys the job on every exit path.
    """
    from pyte import remote
    from pyte.tools.trex import _ops as _stl_ops
    ports = list(range(len(opts.ports)))
    log.step_push(f"TRex ASTF: bring up on {pco.ta} "
                  f"({len(ports)} ports)")
    job = None
    popped = False
    primary = None
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
                # Which compatibility shims fired and which were not
                # needed. Each of them is independently guarded so an
                # unnecessary one cannot break bring-up, which also
                # means a broken one leaves no trace unless it says so
                # -- and a live bring-up has already been debugged the
                # hard way for want of exactly these lines.
                try:
                    report = rem.call(_ops.shim_report, cli)
                    for note in report.get("notes", ()):
                        log.ring(f"trex shim: {note}")
                except Exception:       # noqa: BLE001 diagnostics only
                    log.ring("trex: no compatibility-shim report")
                client = Client(rem, cli, ports)
                # A freshly connected client owns nothing: every
                # command that changes state, load_profile included,
                # answers "must acquire the context for this
                # operation" until the ports are taken. reset() takes
                # them by force and clears whatever an earlier client
                # left loaded, so the session starts from a known
                # state as well as an owned one. A failure here
                # leaves ``popped`` false, so the outer teardown says
                # bring-up failed and destroys the job.
                client.reset()
                log.step_pop(f"TRex ASTF ready on {pco.ta}")
                popped = True
                try:
                    yield client
                finally:
                    if client._profile is not None:
                        try:
                            rem.call(_ops.remove_file, client._profile)
                        except Exception:   # noqa: BLE001 teardown
                            pass
                    try:
                        # Through the client rather than rem.call, so
                        # the last op of a session is announced like
                        # every other one -- a teardown that hangs is
                        # otherwise indistinguishable from a body that
                        # never returned.
                        client._call(_ops.disconnect)
                    except Exception:       # noqa: BLE001 teardown
                        pass
            finally:
                try:
                    rem.call(_stl_ops.remove_file, cfg_path)
                except Exception:           # noqa: BLE001 teardown
                    pass
    except BaseException as exc:
        primary = exc
        raise
    finally:
        if not popped:
            log.step_pop(f"TRex ASTF bring-up failed on {pco.ta}")
        if job is not None:
            cleanup_all(job.destroy, primary=primary)
