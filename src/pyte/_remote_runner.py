# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Agent-side runner for pyte.remote.

This module's SOURCE is shipped to the agent host verbatim and run
there as ``python3 -u -c <source>`` — it executes on a bare host
interpreter and therefore MUST stay stdlib-only and self-contained
(no pyte imports, no relative imports).  It is a real module so ruff
lints it and unit tests import/drive it; the serve loop only runs
under ``__main__``.

Protocol: line-delimited JSON, one request line in (stdin), one
response line out (the real stdout).  ``sys.stdout`` is rebound to
``sys.stderr`` before serving so user ``print()``s end up in the TE
log (stderr filter) instead of corrupting the protocol stream.

Marshalling: JSON-serializable values cross by value; anything else
is stored in a per-session table and crosses as
``{"__pyte_ref__": handle}``.  The ``__pyte_ref__`` key is reserved.
"""
import importlib
import json
import sys
import traceback

REF_KEY = "__pyte_ref__"


class Runner:
    """Serve protocol requests from rfile, respond on wfile."""

    def __init__(self, rfile, wfile):
        self._rfile = rfile
        self._wfile = wfile
        self._objects = {}
        self._next_handle = 1

    # -- marshalling ---------------------------------------------------
    def _encode(self, value):
        """By value if JSON-serializable, else stash and return a ref."""
        try:
            json.dumps(value)
            return value
        except (TypeError, ValueError):
            handle = self._next_handle
            self._next_handle += 1
            self._objects[handle] = value
            return {REF_KEY: handle}

    def _decode(self, value):
        """Swap refs back to live objects, recursing into containers."""
        if isinstance(value, dict):
            if set(value) == {REF_KEY}:
                return self._objects[value[REF_KEY]]
            return {k: self._decode(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._decode(v) for v in value]
        return value

    # -- ops -----------------------------------------------------------
    def _dispatch(self, req):
        op = req["op"]
        args = [self._decode(a) for a in req.get("args", [])]
        kwargs = {k: self._decode(v)
                  for k, v in req.get("kwargs", {}).items()}
        if op == "call":
            ns = {}
            exec(req["src"], ns)  # noqa: S102
            return ns[req["fname"]](*args, **kwargs)
        if op == "import":
            return importlib.import_module(req["module"])
        if op == "getattr":
            return getattr(self._objects[req["obj"]], req["name"])
        if op == "callobj":
            return self._objects[req["obj"]](*args, **kwargs)
        raise ValueError("unknown op %r" % (op,))

    # -- loop ----------------------------------------------------------
    def _respond(self, payload):
        self._wfile.write(json.dumps(payload) + "\n")
        self._wfile.flush()

    def serve(self):
        for line in self._rfile:
            line = line.strip()
            if not line:
                continue
            req = json.loads(line)
            rid = req.get("id")
            if req.get("op") == "shutdown":
                self._respond({"id": rid, "ok": True, "value": None})
                return
            try:
                value = self._dispatch(req)
                self._respond({"id": rid, "ok": True,
                               "value": self._encode(value)})
            except Exception as exc:  # report, don't die  # noqa: BLE001
                self._respond({"id": rid, "ok": False,
                               "type": type(exc).__name__,
                               "msg": str(exc),
                               "traceback": traceback.format_exc()})


def main():
    proto_out = sys.stdout
    sys.stdout = sys.stderr  # user print()s -> TE log, not protocol
    Runner(sys.stdin, proto_out).serve()


if __name__ == "__main__":
    main()
