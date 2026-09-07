# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""tapi_job wrapper: jobs, output channels, filters, messages."""
from __future__ import annotations

import signal
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Iterator

from pyte._util import shim as _shim, shim_lib as _shim_lib
from pyte.errors import ClosedResourceError, check
from pyte.errors import TimeoutError as TeTimeoutError
from pyte._util import enc as _enc

if TYPE_CHECKING:
    from pyte.rpc.server import RpcServer

#: Default timeout (seconds) for job waits/receives.
DEFAULT_TIMEOUT = 10.0


def _ms(timeout: float | None) -> int:
    """Convert float seconds to int milliseconds.

    None means "block forever" (-1 ms, the tapi_job convention).
    Negative values are rejected: they used to silently mean forever
    in C, which is never what a computed remaining-time wants.
    """
    if timeout is None:
        return -1
    if timeout < 0:
        raise ValueError(f"timeout must not be negative, got {timeout!r}"
                         " (use None to block forever)")
    return int(timeout * 1000)


def _signo(sig: int | signal.Signals) -> int:
    """Return the host signal number for *sig*.

    Accepts a raw int or a :class:`signal.Signals` member (the stdlib
    enum, whose values already are the host signal numbers).  tapi_job
    takes host numbers and its RPC backend converts them itself.
    """
    if not isinstance(sig, int):
        raise TypeError(
            "signal must be an int or signal.Signals, not "
            f"{sig.__class__.__name__}")
    return int(sig)


def _log_level(level: int | str | None) -> int:
    """Map a TE log level name ("RING", ...) or int to its value."""
    if level is None:
        return 0
    if isinstance(level, int):
        return level
    lib = _shim_lib()
    try:
        return getattr(lib, f"TE_LL_{level}")
    except AttributeError:
        raise ValueError(f"unknown log level {level!r}") from None


class StatusKind(Enum):
    """Cause of a job's completion."""
    EXITED = "exited"
    SIGNALED = "signaled"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class JobStatus:
    """Completed job status: kind + exit code or signal number."""
    kind: StatusKind
    value: int

    @property
    def ok(self) -> bool:
        """True iff the job exited normally with code 0."""
        return self.kind is StatusKind.EXITED and self.value == 0

    def __str__(self) -> str:
        return f"{self.kind.value}({self.value})"


@dataclass(frozen=True)
class JobMessage:
    """One message read from a job filter.

    ``raw`` is the exact received bytes; ``data`` decodes THIS
    message's bytes as UTF-8 (errors replaced with U+FFFD).  Messages
    are arbitrary stream chunks (agent pipe-read boundaries), so a
    multibyte character split between two messages shows up as U+FFFD
    in both messages' ``data`` — use :meth:`Filter.read_all` (or join
    ``raw`` yourself) for boundary-safe text.  TE truncates data at
    interior NUL bytes before delivery, so the payload may be shorter
    than the raw output; this is asymmetric with
    :meth:`InputChannel.send`, which is binary-safe.
    """
    raw: bytes
    eos: bool
    dropped: int
    filter: "Filter"

    @property
    def data(self) -> str:
        """This message's bytes decoded as UTF-8 (errors replaced)."""
        return self.raw.decode("utf-8", errors="replace")


class Channel:
    """A primary output channel (stdout/stderr) of a job."""

    def __init__(self, job: "Job", handle, name: str):
        self._job = job
        self._h = handle
        self.name = name

    def _handle(self):
        """The live C handle; raises after the owning job is destroyed.

        pyte_shim passes handles straight into tapi_job_*, so a NULL
        or dangling pointer would crash the test process in C.
        """
        if self._h is None:
            raise ClosedResourceError(
                f"channel {self.name} of job "
                f"{self._job.program!r} is already destroyed")
        return self._h

    def attach_filter(self, name: str | None = None, readable: bool = True,
                      log_level: int | str | None = None,
                      regex: str | None = None, group: int = 0) -> "Filter":
        """Attach a filter to this channel; see Job.filter() for args."""
        return _attach_filter([self], name=name, readable=readable,
                              log_level=log_level, regex=regex, group=group)

    def grep(self, regex: str, group: int = 0,
             name: str | None = None) -> "Filter":
        """Readable regexp filter: yields matches (PCRE2, multiline).

        group selects the capture group to extract (0 = whole match).
        """
        return self.attach_filter(name=name, readable=True, regex=regex,
                                  group=group)

    def log(self, level: int | str = "RING") -> "Filter":
        """Send everything on this channel to the TE log; the output
        is not readable from the test.
        """
        return self.attach_filter(name=f"{self.name}-log", readable=False,
                                  log_level=level)

    def __repr__(self) -> str:
        return f"<Channel {self.name} of {self._job.program}>"


