# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Tests for pyte.tools.http (HTTP client session)."""
from pyte.errors import HttpError, TeError, ToolError


def test_httperror_is_toolerror_with_response():
    e = HttpError("GET /x -> 404 Not Found: nope", response="resp")
    assert isinstance(e, ToolError) and isinstance(e, TeError)
    assert e.rc == 0
    assert e.response == "resp"
    assert HttpError("plain").response is None


# ---- facade tests -------------------------------------------------------
from contextlib import contextmanager  # noqa: E402

import pytest  # noqa: E402

from pyte import log  # noqa: E402
from pyte.errors import RemotePythonError  # noqa: E402
from pyte.tools import http  # noqa: E402


class _FakeRem:
    """Fake pyte.remote session: records (op_name, args, kwargs)."""

    def __init__(self, canned):
        self.canned = canned
        self.calls = []

    def call(self, fn, *args, **kwargs):
        self.calls.append((fn.__name__, args, kwargs))
        val = self.canned.get(fn.__name__)
        if isinstance(val, BaseException):
            raise val
        return val() if callable(val) else val


def _resp(status=200, reason="OK", body='{"a": 1}', headers=None,
          url="http://d/x"):
    return {"status": status, "reason": reason,
            "headers": headers or {"content-type": "application/json"},
            "body": body, "url": url, "json": None, "elapsed": 0.012}


CLIENT = object()


def _sess(canned=None, **kw):
    rem = _FakeRem({"request": _resp()} if canned is None else canned)
    opts = dict(timeout=30.0, log_body=http.DEFAULT_LOG_BODY,
                redact=frozenset())
    opts.update(kw)
    return http.Session(rem, CLIENT, **opts), rem


@pytest.fixture
def logs(monkeypatch):
    out = {"push": [], "pop": [], "ring": [], "verb": []}
    monkeypatch.setattr(log, "step_push", lambda t: out["push"].append(t))
    monkeypatch.setattr(log, "step_pop",
                        lambda t="": out["pop"].append(t))
    monkeypatch.setattr(log, "ring",
                        lambda t, user="Self": out["ring"].append(t))
    monkeypatch.setattr(log, "verb",
                        lambda t, user="Self": out["verb"].append(t))
    return out


def test_get_ships_request_op_with_agent_and_transport_timeouts(logs):
    s, rem = _sess({"request": _resp(headers={"content-type": "x/y"})})
    r = s.get("/x", params={"q": "1"})
    op, args, kwargs = rem.calls[-1]
    assert op == "request"
    assert args[:3] == (CLIENT, "GET", "/x")
    assert args[3]["timeout"] == 30.0
    assert args[3]["params"] == {"q": "1"}
    assert kwargs == {"timeout": 60.0}
    assert isinstance(r, http.Response)
    assert r.status == 200 and r.ok
    assert r.headers == {"content-type": "x/y"}
    assert r.json() == {"a": 1}


def test_per_request_timeout_overrides_both(logs):
    s, rem = _sess()
    s.get("/x", timeout=5)
    _, args, kwargs = rem.calls[-1]
    assert args[3]["timeout"] == 5.0
    assert kwargs == {"timeout": 35.0}


def test_body_kinds_exclusive_engine_side(logs):
    s, rem = _sess()
    with pytest.raises(ValueError):
        s.post("/x", json={}, form={"a": "b"})
    with pytest.raises(ValueError):
        s.post("/x", data="raw")
    assert rem.calls == []


def test_content_type_passes_through_with_json(logs):
    s, rem = _sess()
    s.post("/x", json={"a": 1}, content_type="application/vnd.x+json")
    assert rem.calls[-1][1][3]["content_type"] == "application/vnd.x+json"


def test_get_and_delete_accept_no_body(logs):
    s, _ = _sess()
    with pytest.raises(TypeError):
        s.get("/x", json={})
    with pytest.raises(TypeError):
        s.delete("/x", form={})


