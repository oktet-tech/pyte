# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools.stress — run the stress load generator via pyte.job.

Pure Python over pyte.job; zero shim imports. The stress binary is
resolved from the agent's PATH (job program "stress"). Gate stress tests
with <req id="STRESS"/> and the prologue probe.

Pinned mappings (from te/lib/tapi_tool/tapi_stress.{h,c})
========================================================

argv (stress_tool_binds; each omittable, omitted when unset):
    --cpu <N>   --io <N>   --vm <N>   --timeout <N>

Constraint: at least one of cpu/io/vm must be set (tapi_stress.h).
stress has no machine-readable report and the C TAPI emits no MI, so this
wrapper exposes only argv + an exit-status wait(). The C polls a
"Usage: stress" filter to catch wrong usage; pyte validates ">=1 target"
up front and otherwise relies on the exit status.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyte.rpc import RpcServer


@dataclass(frozen=True)
class Opts:
    """stress options.

    Parameters
    ----------
    cpu:
        ``--cpu`` workers spinning on sqrt() (0 means all CPUs, per stress).
    io:
        ``--io`` workers spinning on sync().
    vm:
        ``--vm`` workers spinning on malloc()/free().
    timeout:
        ``--timeout`` seconds to run; None runs until stopped.
    """
    cpu: int | None = None
    io: int | None = None
    vm: int | None = None
    timeout: int | None = None

    def __post_init__(self) -> None:
        if self.cpu is None and self.io is None and self.vm is None:
            raise ValueError(
                "stress needs at least one of cpu/io/vm to be set")

    def to_argv(self) -> list[str]:
        """Build the stress argument list (without argv[0])."""
        argv: list[str] = []
        if self.cpu is not None:
            argv += ["--cpu", str(self.cpu)]
        if self.io is not None:
            argv += ["--io", str(self.io)]
        if self.vm is not None:
            argv += ["--vm", str(self.vm)]
        if self.timeout is not None:
            argv += ["--timeout", str(self.timeout)]
        return argv


class Stress:
    """Lifecycle manager for a running stress job (no report)."""

    def __init__(self, job):
        self._job = job
        self._closed = False

    def wait(self, timeout: float = 60.0) -> bool:
        """Wait for stress to finish; return True iff it exited cleanly."""
        return self._job.wait(timeout=timeout).ok

    def close(self) -> None:
        """Stop stress (SIGTERM, errors tolerated) and destroy the job."""
        if self._closed:
            return
        self._closed = True
        from pyte.errors import TeError
        try:
            self._job.stop()
        except TeError:
            pass
        self._job.destroy()


@contextmanager
def run(pco: "RpcServer", opts: Opts):
    """Context manager: create, start, and clean up a stress job.

    Yields a :class:`Stress`; call :meth:`Stress.wait` inside the block.

    Example::

        with stress.run(pco, stress.Opts(cpu=1, timeout=2)) as s:
            assert s.wait()
    """
    job = pco.job("stress", opts.to_argv())
    try:
        job.stdout.log(level="RING")
        job.stderr.log(level="ERROR")
        job.start()
    except Exception:
        job.destroy()
        raise
    stress_obj = Stress(job)
    try:
        yield stress_obj
    finally:
        stress_obj.close()
