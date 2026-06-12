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
    mod = runner.request("import", module="json")["value"]
    dumps = runner.request("getattr", obj=mod["__pyte_ref__"],
                           name="dumps")["value"]
    resp = runner.request("callobj", obj=dumps["__pyte_ref__"],
                          args=[[1, 2]], kwargs={})
    assert resp["value"] == "[1, 2]"
    # A ref is valid as an argument: getattr on a proxied str.
    loads = runner.request("getattr", obj=mod["__pyte_ref__"],
                           name="loads")["value"]
    resp = runner.request("callobj", obj=loads["__pyte_ref__"],
                          args=["[5]"], kwargs={})
    assert resp["value"] == [5]


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
