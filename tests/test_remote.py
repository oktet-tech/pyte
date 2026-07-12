# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Engine-side pyte.remote tests: fake transport + real-runner bridge."""
import json
import pathlib
import subprocess
import sys
from types import SimpleNamespace

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
        {"id": session._last_id + len(session.replies) + 1,
         "ok": True, "value": value})


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
    _reply_to(s, {"__pyte_ref__": 4})   # getattr -> method ref
    _reply_to(s, "[1]")                 # callobj -> value
    assert obj.dumps([1]) == "[1]"
    assert s.sent[0] == {"id": 1, "op": "getattr", "obj": 3,
                         "name": "dumps"}
    assert s.sent[1]["id"] == 2
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


def test_value_attribute_roundtrips_immediately():
    s = FakeSession()
    obj = remote.RemoteObject(s, 3)
    _reply_to(s, 3.14159)
    assert obj.pi == 3.14159
    assert s.sent[0]["op"] == "getattr" and s.sent[0]["name"] == "pi"


def test_reserved_key_dict_rejected():
    s = FakeSession()
    with pytest.raises(ValueError, match="__pyte_ref__"):
        s.call(outer, {"__pyte_ref__": 1})


async def _async_fn():
    return 42


def test_async_function_rejected():
    s = FakeSession()
    with pytest.raises(ValueError, match="async"):
        s.call(_async_fn)


# ---------------------------------------------------------------------------
# _StubFilter: drive the REAL _recv without TE infrastructure
# ---------------------------------------------------------------------------

class _StubFilter:
    """Feeds scripted JobMessage-shaped chunks to the real _recv."""

    def __init__(self, chunks):
        self._chunks = list(chunks)

    def next(self, timeout):
        data = self._chunks.pop(0)
        if data is None:
            return SimpleNamespace(data="", eos=True, dropped=0,
                                   filter=self)
        return SimpleNamespace(data=data, eos=False, dropped=0,
                               filter=self)


def test_recv_reassembles_split_line():
    flt = _StubFilter(['{"id": 1, ', '"ok": true, "value": 7}\n'])
    s = remote.RemotePython(job=None, flt=flt, timeout=5.0)
    result = s._recv(5.0)
    assert result == {"id": 1, "ok": True, "value": 7}


def test_recv_two_lines_one_chunk():
    chunk = ('{"id": 1, "ok": true, "value": 1}\n'
             '{"id": 2, "ok": true, "value": 2}\n')
    flt = _StubFilter([chunk])
    s = remote.RemotePython(job=None, flt=flt, timeout=5.0)
    first = s._recv(5.0)
    assert first == {"id": 1, "ok": True, "value": 1}
    # Second _recv must NOT call the filter again (list is now empty —
    # popping would raise IndexError, proving the buffer was used).
    second = s._recv(5.0)
    assert second == {"id": 2, "ok": True, "value": 2}


def test_recv_eos_raises_runner_died():
    flt = _StubFilter([None])
    s = remote.RemotePython(job=None, flt=flt, timeout=5.0)
    with pytest.raises(RemotePythonError, match="died"):
        s._recv(5.0)


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


# ---------------------------------------------------------------------------
# P0.18: proxy assignment, deadline enforcement, desync flag, handle release
# ---------------------------------------------------------------------------

def test_proxy_setattr_raises():
    """Assignment is not proxied; silently setting a local attribute
    (which later reads would return!) must be refused instead."""
    s = FakeSession()
    obj = remote.RemoteObject(s, 3)
    with pytest.raises(AttributeError, match="assignment"):
        obj.isolation_level = None
    assert s.sent == []
    # reads still see the remote object, not a stale local shadow
    _reply_to(s, 42)
    assert obj.isolation_level == 42


class _FirehoseFilter:
    """Always has data, never a newline: a subprocess spawned by shipped
    code that inherits fd 1 produces exactly this."""

    def __init__(self, limit=1000):
        self.calls = 0
        self.limit = limit

    def next(self, timeout):
        self.calls += 1
        assert self.calls <= self.limit, \
            "_recv looped past its deadline without raising"
        return SimpleNamespace(data="no newline here ", eos=False,
                               dropped=0, filter=self)


def test_recv_enforces_deadline_when_data_flows():
    """Chunks arriving without newlines must not keep _recv alive past
    its deadline (the old max(remaining, 1ms) clamp looped forever)."""
    flt = _FirehoseFilter()
    s = remote.RemotePython(job=None, flt=flt, timeout=5.0)
    with pytest.raises(RemotePythonError, match="deadline|timed out"):
        s._recv(0.0)


class _NeverFilter:
    def next(self, timeout):
        raise TimeoutError("no data")


class _SendOnlySession(remote.RemotePython):
    def _send(self, req):
        pass


def test_timeout_marks_session_broken():
    """After a per-call timeout the late reply is still in flight; the
    session must refuse reuse instead of reading the stale reply and
    failing with a confusing protocol-error later."""
    s = _SendOnlySession(job=None, flt=_NeverFilter(), timeout=0.01)
    with pytest.raises(TimeoutError):
        s.call(outer, 1)
    with pytest.raises(RemotePythonError, match="unusable|desync"):
        s.call(outer, 2)


def test_eos_marks_session_broken():
    flt = _StubFilter([None])
    s = _SendOnlySession(job=None, flt=flt, timeout=5.0)
    s._job_status = lambda: None
    with pytest.raises(RemotePythonError, match="died"):
        s.call(outer, 1)
    # second use: refused up front, filter not touched (chunks empty)
    with pytest.raises(RemotePythonError, match="unusable|died"):
        s.call(outer, 2)


def test_dropped_proxy_frees_handle_on_next_request():
    """A garbage-collected proxy queues its handle; the next request
    piggybacks it as \"free\" so the runner can drop the object."""
    import gc

    s = FakeSession()
    obj = remote.RemoteObject(s, 7)
    del obj
    gc.collect()
    _reply_to(s, None)
    s.call(outer, 1)
    assert s.sent[0].get("free") == [7]


def test_bridge_dropped_proxy_releases_remote_object(bridge):
    """End-to-end: after the proxy dies, the remote handle is gone."""
    import gc

    sio_mod = bridge.import_module("io")
    buf = sio_mod.StringIO()
    handle = buf._handle
    del buf
    gc.collect()
    # any next request carries the free list and drops the handle
    assert bridge.call(parse_csv_line, "a,b") == ["a", "b"]
    stale = remote.RemoteObject(bridge, handle)
    with pytest.raises(RemotePythonError, match="KeyError"):
        stale.getvalue()