class InputChannel:
    """The stdin channel of a job."""

    def __init__(self, job: "Job", handle):
        self._job = job
        self._h = handle

    def _handle(self):
        """The live C handle; raises after the owning job is destroyed."""
        if self._h is None:
            raise ClosedResourceError(
                f"stdin of job {self._job.program!r} is already destroyed")
        return self._h

    def send(self, data: str | bytes) -> None:
        """Write data to the job's stdin (binary-safe)."""
        h = self._handle()
        lib = _shim_lib()
        raw = data.encode("utf-8") if isinstance(data, str) else bytes(data)
        check(lib.pyte_job_send(h, raw, len(raw)),
              f"job.send({self._job.program})")

    def __repr__(self) -> str:
        return f"<InputChannel stdin of {self._job.program}>"


class Filter:
    """A secondary (filter) channel: a message source for the test."""

    def __init__(self, job: "Job", handle, name: str, n_channels: int = 1):
        self._job = job
        self._h = handle
        self.name = name
        self._n_channels: int = n_channels

    def _handle(self):
        """The live C handle; raises once the filter is unusable.

        The handle is invalidated when the owning job is destroyed or
        when the filter has been detached from all its channels (the
        TAPI frees it then).
        """
        if self._h is None:
            raise ClosedResourceError(
                f"filter {self.name!r} of job {self._job.program!r} is "
                "already destroyed or fully detached")
        return self._h

    def attach(self, channel: Channel) -> None:
        """Attach this filter to one more output channel.

        Increments the internal channel count so that
        :meth:`messages` waits for the correct number of eos messages.
        """
        h = self._handle()
        ffi, lib = _shim()
        arr = ffi.new("tapi_job_channel_t *[]", [channel._handle()])
        check(lib.pyte_job_filter_add(h, arr, 1),
              f"filter_add_channels({self.name})")
        self._n_channels += 1

    def detach(self, channel: Channel) -> None:
        """Detach this filter from a channel.

        Decrements the internal channel count.  Once detached from all
        its channels the filter is freed by the TAPI; this object is
        marked dead and any further use raises RuntimeError.
        """
        h = self._handle()
        ffi, lib = _shim()
        arr = ffi.new("tapi_job_channel_t *[]", [channel._handle()])
        check(lib.pyte_job_filter_remove(h, arr, 1),
              f"filter_remove_channels({self.name})")
        self._n_channels -= 1
        if self._n_channels == 0:
            self._h = None      # freed by the TAPI: refuse further use

    def receive(self, timeout: float | None = DEFAULT_TIMEOUT) -> JobMessage:
        """Read the next message (raises TimeoutError if none)."""
        return receive_any([self], timeout=timeout)

    def last(self, timeout: float | None = DEFAULT_TIMEOUT) -> JobMessage:
        """Peek the last message without consuming the queue."""
        return receive_any([self], timeout=timeout, last=True)

    def messages(self, timeout: float | None = DEFAULT_TIMEOUT,
                 ) -> Iterator[JobMessage]:
        """Yield messages until all attached channels have sent eos.

        ta_job emits one eos message per attached primary channel, so a
        filter attached to both stdout and stderr receives two eos
        messages.  This method counts them and stops only after all
        ``self._n_channels`` eos messages have been consumed.  Eos
        messages themselves are not yielded.

        ``timeout`` is forwarded to each :meth:`receive` call;
        :exc:`pyte.errors.TimeoutError` propagates immediately if a
        receive times out (already-yielded messages are not replayed).
        """
        eos_seen = 0
        while eos_seen < self._n_channels:
            msg = self.receive(timeout=timeout)
            if msg.eos:
                eos_seen += 1
            else:
                yield msg

    def __iter__(self) -> Iterator[JobMessage]:
        """Iterate messages until end-of-stream (``messages()`` with
        the default per-receive timeout)."""
        return self.messages()

    def drain(self, timeout: float | None = 0) -> list[JobMessage]:
        """Read ALL queued messages in one tapi_job_receive_many() call.

        Eos messages are consumed but not returned.  One RPC instead
        of one per message; a short read (e.g. the job still running)
        shows up as missing eos entries, not as an error.  The default
        timeout is 0: "drain" means what is queued NOW (it used to
        inherit the 10 s first-message wait, so draining an empty
        queue blocked ten seconds).
        """
        return self.read_many(0, timeout=timeout)

    def read_many(self, count: int,
                  timeout: float | None = DEFAULT_TIMEOUT,
                  ) -> list[JobMessage]:
        """Read up to ``count`` messages (0 = all queued) from this
        filter via ONE C ``tapi_job_receive_many()`` call.

        Eos messages count against ``count`` on the agent side but are
        consumed here, not returned.  Unlike :meth:`messages` this does
        not wait for end-of-stream: after ``timeout`` expires waiting
        for the *first* message, whatever already arrived is returned
        (possibly an empty list) — a timeout is not an error.  The
        ``dropped`` field of the returned messages is always 0 (the
        bulk shim call does not carry per-message drop counts).
        """
        h = self._handle()
        ffi, lib = _shim()
        flts = ffi.new("tapi_job_channel_t *[]", [h])
        datas = ffi.new("char ***")
        lens = ffi.new("size_t **")
        eos = ffi.new("int **")
        n = ffi.new("unsigned int *")
        check(lib.pyte_job_receive_many(flts, 1, _ms(timeout), count,
                                        datas, lens, eos, n),
              f"filter.read_many({self.name})")
        try:
            out = []
            for i in range(n[0]):
                if eos[0][i]:
                    continue
                raw = bytes(ffi.buffer(datas[0][i], lens[0][i]))
                out.append(JobMessage(raw=raw, eos=False, dropped=0,
                                      filter=self))
            return out
        finally:
            lib.pyte_job_receive_many_free(datas[0], lens[0], eos[0], n[0])

    def read_all(self, timeout: float | None = DEFAULT_TIMEOUT) -> str:
        """Concatenate all message data until end-of-stream.

        Joins the raw bytes of every message and decodes ONCE, so a
        multibyte UTF-8 character split across message boundaries
        (arbitrary agent pipe-read chunks) decodes correctly — unlike
        joining per-message ``data``.  Calls :meth:`messages`
        internally; :exc:`pyte.errors.TimeoutError` propagates if a
        receive times out mid-stream.
        """
        raw = b"".join(m.raw for m in self.messages(timeout=timeout))
        return raw.decode("utf-8", errors="replace")

    def __repr__(self) -> str:
        return f"<Filter {self.name} of {self._job.program}>"


