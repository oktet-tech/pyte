# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools.stress — run the stress load generator via pyte.job.

Pure Python over pyte.job; zero shim imports. The stress binary is
resolved from the agent's PATH (job program "stress"). Gate stress tests
with <req id="STRESS"/> and the prologue probe.

Pinned mappings (from te/lib/tapi_tool/tapi_stress.{h,c})
===========================================================

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

from pyte.errors import ToolError
from pyte.tools import _tool

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
    duration:
        ``--timeout`` seconds to run; None runs until stopped.  Named
        duration to avoid colliding with every wait(timeout=) in the
        package (BREAKING rename from ``timeout``, P1.1 sweep).
    """
    cpu: int | None = None
    io: int | None = None
    vm: int | None = None
    duration: int | None = None

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
        if self.duration is not None:
            argv += ["--timeout", str(self.duration)]
        return argv


class Stress(_tool.ToolHandle):
    """Lifecycle manager for a running stress job (no report)."""

    tool = "stress"
    error_cls = ToolError
    default_timeout = 60.0

    def __init__(self, job):
        super().__init__(job)

    def wait(self,
             timeout: float | _tool._NoTimeout | None = _tool._USE_DEFAULT,
             ):
        """Wait for stress to finish; return the JobStatus.

        BREAKING (was ``-> bool``): the status carries which signal
        killed the run, not just success -- check ``status.ok``.
        Follows the package timeout convention (P1.5, A2): omit
        *timeout* for the class's ``default_timeout``, pass ``None``
        to block forever.
        """
        timeout = self._resolve_timeout(timeout)
        return self._job.wait(timeout=timeout)


@contextmanager
def run(pco: "RpcServer", opts: Opts):
    """Context manager: create, start, and clean up a stress job.

    Yields a :class:`Stress`; call :meth:`Stress.wait` inside the block.

    Example::

        with stress.run(pco, stress.Opts(cpu=1, duration=2)) as s:
            assert s.wait().ok
    """
    def _setup(job):
        job.stdout.log(level="RING")
        job.stderr.log(level="ERROR")

    job, _ = _tool.launch(pco, "stress", opts.to_argv(), setup=_setup)
    with _tool.running(Stress(job)) as s:
        yield s
