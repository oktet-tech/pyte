# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Run the agent-side HTTP ops in-process against a local server."""
import inspect
import json
import re
import ssl
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import pytest

from pyte.tools import _http_ops
from pyte.tools._http_ops import bootstrap, request, set_header


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, code, body, ctype="application/json", extra=()):
        if not isinstance(body, bytes):
            body = json.dumps(body).encode()
        try:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            for k, v in extra:
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _read(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n)

    def do_POST(self):
        path = urlsplit(self.path).path
        body = self._read()
        if path == "/login":
            self._send(200, {"ok": True},
                       extra=[("Set-Cookie", "sid=abc123; Path=/")])
        elif path == "/login-redirect":
            self._send(302, b"", extra=[("Location", "/data"),
                                        ("Set-Cookie", "sid=abc123; Path=/")])
        elif path == "/echo":
            self._send(200, {"ct": self.headers.get("Content-Type"),
                             "body": body.decode()})
        else:
            self._send(404, {})

    def do_GET(self):
        u = urlsplit(self.path)
        q = parse_qs(u.query)
        if u.path == "/data":
            ct = "text/html" if q.get("ct") == ["html"] else "application/json"
            if "sid=abc123" in (self.headers.get("Cookie") or ""):
                self._send(200, {"items": [1, 2, 3]}, ct)
            else:
                self._send(401, {"error": "unauthenticated"}, ct)
        elif u.path == "/echo":
            self._send(200, {"query": q, "headers": {
                k.lower(): v for k, v in self.headers.items()}})
        elif u.path == "/latin":
            self._send(200, b"caf\xe9", "text/plain; charset=latin-1")
        elif u.path == "/big":
            self._send(200, b"x" * 1000, "text/plain")
        elif u.path == "/slow":
            time.sleep(2)
            self._send(200, {})
        else:
            self._send(404, {})


@pytest.fixture
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    srv.daemon_threads = True
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield "http://127.0.0.1:%d" % srv.server_address[1]
    srv.shutdown()
    srv.server_close()
    t.join()


def test_login_cookie_replayed(server):
    c = bootstrap(server, True, {}, 8 << 20, None)
    r = c.request("POST", "/login", json={"user": "a", "pass": "b"})
    assert r["status"] == 200 and r["json"] == {"ok": True}
    assert c.cookies() == {"sid": "abc123"}
    assert c.request("GET", "/data")["json"] == {"items": [1, 2, 3]}


def test_unauthenticated_status_is_a_result_not_an_exception(server):
    r = bootstrap(server, True, {}, 8 << 20, None).request("GET", "/data")
    assert r["status"] == 401 and r["reason"] == "Unauthorized"
    assert r["json"] == {"error": "unauthenticated"}


def test_cookie_set_on_redirect_hop_is_kept(server):
    c = bootstrap(server, True, {}, 8 << 20, None)
    r = c.request("POST", "/login-redirect", json={})
    assert r["status"] == 200 and r["url"].endswith("/data")
    assert c.cookies() == {"sid": "abc123"}


def test_json_parsed_regardless_of_content_type(server):
    c = bootstrap(server, True, {}, 8 << 20, None)
    c.request("POST", "/login", json={})
    r = c.request("GET", "/data", params={"ct": "html"})
    assert r["headers"]["content-type"].startswith("text/html")
    assert r["json"] == {"items": [1, 2, 3]}


def test_params_and_default_and_per_request_headers(server):
    c = bootstrap(server, True, {"X-Default": "d", "X-Over": "a"},
                  8 << 20, None)
    r = c.request("GET", "/echo", params={"q": "1", "z": "two"},
                  headers={"X-Over": "b"})
    assert r["json"]["query"] == {"q": ["1"], "z": ["two"]}
    assert r["json"]["headers"]["x-default"] == "d"
    assert r["json"]["headers"]["x-over"] == "b"


def test_set_header_add_and_remove(server):
    c = bootstrap(server, True, {}, 8 << 20, None)
    set_header(c, "Authorization", "Bearer t")
    got = json.loads(request(c, "GET", "/echo", {})["body"])["headers"]
    assert got["authorization"] == "Bearer t"
    set_header(c, "Authorization", None)
    got = json.loads(request(c, "GET", "/echo", {})["body"])["headers"]
    assert "authorization" not in got