def _attach_filter(channels: list[Channel], *, name: str | None,
                   readable: bool, log_level: int | str | None,
                   regex: str | None, group: int) -> Filter:
    ffi, lib = _shim()
    if not channels:
        raise ValueError("no channels to attach the filter to")
    job = channels[0]._job
    arr = ffi.new("tapi_job_channel_t *[]", [c._handle() for c in channels])
    out = ffi.new("tapi_job_channel_t **")
    cname = ffi.NULL if name is None else _enc(name)
    check(lib.pyte_job_attach_filter(arr, len(channels), cname,
                                     1 if readable else 0,
                                     _log_level(log_level), out),
          f"job.attach_filter({name or ''})")
    flt = Filter(job, out[0], name or regex or "filter",
                 n_channels=len(channels))
    if regex is not None:
        check(lib.pyte_job_filter_regexp(flt._h, _enc(regex), group),
              f"job.filter_add_regexp({regex!r})")
    job._filters.append(flt)
    return flt


def receive_any(filters: list[Filter],
                timeout: float | None = DEFAULT_TIMEOUT,
                last: bool = False) -> JobMessage:
    """Read the next message from any of the given filters.

    The returned :class:`JobMessage` carries the exact received bytes
    in ``raw``; its ``data`` property decodes them per message (see
    the JobMessage docstring for the chunk-boundary caveat).  TE
    truncates output at interior NUL bytes before delivery, so the
    payload may be shorter than the raw output — asymmetric with
    :meth:`InputChannel.send` which is binary-safe.

    Raises :exc:`pyte.errors.TimeoutError` if nothing arrives in time.
    """
    ffi, lib = _shim()
    if not filters:
        raise ValueError("no filters to receive from")
    arr = ffi.new("tapi_job_channel_t *[]", [f._handle() for f in filters])
    data = ffi.new("char **")
    dlen = ffi.new("size_t *")
    eos = ffi.new("int *")
    dropped = ffi.new("unsigned int *")
    src = ffi.new("tapi_job_channel_t **")
    check(lib.pyte_job_receive(arr, len(filters), _ms(timeout),
                               1 if last else 0, data, dlen, eos, dropped,
                               src),
          "job.receive")
    try:
        raw = bytes(ffi.buffer(data[0], dlen[0]))
    finally:
        lib.pyte_free_string(data[0])
    flt = next((f for f in filters if f._h == src[0]), None)
    if flt is None:
        raise RuntimeError(
            "receive_any: message arrived from a filter not in the "
            "provided set")
    return JobMessage(raw=raw, eos=bool(eos[0]), dropped=dropped[0],
                      filter=flt)


