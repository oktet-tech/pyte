# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Run Python code on the agent host (zero install: python3 + stdlib).

A session is a tapi_job running the pyte._remote_runner source via
``python3 -u -c``; requests go down the job's stdin, responses come
back through a readable stdout filter, and stderr is logged to TE
(remote print()s and crashes land in the run log).

Marshalling: JSON-serializable values cross by value; everything else
stays remote and crosses as a RemoteObject proxy — in both directions,
including arguments.  Tuples become lists (JSON), dict keys become
strings.  Shipped functions must be self-contained: imports inside the
body, no closures, no globals (a NameError surfaces in the remote
traceback).

Usage::

    from pyte import remote

    with remote.python(pco) as rem:
        def parse(path):
            import re
            return sum(1 for line in open(path)
                       if re.search(r"ERROR", line))

        n = rem.call(parse, "/var/log/syslog")

        mylib = rem.import_module("sqlite3")
        conn = mylib.connect(":memory:")        # RemoteObject
        rows = conn.execute("select 1").fetchall()
"""
from __future__ import annotations

import inspect
import json
import textwrap
import time
from contextlib import contextmanager
from importlib import resources
from typing import TYPE_CHECKING, Iterator

from pyte.errors import RemotePythonError

if TYPE_CHECKING:
    from pyte.job import Filter, Job
    from pyte.rpc.server import RpcServer

#: Default per-operation timeout (seconds).
DEFAULT_TIMEOUT = 30.0

REF_KEY = "__pyte_ref__"


def _runner_source() -> str:
    return (resources.files("pyte") / "_remote_runner.py").read_text()


def _extract_source(fn) -> tuple[str, str]:
    """Validate a shippable function, return (source, name)."""
    if not inspect.isfunction(fn):
        raise ValueError(f"remote.call needs a plain function, "
                         f"got {fn!r}")
    if fn.__name__ == "<lambda>":
        raise ValueError("remote.call cannot ship a lambda: define a "
                         "named function instead")
    if fn.__closure__:
        raise ValueError(
            f"remote.call cannot ship {fn.__name__}(): closure over "
            f"local variables; pass them as arguments instead")
    try:
        src = inspect.getsource(fn)
    except OSError as exc:
        raise ValueError(f"remote.call: source of {fn.__name__}() is "
                         f"unavailable: {exc}") from exc
    return textwrap.dedent(src), fn.__name__


class RemoteObject:
    """Proxy for an object living in the remote runner.

    Attribute access and calls round-trip to the agent; values come
    back by the marshalling rule (JSON-able -> value, else another
    proxy).  Underscore-prefixed attributes are not proxied.
    """

    def __init__(self, session: "RemotePython", handle: int):
        self._session = session
        self._handle = handle

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        return self._session._request(
            {"op": "getattr", "obj": self._handle, "name": name})

    def __call__(self, *args, **kwargs):
        s = self._session
        return s._request({"op": "callobj", "obj": self._handle,
                           "args": s._encode_args(args),
                           "kwargs": s._encode_kwargs(kwargs)})

    def __repr__(self) -> str:
        return f"<RemoteObject #{self._handle}>"


class RemotePython:
    """A live remote Python session; create with remote.python()."""

    def __init__(self, job: "Job | None", flt: "Filter | None",
                 timeout: float):
        self._job = job
        self._flt = flt
        self._timeout = timeout
        self._last_id = 0
        self._buf = ""

    # -- transport (overridden by unit-test fakes) ----------------------
    def _send(self, req: dict) -> None:
        assert self._job is not None
        self._job.stdin.send(json.dumps(req) + "\n")

    def _recv(self, timeout: float) -> dict:
        """Read one response line from the stdout filter.

        Filter messages are stream chunks, not lines: accumulate and
        split on newlines under a single deadline.  An eos message
        means the runner died.
        """
        assert self._flt is not None
        deadline = time.monotonic() + timeout
        while True:
            nl = self._buf.find("\n")
            if nl >= 0:
                line, self._buf = self._buf[:nl], self._buf[nl + 1:]
                if line.strip():
                    return json.loads(line)
                continue
            remaining = max(deadline - time.monotonic(), 0.001)
            msg = self._flt.next(timeout=remaining)  # raises TimeoutError
            if msg.eos:
                raise RemotePythonError(
                    "remote python runner died "
                    f"({self._job_status() or 'no status'})")
            self._buf += msg.data

    def _job_status(self) -> str | None:
        try:
            assert self._job is not None
            return str(self._job.wait(timeout=0.1))
        except Exception:  # noqa: BLE001
            return None

    # -- marshalling -----------------------------------------------------
    def _encode(self, value):
        if isinstance(value, RemoteObject):
            if value._session is not self:
                raise ValueError(
                    "RemoteObject belongs to another session")
            return {REF_KEY: value._handle}
        if isinstance(value, (list, tuple)):
            return [self._encode(v) for v in value]
        if isinstance(value, dict):
            return {k: self._encode(v) for k, v in value.items()}
        json.dumps(value)  # raises TypeError if not shippable
        return value

    def _encode_args(self, args) -> list:
        return [self._encode(a) for a in args]

    def _encode_kwargs(self, kwargs) -> dict:
        return {k: self._encode(v) for k, v in kwargs.items()}

    def _decode(self, value):
        if isinstance(value, dict) and set(value) == {REF_KEY}:
            return RemoteObject(self, value[REF_KEY])
        return value

    # -- protocol ----------------------------------------------------------
    def _request(self, req: dict, timeout: float | None = None):
        self._last_id += 1
        req = {"id": self._last_id, **req}
        self._send(req)
        resp = self._recv(timeout if timeout is not None
                          else self._timeout)
        if resp.get("id") != self._last_id:
            raise RemotePythonError(
                f"protocol error: response id {resp.get('id')!r}, "
                f"expected {self._last_id}")
        if not resp["ok"]:
            raise RemotePythonError(
                f"remote {resp['type']}: {resp['msg']}\n"
                f"{resp['traceback']}",
                remote_traceback=resp["traceback"])
        return self._decode(resp["value"])

    # -- public API -------------------------------------------------------
    def call(self, fn, *args, timeout: float | None = None, **kwargs):
        """Ship a self-contained function, run it remotely.

        The function source is extracted with inspect.getsource():
        imports go inside the body, no closures/globals; arguments
        and the result follow the marshalling rule.
        """
        src, fname = _extract_source(fn)
        return self._request({"op": "call", "src": src, "fname": fname,
                              "args": self._encode_args(args),
                              "kwargs": self._encode_kwargs(kwargs)},
                             timeout=timeout)

    def import_module(self, name: str,
                      timeout: float | None = None) -> RemoteObject:
        """Import a module on the agent host, return its proxy."""
        obj = self._request({"op": "import", "module": name},
                            timeout=timeout)
        assert isinstance(obj, RemoteObject)
        return obj

    def _shutdown(self) -> None:
        """Best-effort orderly runner exit (session teardown)."""
        try:
            self._request({"op": "shutdown"}, timeout=5.0)
        except Exception:  # noqa: BLE001
            pass  # runner already dead / stuck: job.destroy() kills it


@contextmanager
def python(pco: "RpcServer", timeout: float = DEFAULT_TIMEOUT,
           interpreter: str = "python3") -> Iterator[RemotePython]:
    """Start a remote Python session on pco's agent.

    Zero install on the agent: only ``interpreter`` (python3) with the
    stdlib is required there; the runner ships in argv.
    """
    with pco.job(interpreter, ["-u", "-c", _runner_source()]) as job:
        _ = job.stdin                     # MUST allocate before start()
        flt = job.stdout.attach_filter(name="pyte-remote")
        job.stderr.log()
        job.start()
        session = RemotePython(job, flt, timeout)
        try:
            yield session
        finally:
            session._shutdown()
