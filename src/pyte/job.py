# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""tapi_job wrapper: jobs, output channels, filters, messages."""
from __future__ import annotations

import signal
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Iterator

from pyte.errors import check
from pyte.errors import TimeoutError as TeTimeoutError
from pyte.log import _enc

if TYPE_CHECKING:
    from pyte.rpc.server import RpcServer

#: Default timeout (seconds) for job waits/receives.
DEFAULT_TIMEOUT = 10.0


def _ms(timeout: float) -> int:
    """Convert float seconds to int milliseconds."""
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
    from pyte._shim import lib
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

    ``data`` is text decoded from UTF-8 (errors replaced with U+FFFD).
    TE truncates data at interior NUL bytes before delivery, so
    ``data`` may be shorter than the raw output.  This is asymmetric
    with :meth:`InputChannel.send`, which is binary-safe.
    """
    data: str
    eos: bool
    dropped: int
    filter: "Filter"


class Channel:
    """A primary output channel (stdout/stderr) of a job."""

    def __init__(self, job: "Job", handle, name: str):
        self._job = job
        self._h = handle
        self.name = name

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

    def log(self, level: int | str | None = None) -> "Filter":
        """Send everything on this channel to the TE log (RING level
        by default); the output is not readable from the test.
        """
        return self.attach_filter(name=f"{self.name}-log", readable=False,
                                  log_level=level if level is not None
                                  else "RING")

    def __repr__(self) -> str:
        return f"<Channel {self.name} of {self._job.program}>"


class InputChannel:
    """The stdin channel of a job."""

    def __init__(self, job: "Job", handle):
        self._job = job
        self._h = handle

    def send(self, data: str | bytes) -> None:
        """Write data to the job's stdin (binary-safe)."""
        from pyte._shim import lib
        raw = data.encode("utf-8") if isinstance(data, str) else bytes(data)
        check(lib.pyte_job_send(self._h, raw, len(raw)),
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

    def attach(self, channel: Channel) -> None:
        """Attach this filter to one more output channel.

        Increments the internal channel count so that
        :meth:`messages` waits for the correct number of eos messages.
        """
        from pyte._shim import ffi, lib
        arr = ffi.new("tapi_job_channel_t *[]", [channel._h])
        check(lib.pyte_job_filter_add(self._h, arr, 1),
              f"filter_add_channels({self.name})")
        self._n_channels += 1

    def detach(self, channel: Channel) -> None:
        """Detach this filter from a channel.

        Decrements the internal channel count.  Once detached from all
        its channels the filter is freed by the TAPI and this object
        must not be used again.
        """
        from pyte._shim import ffi, lib
        arr = ffi.new("tapi_job_channel_t *[]", [channel._h])
        check(lib.pyte_job_filter_remove(self._h, arr, 1),
              f"filter_remove_channels({self.name})")
        self._n_channels -= 1

    def next(self, timeout: float = DEFAULT_TIMEOUT) -> JobMessage:
        """Read the next message (raises TimeoutError if none)."""
        return receive_any([self], timeout=timeout)

    def last(self, timeout: float = DEFAULT_TIMEOUT) -> JobMessage:
        """Peek the last message without consuming the queue."""
        return receive_any([self], timeout=timeout, last=True)

    def messages(self,
                 timeout: float = DEFAULT_TIMEOUT) -> Iterator[JobMessage]:
        """Yield messages until all attached channels have sent eos.

        ta_job emits one eos message per attached primary channel, so a
        filter attached to both stdout and stderr receives two eos
        messages.  This method counts them and stops only after all
        ``self._n_channels`` eos messages have been consumed.  Eos
        messages themselves are not yielded.

        ``timeout`` is forwarded to each :meth:`next` call;
        :exc:`pyte.errors.TimeoutError` propagates immediately if a
        receive times out (already-yielded messages are not replayed).
        """
        eos_seen = 0
        while eos_seen < self._n_channels:
            msg = self.next(timeout=timeout)
            if msg.eos:
                eos_seen += 1
            else:
                yield msg

    def drain(self, timeout: float = DEFAULT_TIMEOUT) -> list[JobMessage]:
        """Read ALL queued messages in one tapi_job_receive_many() call.

        Eos messages are consumed but not returned.  One RPC instead
        of one per message; a short read (e.g. the job still running)
        shows up as missing eos entries, not as an error.
        """
        return self.read_many(0, timeout=timeout)

    def read_many(self, count: int,
                  timeout: float = DEFAULT_TIMEOUT) -> list[JobMessage]:
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
        from pyte._shim import ffi, lib
        flts = ffi.new("tapi_job_channel_t *[]", [self._h])
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
                data = ffi.buffer(datas[0][i], lens[0][i])[:].decode(
                    "utf-8", "replace")
                out.append(JobMessage(data=data, eos=False, dropped=0,
                                      filter=self))
            return out
        finally:
            lib.pyte_job_receive_many_free(datas[0], lens[0], eos[0], n[0])

    def read_all(self, timeout: float = DEFAULT_TIMEOUT) -> str:
        """Concatenate all message data until end-of-stream.

        Calls :meth:`messages` internally; :exc:`pyte.errors.TimeoutError`
        propagates if a receive times out mid-stream.
        """
        return "".join(m.data for m in self.messages(timeout=timeout))

    def __repr__(self) -> str:
        return f"<Filter {self.name} of {self._job.program}>"


def _attach_filter(channels: list[Channel], *, name: str | None,
                   readable: bool, log_level: int | str | None,
                   regex: str | None, group: int) -> Filter:
    from pyte._shim import ffi, lib
    if not channels:
        raise ValueError("no channels to attach the filter to")
    job = channels[0]._job
    arr = ffi.new("tapi_job_channel_t *[]", [c._h for c in channels])
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
    return flt


def receive_any(filters: list[Filter], timeout: float = DEFAULT_TIMEOUT,
                last: bool = False) -> JobMessage:
    """Read the next message from any of the given filters.

    The returned :class:`JobMessage` ``data`` field is text decoded
    from UTF-8 (errors replaced).  TE truncates output at interior NUL
    bytes before delivery, so ``data`` may be shorter than the raw
    output — asymmetric with :meth:`InputChannel.send` which is
    binary-safe.

    Raises :exc:`pyte.errors.TimeoutError` if nothing arrives in time.
    """
    from pyte._shim import ffi, lib
    if not filters:
        raise ValueError("no filters to receive from")
    arr = ffi.new("tapi_job_channel_t *[]", [f._h for f in filters])
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
    return JobMessage(data=raw.decode("utf-8", errors="replace"),
                      eos=bool(eos[0]), dropped=dropped[0], filter=flt)


def poll(items: list[Channel | InputChannel | Filter],
         timeout: float = DEFAULT_TIMEOUT) -> None:
    """Wait until one of the channels/filters is ready.

    Raises pyte.errors.TimeoutError if none becomes ready in time.
    """
    from pyte._shim import ffi, lib
    if not items:
        raise ValueError("no channels to poll")
    arr = ffi.new("tapi_job_channel_t *[]", [i._h for i in items])
    check(lib.pyte_job_poll(arr, len(items), _ms(timeout)), "job.poll")


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
        from pyte._shim import lib
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
        self._stdout: Channel | None = None
        self._stderr: Channel | None = None
        self._stdin: InputChannel | None = None

    @classmethod
    def create(cls, server: "RpcServer", program: str, args: list[str],
               env: dict[str, str] | None = None) -> "Job":
        """Create (but do not start) a job running program on server.

        args are the program arguments (argv[0] = program is added
        here, per the exec convention tapi_job_create() expects).
        env replaces the whole environment when given (None inherits).

        The argv/env cffi arrays are built before the factory is
        created so that a Python-side exception (e.g. encoding error)
        cannot leak an allocated factory handle.
        """
        from pyte._shim import ffi, lib
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
        return cls(fac[0], out[0], program)

    # -- channels ------------------------------------------------------
    def _alloc_out(self) -> None:
        if self._stdout is None:
            from pyte._shim import ffi, lib
            o = ffi.new("tapi_job_channel_t **")
            e = ffi.new("tapi_job_channel_t **")
            check(lib.pyte_job_out_channels(self._h, o, e),
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

        Touch this property before start(): a channel allocated after
        the process is spawned is not bound to it (TE_EBADFD on send).
        """
        if self._stdin is None:
            from pyte._shim import ffi, lib
            i = ffi.new("tapi_job_channel_t **")
            check(lib.pyte_job_in_channel(self._h, i),
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
        from pyte._shim import lib
        check(lib.pyte_job_start(self._h), f"job.start({self.program})")

    def wait(self, timeout: float = DEFAULT_TIMEOUT) -> JobStatus:
        """Wait for completion; raises TimeoutError if still running.

        tapi_job_wait() reports a still-running job as TE_EINPROGRESS;
        convert that to the same TimeoutError as other timeouts.
        """
        from pyte._shim import ffi, lib
        otype = ffi.new("int *")
        oval = ffi.new("int *")
        rc = lib.pyte_job_wait(self._h, _ms(timeout), otype, oval)
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
        from pyte._shim import lib
        check(lib.pyte_job_stop(self._h, _signo(signal), _ms(timeout)),
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
        from pyte._shim import ffi, lib
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
        check(lib.pyte_job_wrapper_add(self._h, _enc(tool), argv, prio, out),
              f"job.wrap({tool})")
        return Wrapper(self, out[0])

    def tracing(self, enable: bool) -> None:
        """Toggle per-call RPC logging for this job's operations.

        Wraps tapi_job_set_tracing(): affects the job and all of its
        channels and filters; errors are still logged either way.
        """
        if self._h is None:      # after destroy(): no-op, mirrors destroy()
            return               # idempotence; a NULL handle would crash in C
        from pyte._shim import lib
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
        from pyte._shim import lib
        check(lib.pyte_job_kill(self._h, _signo(signal)),
              f"job.kill({self.program}, {signal})")

    def destroy(self, timeout: float = DEFAULT_TIMEOUT) -> None:
        """Destroy the job (terminating it if needed) and its factory.

        Idempotent: safe to call more than once.
        """
        from pyte._shim import lib
        if self._h is not None:
            check(lib.pyte_job_destroy(self._h, _ms(timeout)),
                  f"job.destroy({self.program})")
            self._h = None
            self._stdout = self._stderr = self._stdin = None
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