def poll(items: list[Channel | InputChannel | Filter],
         timeout: float | None = DEFAULT_TIMEOUT) -> None:
    """Wait until one of the channels/filters is ready.

    Raises pyte.errors.TimeoutError if none becomes ready in time.
    """
    ffi, lib = _shim()
    if not items:
        raise ValueError("no channels to poll")
    arr = ffi.new("tapi_job_channel_t *[]", [i._handle() for i in items])
    check(lib.pyte_job_poll(arr, len(items), _ms(timeout)), "job.poll")


@dataclass(frozen=True)
class CompletedJob:
    """Result of :func:`run`: completion status plus captured output."""
    status: JobStatus
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        """True iff the job exited normally with code 0."""
        return self.status.ok


def run(server: "RpcServer", program: str, args: list[str] | None = None,
        env: dict[str, str] | None = None,
        timeout: float | None = DEFAULT_TIMEOUT) -> CompletedJob:
    """Run *program* to completion and capture its output.

    The ``subprocess.run()`` of tapi_job: create the job, capture
    stdout/stderr (also logged at RING level), start, wait, read the
    streams and destroy the job.  A non-zero exit is a result, not an
    exception — check ``.status`` / ``.ok`` — but a job still running
    when ``timeout`` expires raises :exc:`pyte.errors.TimeoutError`.
    """
    with Job.create(server, program, args or [], env) as job:
        out = job.stdout.attach_filter(name="stdout", log_level="RING")
        err = job.stderr.attach_filter(name="stderr", log_level="RING")
        job.start()
        status = job.wait(timeout=timeout)
        return CompletedJob(status=status,
                            stdout=out.read_all(timeout=timeout),
                            stderr=err.read_all(timeout=timeout))


