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

The trade is that those agent-side filters are not readable: the
streams reach the log and nothing else. Code that must parse a
process's output wants :mod:`pyte.job`, not this.

The model is ``doc/cm/cm_process.yml`` in TE.
"""
from __future__ import annotations

from pyte import cfg


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
               workdir: str | None = None) -> "Process":
        """Add the entry and configure it, without starting it.

        ``args`` are raw arguments, installed as ``arg:`` instances
        named by their order. cm_process.yml calls that instance name
        "the order" and the agent replays them sorted by it, so the
        names start at 1 and must not be sparse.

        Nothing here starts the process: cm_process.yml forbids
        reconfiguring a running one, so every knob is written first
        and :meth:`start` comes after.
        """
        self = cls(ta, name)
        cfg.add(self.oid)
        cfg.add(f"{self.oid}/exe:", exe)
        for order, arg in enumerate(args, start=1):
            cfg.add(f"{self.oid}/arg:{order}", arg)
        for key, value in (env or {}).items():
            cfg.add(f"{self.oid}/env:{key}", value)
        if workdir is not None:
            cfg.add(f"{self.oid}/workdir:", workdir)
        return self

    def start(self) -> None:
        """Start the process."""
        cfg.set(f"{self.oid}/status:", 1)

    def stop(self) -> None:
        """Stop the process."""
        cfg.set(f"{self.oid}/status:", 0)

    def destroy(self) -> None:
        """Remove the entry and everything under it."""
        cfg.delete(self.oid, children=True)

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
