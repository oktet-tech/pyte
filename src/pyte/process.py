# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Processes the Configurator owns, rather than a test.

:mod:`pyte.job` starts a process through an RPC server: it dies with
the test that started it, and it can attach readable output filters so
the test can parse what it printed. This module is the other kind. An
``/agent/process`` entry is plain Configurator state, so it outlives
the test that created it -- a prologue can start one and an epilogue
several tests later can stop it -- and the *agent* attaches its stdout
and stderr filters, at RING and WARN, without being asked (see the
Test Agent's ``ps_enable_stdout_and_stderr_logging``).

Those agent-side filters are not readable: on their own the streams
reach the log and nothing else. The entry's output settings change
that (``Process.create(stdout_file=..., stdout_log_level=...)``): the
agent also writes a stream to a file on its host, which
:class:`Output` reads back by offset, and a level of ``"none"`` keeps
the stream out of the log. An agent built from an older TE has no
such settings, see :meth:`Process.create`. Code that must react to
output as it arrives (wait for a line, match a pattern) still wants
:mod:`pyte.job`.

The model is ``doc/cm/cm_process.yml`` in TE.
"""
from __future__ import annotations

from pyte import cfg, errors
from pyte._cleanup import cleanup_all
from pyte.errors import ProcessOutputUnsupportedError, RpcError
from pyte.rpc.files import open_file


class Process:
    """A ``/agent:<ta>/process:<name>`` entry.

    Cheap to construct and holds no state of its own: every property
    reads the configuration tree. That is what lets one process create
    the entry and an entirely different one, in a later test, act on
    it by name.
    """

    def __init__(self, ta: str, name: str) -> None:
        self.ta = ta
        self.name = name

    @property
    def oid(self) -> str:
        """The process instance's OID."""
        return f"/agent:{self.ta}/process:{self.name}"

    @classmethod
    def create(cls, ta: str, name: str, exe: str,
               args: "list[str] | tuple[str, ...]" = (),
               env: "dict[str, str] | None" = None,
               workdir: str | None = None,
               stdout_file: str | None = None,
               stdout_log_level: str | None = None,
               stderr_file: str | None = None,
               stderr_log_level: str | None = None) -> "Process":
        """Add the entry and configure it, without starting it.

        ``args`` are raw arguments, installed as ``arg:`` instances
        named by their order. cm_process.yml calls that instance name
        "the order" and the agent replays them sorted by it, so the
        names start at 1 and must not be sparse.

        Nothing here starts the process: cm_process.yml forbids
        reconfiguring a running one, so every knob is written first
        and :meth:`start` comes after.

        The mix of set and add follows the model's access modes, and
        getting it wrong fails at run time rather than here: ``exe``
        and ``workdir`` are ``read_write``, so they come into being
        with the parent instance and adding one returns CS-EEXIST,
        while ``arg`` and ``env`` are ``read_create`` and have to be
        added.

        ``stdout_file`` and ``stderr_file`` ask the agent to write the
        stream to that file on the agent instead of (or besides) the
        log, and the ``*_log_level`` arguments set the level the agent
        logs the stream at (``"none"`` turns the log off). Each is
        written only when given, so an unset one leaves the agent's
        default alone. :class:`Output` reads such a file back.

        An agent built from a TE older than these settings has no
        ``output`` nodes. Asking for one there raises
        :class:`~pyte.errors.ProcessOutputUnsupportedError` (a
        :class:`~pyte.errors.CfgNotFoundError`) before anything else is
        written, and the entry just added is removed again, so the
        caller can create it once more without them.
        """
        self = cls(ta, name)
        outputs = [(stream, path, level) for stream, path, level in (
                       ("stdout", stdout_file, stdout_log_level),
                       ("stderr", stderr_file, stderr_log_level))
                   if path is not None or level is not None]
        cfg.add(self.oid)
        for stream, _path, _level in outputs:
            if not cfg.exists(f"{self.oid}/output:{stream}"):
                exc = ProcessOutputUnsupportedError(
                    f"Agent {ta} has no process output settings "
                    f"({self.oid}/output:{stream} does not exist): it "
                    f"runs a TE older than them")
                cleanup_all(self.destroy, primary=exc)
                raise exc
        cfg.set(f"{self.oid}/exe:", exe)
        for order, arg in enumerate(args, start=1):
            cfg.add(f"{self.oid}/arg:{order}", arg)
        for key, value in (env or {}).items():
            cfg.add(f"{self.oid}/env:{key}", value)
        if workdir is not None:
            cfg.set(f"{self.oid}/workdir:", workdir)
        for stream, path, level in outputs:
            if path is not None:
                cfg.set(f"{self.oid}/output:{stream}/file:", path)
            if level is not None:
                cfg.set(f"{self.oid}/output:{stream}/log_level:", level)
        return self

    def start(self) -> None:
        """Start the process."""
        cfg.set(f"{self.oid}/status:", 1)

    def stop(self) -> None:
        """Stop the process.

        The agent sends SIGTERM, then SIGKILL after a short grace
        period, to the whole process group by default (see the
        model's ``stop_group``), so a program started through a
        wrapper script goes down with the wrapper.
        """
        cfg.set(f"{self.oid}/status:", 0)

    def destroy(self) -> None:
        """Remove the entry and everything under it.

        The parent instance alone is deleted: its ``arg``, ``env`` and
        ``option`` children go with it on the agent, and the
        ``read_write`` leaves (``exe``, ``status``, ``workdir``...)
        cannot be deleted on their own at all. Asking for the children
        too made the Configurator log an ERROR for every such leaf
        before deleting the parent anyway. This is what the C TAPI's
        tapi_cfg_ps_del() does as well.
        """
        cfg.delete(self.oid)

    def kill(self, signal: str, group: bool = False) -> None:
        """Send ``signal`` to the process, or to its process group."""
        leaf = "group" if group else "self"
        cfg.set(f"{self.oid}/kill:/{leaf}:", signal)

    @property
    def exists(self) -> bool:
        """Whether the entry is present in the configuration tree."""
        return cfg.exists(self.oid)

    @property
    def running(self) -> bool:
        """Whether the agent reports the process as running.

        Read with ``sync=True``: the process can exit on its own, and
        a cached value would report a dead one as alive -- which is
        precisely the case a caller asks this question to catch.
        """
        return bool(cfg.get(f"{self.oid}/status:", sync=True))

    @property
    def exit_status(self) -> tuple[int, int]:
        """``(type, value)`` of the last termination.

        Type 0 is a normal exit and the value is its status; type 1 is
        a signal and the value is its number; type 2 means the process
        has never terminated, and the value is then meaningless.
        """
        base = f"{self.oid}/status:/exit_status:"
        return (int(cfg.get(f"{base}/type:", sync=True)),
                int(cfg.get(f"{base}/value:", sync=True)))


#: Largest single read from the agent, bytes.
_READ_CHUNK = 64 * 1024


class Output:
    """Offset-based reader of a file an agent process writes to.

    Pair it with ``Process.create(stdout_file=...)``: the agent keeps
    appending, and this class returns what appeared since a point the
    test chose. The file is opened and closed on every call, so no
    descriptor outlives a call and the object holds no RPC state of its
    own. Each of its RPCs runs in its own
    ``server.silent_pass_once()`` block: polling adds no rows to the
    test log, only a failing call is logged.

    There are two positions. The *cursor* moves with :meth:`new`; the
    *mark* is set by :meth:`mark` and only :meth:`since_mark` and
    :meth:`save_since_mark` look at it. Both start at 0, so before
    :meth:`mark` is called they cover the whole file.

    A file that is missing reads as empty; any other failure to open
    it raises :class:`~pyte.errors.RpcError`. A file that is shorter than
    a position (truncated or replaced) restarts from 0. ``cap`` bounds
    what :meth:`new` and :meth:`since_mark` return to the newest
    ``cap`` bytes; :meth:`save_since_mark` is not capped.
    """

    def __init__(self, server, path: str, cap: int = 1 << 20):
        self.server = server
        self.path = path
        self.cap = cap
        self._cursor = 0
        self._mark = 0

    def _quiet(self, call, *args):
        """Make one RPC without a log row (unless it fails).

        One call per :meth:`~pyte.rpc.server.RpcServer.silent_pass_once`
        block: TE consumes the flag on the first call it skips.
        """
        with self.server.silent_pass_once():
            return call(*args)

    def _read(self, start: int, cap: int | None, sink) -> int:
        """Feed ``sink`` the bytes from ``start`` to the end; return
        the size seen at open (``start`` when the file is missing)."""
        quiet = self._quiet
        try:
            f = quiet(open_file, self.server, self.path, "r")
        except RpcError as exc:
            if exc.code != errors.ENOENT:
                raise
            return start
        try:
            # Not f.size(): it restores the position, and the seek
            # below overwrites it anyway.
            end = quiet(f.seek, 0, 2)
            if end < start:
                start = 0
            if cap is not None and end - start > cap:
                start = end - cap
            pos = start
            if pos < end:
                quiet(f.seek, pos, 0)
            while pos < end:
                chunk = quiet(f.read, min(_READ_CHUNK, end - pos))
                if not chunk:
                    break
                sink(chunk)
                pos += len(chunk)
        except BaseException as exc:
            cleanup_all(lambda: quiet(f.close), primary=exc)
            raise
        quiet(f.close)
        return end

    def _text(self, start: int) -> tuple[str, int]:
        parts: list[bytes] = []
        end = self._read(start, self.cap, parts.append)
        return b"".join(parts).decode("utf-8", errors="replace"), end

    def mark(self) -> None:
        """Set the cursor and the mark to the current end of the file."""
        end = self._read(0, 0, lambda _chunk: None)
        self._cursor = self._mark = end

    def new(self) -> str:
        """The text written since the cursor; advances the cursor.

        Calls do not join their bytes: a multibyte character split
        across two calls decodes as two or more replacement characters,
        at least one in each call's text.
        """
        text, end = self._text(self._cursor)
        self._cursor = end
        return text

    def since_mark(self) -> str:
        """The text written since the mark; the cursor is untouched."""
        return self._text(self._mark)[0]

    def save_since_mark(self, local_path) -> int:
        """Write everything since the mark to a local file.

        Not capped, and copied chunk by chunk, so a large output never
        sits in memory. Returns the number of bytes written.
        """
        written = 0
        with open(local_path, "wb") as out:
            def sink(chunk: bytes) -> None:
                nonlocal written
                out.write(chunk)
                written += len(chunk)
            self._read(self._mark, None, sink)
        return written