class Wrapper:
    """A tapi_job wrapper (command-line prefix) attached to a Job.

    Deleting is optional: TE removes all wrappers together with the
    job.  delete() is idempotent.
    """

    def __init__(self, job: "Job", handle):
        self._job = job
        self._h = handle
        self._deleted = False

    def delete(self) -> None:
        if self._deleted:
            return
        if self._job._h is None:
            # The owning job was destroyed; TE freed its wrappers too.
            return
        lib = _shim_lib()
        check(lib.pyte_job_wrapper_delete(self._h), "job.wrapper_delete")
        self._deleted = True

    def __repr__(self) -> str:
        state = "deleted" if self._deleted else "active"
        return f"<Wrapper {state}>"


class Job:
    """A process run via tapi_job on an RPC server.

    Usually created with RpcServer.job(); a context manager that
    destroys the job (and its factory) on exit.
    """

    def __init__(self, factory, handle, program: str):
        self._factory = factory
        self._h = handle
        self.program = program
        self._started = False
        self._stdout: Channel | None = None
        self._stderr: Channel | None = None
        self._stdin: InputChannel | None = None
        self._filters: list[Filter] = []

    def _handle(self):
        """The live C handle; raises after destroy().

        pyte_shim passes handles straight into tapi_job_*, so a NULL
        handle would crash the test process in C instead of raising.
        """
        if self._h is None:
            raise ClosedResourceError(
                f"job {self.program!r} is already destroyed")
        return self._h

    @classmethod
    def create(cls, server: "RpcServer", program: str, args: list[str],
               env: dict[str, str] | None = None,
               stdin: bool = False) -> "Job":
        """Create (but do not start) a job running program on server.

        args are the program arguments (argv[0] = program is added
        here, per the exec convention tapi_job_create() expects).
        env replaces the whole environment when given (None inherits).
        stdin=True allocates the input channel right away — an input
        channel only binds to the process when allocated before
        start(), so requesting it at creation removes the ordering
        footgun.

        The argv/env cffi arrays are built before the factory is
        created so that a Python-side exception (e.g. encoding error)
        cannot leak an allocated factory handle.
        """
        ffi, lib = _shim()
        # Build argv/env arrays first; a Python error here leaks nothing.
        # Keep the cdata strings alive in locals across the call.
        argv_strs = [ffi.new("char[]", _enc(a)) for a in [program, *args]]
        argv = ffi.new("const char *[]", [*argv_strs, ffi.NULL])
        env_strs = None if env is None else [
            ffi.new("char[]", _enc(f"{k}={v}")) for k, v in env.items()]
        envp = ffi.NULL if env_strs is None else ffi.new(
            "const char *[]", [*env_strs, ffi.NULL])
        fac = ffi.new("tapi_job_factory_t **")
        check(lib.pyte_job_factory_rpc(server._h, fac),
              f"job_factory_rpc_create({server.name})")
        out = ffi.new("tapi_job_t **")
        rc = lib.pyte_job_create(fac[0], _enc(program), argv, envp, out)
        if rc != 0:
            lib.pyte_job_factory_destroy(fac[0])
            check(rc, f"job_create({program})")
        job = cls(fac[0], out[0], program)
        if stdin:
            _ = job.stdin
        return job

    # -- channels ------------------------------------------------------
    def _alloc_out(self) -> None:
        if self._stdout is None:
            h = self._handle()
            ffi, lib = _shim()
            o = ffi.new("tapi_job_channel_t **")
            e = ffi.new("tapi_job_channel_t **")
            check(lib.pyte_job_out_channels(h, o, e),
                  f"job.alloc_output_channels({self.program})")
            self._stdout = Channel(self, o[0], "stdout")
            self._stderr = Channel(self, e[0], "stderr")

    @property
    def stdout(self) -> Channel:
        """The job's stdout channel (allocated lazily, with stderr)."""
        self._alloc_out()
        assert self._stdout is not None
        return self._stdout

    @property
    def stderr(self) -> Channel:
        """The job's stderr channel (allocated lazily, with stdout)."""
        self._alloc_out()
        assert self._stderr is not None
        return self._stderr

    @property
    def stdin(self) -> InputChannel:
        """The job's stdin channel (allocated lazily).

        Must be allocated before start(): a channel allocated after
        the process is spawned is not bound to it, and TE only reports
        that later as TE_EBADFD from send().  Accessing it for the
        first time on a started job raises immediately instead; pass
        ``stdin=True`` to :meth:`create` (or ``RpcServer.job``) to
        allocate it at creation.
        """
        if self._stdin is None:
            if self._started:
                raise RuntimeError(
                    f"stdin of job {self.program!r} must be allocated "
                    "before start(): a channel allocated later is not "
                    "bound to the process (create the job with "
                    "stdin=True or touch job.stdin before starting)")
            h = self._handle()
            ffi, lib = _shim()
            i = ffi.new("tapi_job_channel_t **")
            check(lib.pyte_job_in_channel(h, i),
                  f"job.alloc_input_channels({self.program})")
            self._stdin = InputChannel(self, i[0])
        return self._stdin

    def filter(self, stdout: bool = False, stderr: bool = False,
               readable: bool = True, log_level: int | str | None = None,
               regex: str | None = None, group: int = 0,
               name: str | None = None) -> Filter:
        """Attach one filter to the job's stdout and/or stderr.

        regex (PCRE2, multiline) makes it a match filter; group picks
        the capture group to extract (0 = whole match).  log_level
        additionally logs the output ("RING", ...).
        """
        channels = []
        if stdout:
            channels.append(self.stdout)
        if stderr:
            channels.append(self.stderr)
        if not channels:
            raise ValueError("filter() needs stdout=True and/or "
                             "stderr=True")
        return _attach_filter(channels, name=name, readable=readable,
                              log_level=log_level, regex=regex, group=group)

    # -- lifecycle -----------------------------------------------------
    def start(self) -> None:
        """Actually run the job."""
        h = self._handle()
        lib = _shim_lib()
        check(lib.pyte_job_start(h), f"job.start({self.program})")
        self._started = True

    def run(self, timeout: float | None = DEFAULT_TIMEOUT) -> JobStatus:
        """start() and wait() in one call.

        For a fully one-shot create/run/capture/destroy see the
        module-level :func:`run` (``RpcServer.run``).
        """
        self.start()
        return self.wait(timeout=timeout)

    def wait(self, timeout: float | None = DEFAULT_TIMEOUT) -> JobStatus:
        """Wait for completion; raises TimeoutError if still running.

        timeout=None blocks until the job completes.  tapi_job_wait()
        reports a still-running job as TE_EINPROGRESS; convert that to
        the same TimeoutError as other timeouts.
        """
        h = self._handle()
        ffi, lib = _shim()
        otype = ffi.new("int *")
        oval = ffi.new("int *")
        rc = lib.pyte_job_wait(h, _ms(timeout), otype, oval)
        if rc != 0 and (lib.pyte_rc_error(rc) ==
                        lib.pyte_rc_error(lib.PYTE_EINPROGRESS)):
            raise TeTimeoutError(rc, f"job.wait({self.program}): "
                                     "still running")
        check(rc, f"job.wait({self.program})")
        kind = {lib.PYTE_JOB_EXITED: StatusKind.EXITED,
                lib.PYTE_JOB_SIGNALED: StatusKind.SIGNALED}.get(
                    otype[0], StatusKind.UNKNOWN)
        return JobStatus(kind, oval[0])

    def stop(self, timeout: float = DEFAULT_TIMEOUT,
             signal: int | signal.Signals = signal.SIGTERM) -> None:
        """Terminate gracefully; SIGKILL after timeout expires."""
        h = self._handle()
        lib = _shim_lib()
        check(lib.pyte_job_stop(h, _signo(signal), _ms(timeout)),
              f"job.stop({self.program})")

    def restart(self, timeout: float = DEFAULT_TIMEOUT,
                signal: int | signal.Signals = signal.SIGTERM) -> None:
        """Stop the job if it is running, then start it again.

        tapi_job has no restart call (tapi_job.h documents stopping
        as "Stop a job.  It can be started over with
        tapi_job_start()"), so this is stop-then-start.  Stop errors
        are ignored: a job that already completed (and was waited
        for) or never ran needs no stopping.  Primary channels and
        filters stay attached; the agent re-binds them to the new
        process on start.
        """
        from pyte.errors import TeError
        try:
            self.stop(timeout=timeout, signal=signal)
        except TeError:
            pass
        self.start()

    def wrap(self, tool: str, args: list[str] | None = None,
             priority: str = "default") -> Wrapper:
        """Prefix the job's command line with tool (tapi_job_wrapper_add).

        Must be called before start().  args are the wrapper tool's
        arguments (argv[0] = tool is added here, mirroring create()).
        priority is "low", "default" or "high"; wrappers stack right
        to left within a priority level.
        """
        ffi, lib = _shim()
        try:
            prio = {"low": lib.PYTE_JOB_WRAPPER_PRIORITY_LOW,
                    "default": lib.PYTE_JOB_WRAPPER_PRIORITY_DEFAULT,
                    "high": lib.PYTE_JOB_WRAPPER_PRIORITY_HIGH}[priority]
        except KeyError:
            raise ValueError(
                f"priority must be 'low', 'default' or 'high', "
                f"got {priority!r}") from None
        # Keep the cdata strings alive in locals across the call.
        argv_strs = [ffi.new("char[]", _enc(a))
                     for a in [tool, *(args or [])]]
        argv = ffi.new("const char *[]", [*argv_strs, ffi.NULL])
        out = ffi.new("tapi_job_wrapper_t **")
        check(lib.pyte_job_wrapper_add(self._handle(), _enc(tool), argv,
                                       prio, out),
              f"job.wrap({tool})")
        return Wrapper(self, out[0])

    def tracing(self, enable: bool) -> None:
        """Toggle per-call RPC logging for this job's operations.

        Wraps tapi_job_set_tracing(): affects the job and all of its
        channels and filters; errors are still logged either way.
        """
        if self._h is None:      # after destroy(): no-op, mirrors destroy()
            return               # idempotence; a NULL handle would crash in C
        lib = _shim_lib()
        lib.pyte_job_set_tracing(self._h, 1 if enable else 0)

    @contextmanager
    def quiet(self):
        """Suppress RPC tracing for the block.

        The C suites' set_tracing(FALSE)/.../set_tracing(TRUE) idiom
        around chatty polling loops; tracing is restored even if the
        block raises.
        """
        self.tracing(False)
        try:
            yield self
        finally:
            self.tracing(True)

    def kill(self, signal: int | signal.Signals = signal.SIGKILL) -> None:
        """Send a signal to the job."""
        h = self._handle()
        lib = _shim_lib()
        check(lib.pyte_job_kill(h, _signo(signal)),
              f"job.kill({self.program}, {signal})")

    def destroy(self, timeout: float = DEFAULT_TIMEOUT) -> None:
        """Destroy the job (terminating it if needed) and its factory.

        Idempotent: safe to call more than once.  Channel, Filter and
        InputChannel objects created from this job are invalidated:
        TE frees them together with the job, so any further use would
        dereference freed memory in C — they raise RuntimeError
        instead.
        """
        lib = _shim_lib()
        if self._h is not None:
            check(lib.pyte_job_destroy(self._h, _ms(timeout)),
                  f"job.destroy({self.program})")
            self._h = None
            # TE freed all channels/filters with the job: mark every
            # Python wrapper dead so held references raise instead of
            # passing dangling pointers into C.
            for child in (self._stdout, self._stderr, self._stdin,
                          *self._filters):
                if child is not None:
                    child._h = None
            self._stdout = self._stderr = self._stdin = None
            self._filters.clear()
        if self._factory is not None:
            check(lib.pyte_job_factory_destroy(self._factory),
                  "job_factory_destroy")
            self._factory = None

    def __enter__(self) -> "Job":
        return self

    def __exit__(self, *exc) -> bool:
        self.destroy()
        return False

    def __repr__(self) -> str:
        return f"<Job {self.program}>"