def test_body_kinds(server):
    c = bootstrap(server, True, {}, 8 << 20, None)
    r = c.request("POST", "/echo", json={"a": 1})
    assert json.loads(r["body"]) == {"ct": "application/json", "body": '{"a": 1}'}
    r = c.request("POST", "/echo", form={"a": "1", "b": "x y"})
    assert json.loads(r["body"]) == {"ct": "application/x-www-form-urlencoded",
                         "body": "a=1&b=x+y"}
    r = c.request("POST", "/echo", data=b"<x/>", content_type="text/xml")
    assert json.loads(r["body"]) == {"ct": "text/xml", "body": "<x/>"}


def test_explicit_content_type_overrides_kind_default(server):
    c = bootstrap(server, True, {}, 8 << 20, None)
    r = c.request("POST", "/echo", json={"a": 1},
                  content_type="application/merge-patch+json")
    assert r["json"]["ct"] == "application/merge-patch+json"


def test_request_op_decodes_data_b64(server):
    c = bootstrap(server, True, {}, 8 << 20, None)
    r = request(c, "POST", "/echo",
                {"data_b64": "PHgvPg==", "content_type": "text/xml"})
    assert json.loads(r["body"]) == {"ct": "text/xml", "body": "<x/>"}


def test_body_kinds_are_exclusive_and_data_needs_content_type(server):
    c = bootstrap(server, True, {}, 8 << 20, None)
    with pytest.raises(RuntimeError, match="mutually exclusive"):
        c.request("POST", "/echo", json={}, form={})
    with pytest.raises(RuntimeError, match="content_type"):
        c.request("POST", "/echo", data=b"x")


def test_charset_decoding(server):
    r = bootstrap(server, True, {}, 8 << 20, None).request("GET", "/latin")
    assert r["body"] == "café"


def test_body_cap(server):
    with pytest.raises(RuntimeError,
                       match="1000 bytes exceeds the 512 byte cap"):
        bootstrap(server, True, {}, 512, None).request("GET", "/big")


def test_request_op_reply_has_no_json_key(server):
    c = bootstrap(server, True, {}, 8 << 20, None)
    r = request(c, "GET", "/echo", {})
    assert "json" not in r and r["status"] == 200


def test_request_op_caps_the_encoded_reply(server):
    class Cjk(Handler):
        def do_GET(self):
            self._send(200, ("\u4e2d" * 100).encode(),
                       "text/plain; charset=utf-8")

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Cjk)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        c = bootstrap("http://127.0.0.1:%d" % srv.server_address[1],
                      True, {}, 512, None)
        # 300 raw bytes fit the cap, but json.dumps gives 602 chars (quotes)
        with pytest.raises(RuntimeError,
                           match="response body 602 bytes exceeds the 512"):
            request(c, "GET", "/", {})
    finally:
        srv.shutdown()
        srv.server_close()


def test_request_prints_one_log_line(server, capsys):
    bootstrap(server, True, {}, 8 << 20, None).request("GET", "/data")
    out = capsys.readouterr().out.splitlines()
    assert len(out) == 1
    assert re.fullmatch(
        re.escape("http: GET %s/data -> 401 Unauthorized (" % server)
        + r"\d+\.\d{3}s\)", out[0])


def test_bootstrap_timeout_is_the_request_default(server):
    c = bootstrap(server, True, {}, 8 << 20, 0.5)
    with pytest.raises(Exception):          # socket.timeout / URLError
        c.request("GET", "/slow")


def test_timeout_then_next_request_works(server):
    c = bootstrap(server, True, {}, 8 << 20, None)
    with pytest.raises(Exception):          # socket.timeout / URLError
        c.request("GET", "/slow", timeout=0.5)
    assert c.request("GET", "/echo")["status"] == 200


def test_proxy_env_ignored(server, monkeypatch):
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:9")
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    assert bootstrap(server, True, {}, 8 << 20, None).request(
        "GET", "/echo")["status"] == 200


def test_absolute_url_path_and_elapsed(server):
    r = bootstrap("http://invalid.example/", True, {}, 8 << 20, None).request(
        "GET", server + "/echo")
    assert r["status"] == 200 and r["elapsed"] >= 0.0


def test_verify_false_disables_hostname_and_cert_checks():
    c = bootstrap("https://127.0.0.1:1", False, {}, 8 << 20, None)
    assert c.ssl_context.check_hostname is False
    assert c.ssl_context.verify_mode == ssl.CERT_NONE
    assert bootstrap("https://127.0.0.1:1", True, {},
                     8 << 20, None).ssl_context.check_hostname is True


def test_ops_are_self_contained():
    # The engine ships source text: no module-level imports may be needed.
    src = inspect.getsource(_http_ops)
    assert not re.search(r"^(import|from) ", src, re.M)
