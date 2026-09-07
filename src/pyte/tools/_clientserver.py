# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools._clientserver — shared server-lifecycle helper.

Client/server tool wrappers (iperf3, netperf, …) use serve() to run the
server side: start the server job, wait a readiness delay, yield the
endpoint, and tear the job down on exit. This helper owns ONLY the server
lifecycle — never argv building or output parsing, which stay per-tool.
"""
from __future__ import annotations

import signal as _signal
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pyte._cleanup import cleanup_all

if TYPE_CHECKING:
    from pyte.rpc import RpcServer


@dataclass(frozen=True)
class Endpoint:
    """Where a started server listens.

    ``port`` is None for tools that pick their own port and do not
    report it (sfnt-pingpong, NPtcp) -- a fake 0 used to stand there.
    """
    host: str
    port: int | None


@contextmanager
def serve(pco: "RpcServer", program: str, argv: list[str], *,
          host: str, port: int | None, ready_delay: float = 1.0,
          term: int | _signal.Signals = _signal.SIGINT):
    """Run a server job for the duration of the ``with`` block.

    Starts ``pco.job(program, argv)``, logs its stderr, waits
    ``ready_delay`` seconds so the client never races a not-yet-listening
    server (mirrors tapi_perf_server_start's SLEEP(1)), then yields
    :class:`Endpoint`. On exit the job is stopped (``term`` signal, via
    ``job.stop``) and destroyed — even if the block raises. If the server
    fails to start, or the readiness delay fails, the job is destroyed
    before the exception propagates.
    """
    job = pco.job(program, argv)
    try:
        job.stderr.log(level="WARN")
        job.start()
        # Inside the guard: pco.sleep() is an RPC and can fail, and a
        # failure here used to leak the already-started server job.
        if ready_delay:
            pco.sleep(ready_delay)
    except BaseException as exc:
        cleanup_all(job.destroy, primary=exc)
        raise
    primary = None
    try:
        yield Endpoint(host, port)
    except BaseException as exc:
        primary = exc
        raise
    finally:
        from pyte.errors import TeError

        def _stop():
            try:
                job.stop(signal=term)
            except TeError:
                pass

        cleanup_all(_stop, job.destroy, primary=primary)