def test_non_2xx_raises_with_response_and_excerpt(logs):
    body = "no\nsuch\n" + "z" * 300
    s, _ = _sess({"request": _resp(404, "Not Found", body)})
    with pytest.raises(HttpError) as ei:
        s.get("/x")
    e = ei.value
    assert e.response.status == 404
    prefix = "GET /x -> 404 Not Found: "
    assert str(e).startswith(prefix + "no such ")
    assert len(str(e)) - len(prefix) <= 200


def test_ok_false_returns_response(logs):
    s, _ = _sess({"request": _resp(401, "Unauthorized", "")})
    r = s.get("/x", ok=False)
    assert r.status == 401 and not r.ok


def test_remote_error_wrapped(logs):
    err = RemotePythonError("boom")
    s, _ = _sess({"request": err})
    with pytest.raises(HttpError) as ei:
        s.get("/x")
    assert str(ei.value) == f"GET /x: {err}"
    assert ei.value.__cause__ is err


def test_json_parse_failure_is_httperror(logs):
    s, _ = _sess({"request": _resp(body="<html>")})
    r = s.get("/x")
    with pytest.raises(HttpError, match="body is not JSON: <html>"):
        r.json()


def test_step_bracket_and_body_logging(logs):
    s, _ = _sess()
    s.get("/x")
    assert logs["push"] == ["GET /x"]
    assert len(logs["pop"]) == 1 and logs["pop"][0].startswith("200 OK")
    assert any('{"a": 1}' in t for t in logs["ring"])


def test_body_truncation_and_marker(logs):
    s, _ = _sess({"request": _resp(body="a" * 5000)})
    s.get("/x")
    texts = [t for t in logs["ring"] if "a" * 100 in t]
    assert len(texts) == 1
    assert texts[0].endswith("a" * 4096 + "... (5000 chars)")


def test_log_body_zero_silences_bodies(logs):
    s, _ = _sess(log_body=0)
    s.get("/x")
    assert not any('{"a": 1}' in t for t in logs["ring"])
    s2, _ = _sess()
    s2.get("/x", log_body=0)
    assert not any('{"a": 1}' in t for t in logs["ring"])


def test_headers_redacted_in_verb(logs):
    s, _ = _sess(redact=frozenset({"x-token"}))
    s.get("/x", headers={"Authorization": "Bearer sekret",
                         "X-Token": "t0k", "X-Other": "visible"})
    text = "\n".join(logs["verb"])
    assert "sekret" not in text and "t0k" not in text
    assert text.count(http.REDACTED) >= 2
    assert "visible" in text
    assert "http op: request GET /x" in text


def test_set_header_and_cookies_ship_ops(logs):
    s, rem = _sess({"cookies": {"sid": "1"}})
    s.set_header("X-A", "b")
    assert rem.calls[-1][0] == "set_header"
    assert rem.calls[-1][1] == (CLIENT, "X-A", "b")
    assert s.cookies() == {"sid": "1"}
    assert rem.calls[-1][0] == "cookies"


def test_call_inserts_client_first(logs):
    s, rem = _sess({"custom": 7})

    def custom(client, a, b=0):
        pass

    assert s.call(custom, 1, b=2, timeout=10) == 7
    assert rem.calls[-1] == ("custom", (CLIENT, 1), {"b": 2,
                                                      "timeout": 40.0})
    assert s.remote is rem


def test_session_bootstraps_with_defaults(monkeypatch, logs):
    rem = _FakeRem({"bootstrap": CLIENT})
    seen = {}

    @contextmanager
    def fake_python(pco, timeout=None):
        seen["timeout"] = timeout
        yield rem

    monkeypatch.setattr(http.remote, "python", fake_python)
    with http.session(object(), "https://d", verify=False) as s:
        assert isinstance(s, http.Session)
    assert rem.calls[0] == ("bootstrap",
                            ("https://d", False, {}, http.MAX_BODY), {})
    assert "TLS verification disabled for https://d" in logs["ring"]
    assert seen["timeout"] == 60.0
