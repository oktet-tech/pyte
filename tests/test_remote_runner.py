# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Drive the real remote runner as a subprocess over pipes (no TE)."""
import json
import pathlib
import subprocess
import sys

import pytest

RUNNER = (pathlib.Path(__file__).parent.parent
          / "src" / "pyte" / "_remote_runner.py")


class RunnerProc:
    """A live runner subprocess speaking line-delimited JSON."""

    def __init__(self):
        self.proc = subprocess.Popen(
            [sys.executable, "-u", "-c", RUNNER.read_text()],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True)
        self._id = 0

    def request(self, op, **fields):
        self._id += 1
        req = {"id": self._id, "op": op, **fields}
        self.proc.stdin.write(json.dumps(req) + "\n")
        self.proc.stdin.flush()
        resp = json.loads(self.proc.stdout.readline())
        assert resp["id"] == self._id
        return resp

    def send_raw(self, line):
        """Write a raw line to stdin, read and return one response line."""
        self.proc.stdin.write(line)
        self.proc.stdin.flush()
        return json.loads(self.proc.stdout.readline())

    def close(self):
        self.proc.stdin.close()
        self.proc.wait(timeout=10)


@pytest.fixture
def runner():
    r = RunnerProc()
    yield r
    r.proc.kill()
    r.proc.wait()


SRC_ADD = "def add(a, b):\n    return a + b\n"
SRC_BOOM = "def boom():\n    return 1 // 0\n"
SRC_PRINT = "def chatty():\n    print('hello from agent')\n    return 7\n"
SRC_GRAB = "def grab(buf):\n    return buf.getvalue()\n"
SRC_REF_DICT = "def ref_dict():\n    return {'__pyte_ref__': 123}\n"


def test_call_returns_value(runner):
    resp = runner.request("call", src=SRC_ADD, fname="add",
                          args=[2, 3], kwargs={})
    assert resp == {"id": 1, "ok": True, "value": 5}


def test_call_kwargs(runner):
    resp = runner.request("call", src=SRC_ADD, fname="add",
                          args=[2], kwargs={"b": 40})
    assert resp["value"] == 42


def test_import_returns_ref(runner):
    resp = runner.request("import", module="json")
    assert resp["ok"] is True
    assert set(resp["value"]) == {"__pyte_ref__"}


def test_getattr_value_vs_ref(runner):
    mod = runner.request("import", module="math")["value"]
    pi = runner.request("getattr", obj=mod["__pyte_ref__"], name="pi")
    assert pi["ok"] is True and abs(pi["value"] - 3.14159) < 1e-3
    sqrt = runner.request("getattr", obj=mod["__pyte_ref__"],
                          name="sqrt")
    assert set(sqrt["value"]) == {"__pyte_ref__"}


def test_callobj_and_ref_args(runner):
    """Refs are valid as arguments: pass a live object through a ref dict."""
    # Set up a remote StringIO, write to it, hold its ref.
    mod = runner.request("import", module="io")["value"]
    sio_cls = runner.request("getattr", obj=mod["__pyte_ref__"],
                             name="StringIO")["value"]
    sio = runner.request("callobj", obj=sio_cls["__pyte_ref__"],
                         args=[], kwargs={})["value"]
    write = runner.request("getattr", obj=sio["__pyte_ref__"],
                           name="write")["value"]
    runner.request("callobj", obj=write["__pyte_ref__"],
                   args=["hello"], kwargs={})

    # Ship a function whose arg IS the ref dict — runner must decode it
    # to the live StringIO and return its contents.
    resp = runner.request("call", src=SRC_GRAB, fname="grab",
                          args=[sio], kwargs={})
    assert resp["ok"] is True
    assert resp["value"] == "hello"

    # Also exercise a ref nested inside a list arg (recursive decode).
    resp2 = runner.request("call",
                           src="def unwrap(lst):\n    return lst[0].getvalue()\n",
                           fname="unwrap",
                           args=[[sio]], kwargs={})
    assert resp2["ok"] is True
    assert resp2["value"] == "hello"


