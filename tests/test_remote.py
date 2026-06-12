# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Engine-side pyte.remote tests: fake transport + real-runner bridge."""
import json
import pathlib
import subprocess
import sys

import pytest

from pyte import remote
from pyte.errors import RemotePythonError

RUNNER = (pathlib.Path(__file__).parent.parent
          / "src" / "pyte" / "_remote_runner.py")


class FakeSession(remote.RemotePython):
    """Records requests, replays canned responses; no job behind it."""

    def __init__(self):
        super().__init__(job=None, flt=None, timeout=5.0)
        self.sent = []
        self.replies = []

    def _send(self, req):
        self.sent.append(req)

    def _recv(self, timeout):
        return self.replies.pop(0)


def _reply_to(session, value):
    session.replies.append(
        {"id": session._last_id + 1, "ok": True, "value": value})


def outer(a):
    return a + 1


def test_call_ships_source_and_decodes_value():
    s = FakeSession()
    _reply_to(s, 5)
    assert s.call(outer, 4) == 5
    req = s.sent[0]
    assert req["op"] == "call" and req["fname"] == "outer"
    assert "def outer(a):" in req["src"]
    assert req["args"] == [4]


def test_import_module_returns_proxy():
    s = FakeSession()
    _reply_to(s, {"__pyte_ref__": 3})
    obj = s.import_module("json")
    assert isinstance(obj, remote.RemoteObject)


def test_proxy_getattr_and_call_roundtrip():
    s = FakeSession()
    obj = remote.RemoteObject(s, 3)
    _reply_to(s, {"__pyte_ref__": 4})   # getattr -> bound method proxy
    _reply_to(s, "[1]")                 # callobj -> value
    assert obj.dumps([1]) == "[1]"
    assert s.sent[0] == {"id": 1, "op": "getattr", "obj": 3,
                         "name": "dumps"}
    assert s.sent[1]["op"] == "callobj" and s.sent[1]["obj"] == 4
    assert s.sent[1]["args"] == [[1]]


def test_proxy_encodes_as_ref_argument():
    s = FakeSession()
    obj = remote.RemoteObject(s, 7)
    _reply_to(s, None)
    s.call(outer, obj)
    assert s.sent[0]["args"] == [{"__pyte_ref__": 7}]


def test_foreign_session_proxy_rejected():
    s1, s2 = FakeSession(), FakeSession()
    obj = remote.RemoteObject(s2, 7)
    with pytest.raises(ValueError, match="session"):
        s1.call(outer, obj)


def test_unserializable_argument_rejected():
    s = FakeSession()
    with pytest.raises(TypeError):
        s.call(outer, object())


def test_closure_rejected():
    x = 10

    def closed(a):
        return a + x

    s = FakeSession()
    with pytest.raises(ValueError, match="closure"):
        s.call(closed, 1)


def test_lambda_rejected():
    s = FakeSession()
    with pytest.raises(ValueError, match="lambda"):
        s.call(lambda a: a, 1)


def test_remote_error_reraised():
    s = FakeSession()
    s.replies.append({"id": 1, "ok": False, "type": "KeyError",
                      "msg": "'k'", "traceback": "Trace...KeyError"})
    with pytest.raises(RemotePythonError, match="KeyError") as ei:
        s.call(outer, 1)
    assert "Trace" in ei.value.remote_traceback


def test_id_mismatch_is_protocol_error():
    s = FakeSession()
    s.replies.append({"id": 99, "ok": True, "value": 1})
    with pytest.raises(RemotePythonError, match="id"):
        s.call(outer, 1)


def test_underscore_attrs_not_proxied():
    s = FakeSession()
    obj = remote.RemoteObject(s, 3)
    with pytest.raises(AttributeError):
        obj._private
    assert s.sent == []


class BridgeSession(remote.RemotePython):
    """RemotePython wired to a real runner subprocess (no TE)."""

    def __init__(self):
        super().__init__(job=None, flt=None, timeout=10.0)
        self.proc = subprocess.Popen(
            [sys.executable, "-u", "-c", RUNNER.read_text()],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True)

    def _send(self, req):
        self.proc.stdin.write(json.dumps(req) + "\n")
        self.proc.stdin.flush()

    def _recv(self, timeout):
        line = self.proc.stdout.readline()
        if not line:
            raise RemotePythonError("runner died")
        return json.loads(line)


@pytest.fixture
def bridge():
    s = BridgeSession()
    yield s
    s.proc.kill()
    s.proc.wait()


def parse_csv_line(line):
    return [f.strip() for f in line.split(",")]


def boom():
    return 1 // 0


def test_bridge_end_to_end(bridge):
    assert bridge.call(parse_csv_line, "a, b ,c") == ["a", "b", "c"]
    sio_mod = bridge.import_module("io")
    buf = sio_mod.StringIO()
    buf.write("xyz")
    assert buf.getvalue() == "xyz"
    with pytest.raises(RemotePythonError, match="ZeroDivisionError"):
        bridge.call(boom)
    # The session survives a remote exception.
    assert bridge.call(parse_csv_line, "p,q") == ["p", "q"]
