# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte.tools shared machinery: the one home for wrapper plumbing.

The tool wrappers used to be fifteen hand-rolled copies of one design
whose lifecycle/error/cleanup layers drifted apart (five different
non-zero-exit policies, two cleanup idioms, three argv-builder styles).
This module owns the shared layers; per-tool modules keep what is
genuinely theirs: the Opts dataclass with its C-source-pinned argv
bind order, the output parser, and the MI vocabulary.

Everything here is override-friendly by design: tools with specifics
subclass and redefine individual hooks instead of forking the whole
lifecycle.
"""
from __future__ import annotations

import time
from contextlib import contextmanager

from pyte._cleanup import cleanup_all
from pyte.errors import ToolError

#: Sentinel: "use the class's default_timeout" (None now means forever).
_USE_DEFAULT = object()
_NoTimeout = type(None)

# ---------------------------------------------------------------------------
# argv builders: explicit order stays in the tool module (that order is
# pinned to the C TAPI); these only remove the `if x is not None` ladders.
# ---------------------------------------------------------------------------


def opt(flag: str, value) -> list[str]:
    """``["-p", "8080"]`` — a flag/value pair; [] when value is None."""
    return [] if value is None else [flag, str(value)]


def opt_eq(flag: str, value) -> list[str]:
    """``["--threads=4"]`` — joined form; *flag* includes the ``=``."""
    return [] if value is None else [f"{flag}{value}"]


def switch(name: str, on) -> list[str]:
    """``["-D"]`` when *on* is truthy, else []."""
    return [name] if on else []


def suffixed(flag: str, value, suffix: str) -> list[str]:
    """``["--time=30s"]`` — joined form with a unit suffix appended."""
    return [] if value is None else [f"{flag}{value}{suffix}"]


# ---------------------------------------------------------------------------
# option coercion / validation
# ---------------------------------------------------------------------------


def coerce_enum(cls, field: str, v):
    """Accept an enum member or a (case-insensitive) member-name string.

    Promoted from fio, the best-in-class enum strategy of the package:
    ``Opts(rwtype="randwrite")`` and ``Opts(rwtype=RwType.RANDWRITE)``
    both work, and a typo lists the valid names.
    """
    if isinstance(v, cls):
        return v
    if isinstance(v, str):
        try:
            return cls[v.upper()]
        except KeyError:
            valid = [m.name.lower() for m in cls]
            raise ValueError(
                f"unknown {field} {v!r}; valid: {valid}") from None
    raise TypeError(
        f"{field} must be {cls.__name__} or str, not "
        f"{v.__class__.__name__}")


#: ipversion values as the tools spell them on the command line
#: ("-4"/"-6"); shared by iperf3/netperf/sfnt_pingpong.
IPVERSIONS = frozenset({"4", "6"})


def check_ipversion(v, field: str = "ipversion") -> None:
    """Validate an optional "4"/"6" ipversion option value."""
    if v is not None and v not in IPVERSIONS:
        raise ValueError(
            f"unknown {field} {v!r}; valid: {sorted(IPVERSIONS)}")


# ---------------------------------------------------------------------------
# address arguments: tests hand wrappers a pyte.env.Addr, a (host, port)
# tuple, or a bare port; normalize in one place.
# ---------------------------------------------------------------------------

#: What address-taking wrapper options accept (env.Addr exposes .pair).
AddrLike = "int | tuple[str, int] | pyte.env.Addr"


def addr_host_port(v) -> tuple[str, int]:
    """Normalize an AddrLike carrying a host to ``(host, port)``."""
    if hasattr(v, "pair"):
        v = v.pair
    if isinstance(v, tuple):
        return str(v[0]), int(v[1])
    raise TypeError(
        f"expected (host, port) or an env.Addr (a bare port has no "
        f"host), got {v!r}")


def addr_port(v) -> int:
    """Normalize an AddrLike to just the port number."""
    if hasattr(v, "pair"):
        v = v.pair
    if isinstance(v, tuple):
        return int(v[1])
    return int(v)


# ---------------------------------------------------------------------------
# Job bring-up / teardown
# ---------------------------------------------------------------------------


def launch(pco, program: str, argv: list[str], *, setup=None):
    """Create, set up, and start a tool job; returns ``(job, extras)``.

    The hardened bring-up every wrapper hand-rolled a variant of: any
    failure between job creation and a successful start() destroys the
    job before the exception propagates (older wrappers leaked the job
    when a second filter attach failed).  ``setup(job)`` attaches
    filters/wrappers — it runs BEFORE start(), as channels must — and
    whatever it returns (typically the readable filters) comes back as
    ``extras``.
    """
    job = pco.job(program, argv)
    try:
        extras = None if setup is None else setup(job)
        job.start()
    except BaseException:
        job.destroy()
        raise
    return job, extras


@contextmanager
def running(handle):
    """Yield *handle*, close() it on exit — the tail of every run() CM.

    A failing close() is attached to whatever the block raised rather
    than replacing it: this is the teardown path behind every tool's
    run() context manager, so a masked exception here loses the real
    failure for nine wrappers at once.
    """
    primary = None
    try:
        yield handle
    except BaseException as exc:
        primary = exc
        raise
    finally:
        cleanup_all(handle.close, primary=primary)


# ---------------------------------------------------------------------------
# ToolHandle: the shared handle lifecycle
# ---------------------------------------------------------------------------


class ToolHandle:
    """Base of the per-tool run handles: shared lifecycle, per-tool hooks.

    A subclass sets the class attributes, implements :meth:`_parse`,
    and gets the whole lifecycle for free: cached :meth:`wait` with
    the chosen error policy, :meth:`wait_silent`, :meth:`close`, and
    :meth:`mi_report` that no longer demands a prior wait().

    Everything is deliberately override-friendly — a tool with
    specifics redefines the single hook that differs instead of
    forking the lifecycle:

    - :meth:`_read_output` — what wait() feeds ``_parse()``; the
      default reads ``self._stdout_filter.read_all()``.  Return any
      shape your ``_parse`` understands (e.g. a list of regex-filter
      rows).
    - :meth:`_parse` — per-tool output parsing; raise ``error_cls``
      on unparseable output.
    - :meth:`_check_status` — called in parse-first mode when the
      output parsed fine; the default raises on a non-zero exit.
      Override to tolerate expected non-zero exits (ping's 100%-loss
      runs still print a valid summary).
    - :meth:`_fail_status` — builds and raises the bad-exit error.
    - :meth:`_stop_for_close` / :meth:`_after_close` — how close()
      stops the job / extra teardown after destroy (e.g. removing an
      uploaded config file).
    - :meth:`_mi` — the tool's MI artifact emission, given an open
      ``pyte.mi.Logger`` and the report.
    """

    #: Tool name for error messages and the default MI logger name.
    tool: str = "tool"
    #: Exception the shared machinery raises (a ToolError subclass).
    error_cls = ToolError
    #: Default wait()/wait_silent() timeout in seconds.
    default_timeout: float = 60.0
    #: "parse-first": parse the output and report the exit status only
    #: when parsing also fails (a failed run rarely produces parseable
    #: output, and some tools exit non-zero with a valid report).
    #: "status-first": a non-zero exit raises before parsing (JSON
    #: tools whose failure output is known-unparseable).
    wait_policy: str = "parse-first"

    def __init__(self, job, stdout_filter=None):
        self._job = job
        self._stdout_filter = stdout_filter
        self._report = None
        self._closed = False
        self._stopped = False
        self._job_destroyed = False
        self._after_close_done = False

    # -- hooks (override per tool) --------------------------------------
    def _parse(self, raw):
        """Parse tool output into the report; raise error_cls if bad."""
        raise NotImplementedError

    def _read_output(self, timeout: float):
        """Collect the output wait() hands to :meth:`_parse`."""
        return self._stdout_filter.read_all(timeout=timeout)

    def _check_status(self, status, raw) -> None:
        """Parse succeeded (parse-first mode): judge the exit status."""
        if not status.ok:
            self._fail_status(status, raw)

    def _fail_status(self, status, raw) -> None:
        """Raise the bad-exit error (raw may be any _read_output shape)."""
        msg = f"{self.tool} exited with {status}"
        if raw is not None:
            msg += f"; output={str(raw)[:200]!r}"
        raise self.error_cls(msg)

    def _stop_for_close(self) -> None:
        """How close() stops the tool (default: Job.stop's SIGTERM)."""
        self._job.stop()

    def _after_close(self) -> None:
        """Extra teardown after the job is destroyed (default: none)."""

    def _mi(self, logger, rep) -> None:
        """Emit the tool's MI artifacts into an open mi.Logger."""
        raise NotImplementedError

    # -- shared lifecycle ------------------------------------------------
    def _resolve_timeout(self, timeout):
        """Resolve *timeout* honoring the ``_USE_DEFAULT`` sentinel.

        ``_USE_DEFAULT`` (the omitted-argument case) becomes
        ``self.default_timeout``; ``None`` passes through unchanged and
        means "block forever" (P1.5); a float passes through unchanged.
        Every wrapper's ``wait()``/``wait_silent()`` override must route
        its *timeout* argument through this one place so the
        package-wide timeout convention can't drift per-tool (A2).
        """
        if timeout is _USE_DEFAULT:
            return self.default_timeout
        return timeout

    @staticmethod
    def _remaining(timeout, start: float):
        """Budget left for a second wait step after *start*.

        Mirrors the arithmetic :meth:`wait` uses to share ONE deadline
        between ``job.wait()`` and the output read (A3): the read gets
        whatever the job wait left over (floored at 1 s), not the full
        timeout again.  ``None`` (forever) stays ``None``.
        """
        if timeout is None:
            return None
        return max(timeout - (time.monotonic() - start), 1.0)

    def wait(self, timeout: float | _NoTimeout | None = _USE_DEFAULT):
        """Wait for completion, parse the output, return the report.

        Caches the report; subsequent calls return the cached value.
        Raises ``error_cls`` per the class's ``wait_policy``.

        *timeout* is ONE deadline covering both the job wait and the
        output read (the read gets what the wait left over, floored
        at 1 s); the old per-tool code reused the full timeout for
        each step, doubling the worst case.  Omit it for the tool's
        ``default_timeout``; pass ``None`` to block forever.
        """
        if self._report is not None:
            return self._report
        timeout = self._resolve_timeout(timeout)
        start = time.monotonic()
        status = self._job.wait(timeout=timeout)
        remaining = self._remaining(timeout, start)
        raw = self._read_output(remaining)
        if self.wait_policy == "status-first":
            if not status.ok:
                self._fail_status(status, raw)
            report = self._parse(raw)
        else:  # parse-first
            try:
                report = self._parse(raw)
            except ToolError:
                if not status.ok:
                    self._fail_status(status, raw)
                raise
            self._check_status(status, raw)
        self._report = report
        return report

    def wait_silent(self,
                    timeout: float | _NoTimeout | None = _USE_DEFAULT,
                    ) -> None:
        """Wait for completion without touching the output (pre-runs).

        Omit *timeout* for the tool's default; None blocks forever.
        """
        timeout = self._resolve_timeout(timeout)
        status = self._job.wait(timeout=timeout)
        if not status.ok:
            self._fail_status(status, None)

    def mi_report(self, tool: str | None = None) -> None:
        """Emit MI artifacts (waits for completion if needed)."""
        rep = self.wait()
        import pyte.mi
        with pyte.mi.Logger(tool or self.tool) as logger:
            self._mi(logger, rep)

    def close(self) -> None:
        """Stop the tool and destroy the job; idempotent and retryable.

        Tracks the steps that actually completed, so a close() that
        failed part-way retries only what is left.  Setting a _closed
        flag up front (what this replaced) made a failed teardown
        permanent: the job stayed alive and the second call returned
        having done nothing.
        """
        if self._closed:
            return
        from pyte.errors import TeError
        if not self._stopped:
            try:
                self._stop_for_close()
            except TeError:
                pass
            self._stopped = True
        cleanup_all(self._destroy_job_once, self._after_close_once)
        self._closed = True

    def _destroy_job_once(self) -> None:
        if not self._job_destroyed:
            self._job.destroy()
            self._job_destroyed = True

    def _after_close_once(self) -> None:
        if not self._after_close_done:
            self._after_close()
            self._after_close_done = True