def test_state_persists_across_calls(runner):
    mod = runner.request("import", module="io")["value"]
    sio_cls = runner.request("getattr", obj=mod["__pyte_ref__"],
                             name="StringIO")["value"]
    sio = runner.request("callobj", obj=sio_cls["__pyte_ref__"],
                         args=[], kwargs={})["value"]
    write = runner.request("getattr", obj=sio["__pyte_ref__"],
                           name="write")["value"]
    runner.request("callobj", obj=write["__pyte_ref__"],
                   args=["abc"], kwargs={})
    getvalue = runner.request("getattr", obj=sio["__pyte_ref__"],
                              name="getvalue")["value"]
    resp = runner.request("callobj", obj=getvalue["__pyte_ref__"],
                          args=[], kwargs={})
    assert resp["value"] == "abc"


def test_remote_exception(runner):
    resp = runner.request("call", src=SRC_BOOM, fname="boom",
                          args=[], kwargs={})
    assert resp["ok"] is False
    assert resp["type"] == "ZeroDivisionError"
    assert "ZeroDivisionError" in resp["traceback"]


def test_runner_survives_exception(runner):
    runner.request("call", src=SRC_BOOM, fname="boom",
                   args=[], kwargs={})
    resp = runner.request("call", src=SRC_ADD, fname="add",
                          args=[1, 1], kwargs={})
    assert resp["value"] == 2


def test_unknown_op_is_error_not_death(runner):
    resp = runner.request("frobnicate")
    assert resp["ok"] is False
    resp = runner.request("call", src=SRC_ADD, fname="add",
                          args=[1, 1], kwargs={})
    assert resp["value"] == 2


def test_user_print_goes_to_stderr(runner):
    resp = runner.request("call", src=SRC_PRINT, fname="chatty",
                          args=[], kwargs={})
    assert resp["value"] == 7
    runner.request("shutdown")
    runner.close()
    err = runner.proc.stderr.read()
    assert "hello from agent" in err


def test_shutdown_clean_exit(runner):
    resp = runner.request("shutdown")
    assert resp["ok"] is True
    runner.close()
    assert runner.proc.returncode == 0


def test_runner_importable_without_running():
    import pyte._remote_runner as rr
    assert hasattr(rr, "main")


def test_garbage_line_is_error_not_death(runner):
    """A corrupt (non-JSON) line yields an error response; runner continues."""
    resp = runner.send_raw("not json at all\n")
    assert resp["ok"] is False
    assert resp["id"] is None
    # Runner must still serve a subsequent valid request.
    resp2 = runner.request("call", src=SRC_ADD, fname="add",
                           args=[3, 4], kwargs={})
    assert resp2["ok"] is True
    assert resp2["value"] == 7


def test_unknown_handle_is_error_not_death(runner):
    """A getattr on a non-existent handle yields ok=False; runner continues."""
    resp = runner.request("getattr", obj=9999, name="anything")
    assert resp["ok"] is False
    # Runner must still serve a subsequent valid request.
    resp2 = runner.request("call", src=SRC_ADD, fname="add",
                           args=[10, 20], kwargs={})
    assert resp2["ok"] is True
    assert resp2["value"] == 30


def test_ref_key_collision_stashed_as_ref(runner):
    """A user value that is a dict with __pyte_ref__ is stashed, not crossed."""
    resp = runner.request("call", src=SRC_REF_DICT, fname="ref_dict",
                          args=[], kwargs={})
    assert resp["ok"] is True
    # Must come back as a ref (a single-key dict with __pyte_ref__),
    # NOT as the raw {"__pyte_ref__": 123} (which would be misread).
    assert set(resp["value"]) == {"__pyte_ref__"}
    # The handle must NOT be 123 — it's a runner-assigned handle.
    assert resp["value"]["__pyte_ref__"] != 123
