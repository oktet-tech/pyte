# pyte.tools.http Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An HTTP client session that lives on a test agent and is
driven from a Python test, keeping cookies on the agent and returning
parsed JSON to the test, with no per-device code in pyte.

**Architecture:** Engine-side facade `pyte.tools.http` (Session,
Response, session()) over one `pyte.remote.python()` interpreter per
session. Agent-side `pyte.tools._http_ops` is shipped by source and
builds a stdlib-only urllib client with a cookie jar; the live client
crosses back as a RemoteObject handle and is passed into every shipped
op. Same shape as `pyte.tools.trex.stl` over `pyte.tools.trex._ops`.

**Tech Stack:** Python 3.10+ on the engine, Python 3.10+ stdlib only
on the agent (urllib.request, http.cookiejar, ssl, json). pytest for
unit tests, `http.server` on loopback for agent-side tests. Sphinx
with -W for docs.

**Spec:** `docs/superpowers/specs/2026-11-09-http-session-design.md`

**Repos and branch:** pyte work goes on a new branch `http` created
from the current `stress2` HEAD (where the spec is committed). The
showcase test goes in the sibling `../python-ts` repo on a branch of
the same name. Commits follow `component: lowercase imperative`,
signed off (`git commit -s`), no AI trailers.

## Global Constraints

- Agent side (`_http_ops.py`) imports only the stdlib, inside function
  bodies; no module globals, no closures, no references to siblings.
  Every op-function is self-contained and JSON-able in and out.
- Agent side must run on Python 3.10 (no 3.11+ syntax or stdlib).
- Defaults: `timeout=30.0`, `verify=True`, `log_body=4096`, body cap
  on the agent 8 MiB (8 * 1024 * 1024 bytes), transport margin 30.0 s
  added to the agent timeout.
- Redacted header names (case-insensitive): `authorization`, `cookie`,
  `set-cookie`, plus any in the session's `redact=`; redacted value in
  the log is the literal `<redacted>`.
- Error messages are one line; the body excerpt in an HttpError is at
  most 200 characters with newlines collapsed to spaces.
- Proxy environment on the agent is ignored (`ProxyHandler({})`).
- New files start with `# SPDX-License-Identifier: Apache-2.0` and
  `# Copyright (C) 2026 Konstantin Ushakov`. Plain ASCII in docs and
  docstrings.
- Unit tests must pass with the TE-free command from README.md (no
  shim): `PYTHONPATH=src uv run --no-project --with pytest --with
  scapy --with pyyaml pytest tests/test_http.py tests/test_http_ops.py`.

## Review Focus

- A device that answers a login with 302 and Set-Cookie on the
  redirect: the cookie must be in `cookies()` and replayed, even though
  `Response.headers` shows only the final hop. Test in Task 2.
- A JSON body labelled `text/html`: the agent-side `json` key must be
  filled and `Response.json()` must parse. Test in Task 2.
- A non-UTF-8 body with a charset in Content-Type (e.g. latin-1): the
  text must decode by that charset, and an undeclared byte sequence
  must not raise (errors replaced). Test in Task 2.
- A request made after an agent-side socket timeout: the session must
  still work for the next request. Test in Task 2 (ops) and Task 3
  (facade does not mark anything broken).
- A reply larger than the cap: a clean HttpError naming the length, not
  a broken session. Test in Task 2.

---

### Task 1: HttpError

**Files:**
- Modify: `src/pyte/errors.py` (after `SshError`, before `RcfError`)
- Test: `tests/test_http.py` (new)

**Interfaces:**
- Produces: `class HttpError(ToolError)` with an optional `response`
  attribute (a `pyte.tools.http.Response` or None). Constructor:
  `HttpError(msg: str, response=None)`; the base `_RcOrMsg` string path
  is kept, so `HttpError("x").rc == 0`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_http.py
from pyte.errors import HttpError, TeError, ToolError

def test_httperror_is_toolerror_with_response():
    e = HttpError("GET /x -> 404 Not Found: nope", response="resp")
    assert isinstance(e, ToolError) and isinstance(e, TeError)
    assert e.rc == 0
    assert e.response == "resp"
    assert HttpError("plain").response is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src uv run --no-project --with pytest --with scapy --with pyyaml pytest tests/test_http.py -v`
Expected: FAIL with ImportError on `HttpError`.

- [ ] **Step 3: Implement `HttpError` in `src/pyte/errors.py`**

Docstring: "pyte.tools.http: transport failure, unexpected status, or
unparseable JSON. ``response`` carries the Response for a status
failure." Override `__init__` to accept `response=None`, store it, and
call the base constructor with the message.

- [ ] **Step 4: Run test to verify it passes**

Same command. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/pyte/errors.py tests/test_http.py
git commit -s -m "errors: add HttpError for pyte.tools.http"
```

---

### Task 2: Agent-side ops (`_http_ops.py`)

**Files:**
- Create: `src/pyte/tools/_http_ops.py`
- Test: `tests/test_http_ops.py` (new; runs the ops in-process against
  a `http.server.ThreadingHTTPServer` on 127.0.0.1, port 0)

**Interfaces:**
- Produces, all module-level functions in `_http_ops.py`:
  - `bootstrap(base_url: str, verify: bool, headers: dict, max_body: int) -> Client`
    builds and returns the live client (crosses as a RemoteObject).
  - `request(client, method: str, path: str, kw: dict) -> dict` calls
    `client.request(method, path, **kw)`.
  - `set_header(client, name: str, value) -> None`; None removes.
  - `cookies(client) -> dict[str, str]`.
- `Client` is a class defined inside `bootstrap` (so the op stays
  self-contained). Its public methods are the stable contract:
  - `request(method, path, params=None, json=None, form=None, data=None,
    content_type=None, headers=None, timeout=None) -> dict` with keys
    `status: int`, `reason: str`, `headers: dict[str,str]` (lower-case
    keys, last value wins), `body: str`, `url: str`, `json` (parsed
    body or None), `elapsed: float` seconds.
  - `cookies() -> dict[str, str]`
  - `set_header(name, value) -> None`
  - attribute `headers: dict` (session defaults).
- `request` never raises for an HTTP status: `urllib.error.HTTPError`
  is caught and turned into the same dict. It raises `RuntimeError`
  with a one-line message for: a body longer than `max_body` ("response
  body N bytes exceeds the M byte cap"), and two body kinds given at
  once ("json, form and data are mutually exclusive"). Transport errors
  (`URLError`, `socket.timeout`, `ssl.SSLError`) propagate as they are;
  the engine wraps them.
- `data=` must be `bytes` or `str` (str encoded UTF-8); `content_type`
  is required with `data` (RuntimeError otherwise).
- `path` starting with `http://` or `https://` is used as is; otherwise
  joined to `base_url` with `urllib.parse.urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))`.
- Socket timeout: `timeout` argument if given else the client's default
  (bootstrap stores `None`; the engine always passes an explicit value).
  Store the default as `client.timeout` so shipped functions get one.

- [ ] **Step 1: Write the failing tests**

A pytest fixture `server` starts `ThreadingHTTPServer(("127.0.0.1", 0), Handler)`
in a thread and yields its base URL. `Handler` implements:
- `POST /login`: body `{"user":..., "pass":...}` -> 200, header
  `Set-Cookie: sid=abc123; Path=/`, body `{"ok": true}`.
- `POST /login-redirect`: 302 to `/data` with `Set-Cookie: sid=abc123; Path=/`
  on the 302.
- `GET /data`: 200 `{"items": [1, 2, 3]}` if cookie `sid=abc123`, else
  401 `{"error": "unauthenticated"}`. Content-Type
  `application/json` unless query `ct=html`, then `text/html`.
- `GET /echo`: 200 JSON `{"query": <parsed query dict>, "headers": {<request headers, lower-case>}}`.
- `POST /echo`: 200 JSON `{"ct": <request Content-Type>, "body": <body as text>}`.
- `GET /latin`: 200, `Content-Type: text/plain; charset=latin-1`, body
  `b"caf\xe9"`.
- `GET /big`: 200, a body of 1000 bytes of "x".
- `GET /slow`: sleeps 2 seconds, then 200.

Tests (names and assertions):

```python
def test_login_cookie_replayed(server):
    c = bootstrap(server, True, {}, 8 << 20)
    r = c.request("POST", "/login", json={"user": "a", "pass": "b"})
    assert r["status"] == 200 and r["json"] == {"ok": True}
    assert c.cookies() == {"sid": "abc123"}
    assert c.request("GET", "/data")["json"] == {"items": [1, 2, 3]}

def test_unauthenticated_status_is_a_result_not_an_exception(server):
    r = bootstrap(server, True, {}, 8 << 20).request("GET", "/data")
    assert r["status"] == 401 and r["reason"] == "Unauthorized"
    assert r["json"] == {"error": "unauthenticated"}

def test_cookie_set_on_redirect_hop_is_kept(server):
    c = bootstrap(server, True, {}, 8 << 20)
    r = c.request("POST", "/login-redirect", json={})
    assert r["status"] == 200 and r["url"].endswith("/data")
    assert c.cookies() == {"sid": "abc123"}

def test_json_parsed_regardless_of_content_type(server):
    c = bootstrap(server, True, {}, 8 << 20)
    c.request("POST", "/login", json={})
    r = c.request("GET", "/data", params={"ct": "html"})
    assert r["headers"]["content-type"].startswith("text/html")
    assert r["json"] == {"items": [1, 2, 3]}

def test_params_and_default_and_per_request_headers(server):
    c = bootstrap(server, True, {"X-Default": "d", "X-Over": "a"}, 8 << 20)
    r = c.request("GET", "/echo", params={"q": "1", "z": "two"},
                  headers={"X-Over": "b"})
    assert r["json"]["query"] == {"q": ["1"], "z": ["two"]}
    assert r["json"]["headers"]["x-default"] == "d"
    assert r["json"]["headers"]["x-over"] == "b"

def test_set_header_add_and_remove(server):
    c = bootstrap(server, True, {}, 8 << 20)
    set_header(c, "Authorization", "Bearer t")
    assert request(c, "GET", "/echo", {})["json"]["headers"]["authorization"] == "Bearer t"
    set_header(c, "Authorization", None)
    assert "authorization" not in request(c, "GET", "/echo", {})["json"]["headers"]

def test_body_kinds(server):
    c = bootstrap(server, True, {}, 8 << 20)
    r = c.request("POST", "/echo", json={"a": 1})
    assert r["json"] == {"ct": "application/json", "body": '{"a": 1}'}
    r = c.request("POST", "/echo", form={"a": "1", "b": "x y"})
    assert r["json"] == {"ct": "application/x-www-form-urlencoded", "body": "a=1&b=x+y"}
    r = c.request("POST", "/echo", data=b"<x/>", content_type="text/xml")
    assert r["json"] == {"ct": "text/xml", "body": "<x/>"}

def test_body_kinds_are_exclusive_and_data_needs_content_type(server):
    c = bootstrap(server, True, {}, 8 << 20)
    with pytest.raises(RuntimeError, match="mutually exclusive"):
        c.request("POST", "/echo", json={}, form={})
    with pytest.raises(RuntimeError, match="content_type"):
        c.request("POST", "/echo", data=b"x")

def test_charset_decoding(server):
    r = bootstrap(server, True, {}, 8 << 20).request("GET", "/latin")
    assert r["body"] == "café"

def test_body_cap(server):
    with pytest.raises(RuntimeError, match="1000 bytes exceeds the 512 byte cap"):
        bootstrap(server, True, {}, 512).request("GET", "/big")

def test_timeout_then_next_request_works(server):
    c = bootstrap(server, True, {}, 8 << 20)
    with pytest.raises(Exception):          # socket.timeout / URLError
        c.request("GET", "/slow", timeout=0.5)
    assert c.request("GET", "/echo")["status"] == 200

def test_proxy_env_ignored(server, monkeypatch):
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:9")
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    assert bootstrap(server, True, {}, 8 << 20).request("GET", "/echo")["status"] == 200

def test_absolute_url_path_and_elapsed(server):
    r = bootstrap("http://invalid.example/", True, {}, 8 << 20).request(
        "GET", server + "/echo")
    assert r["status"] == 200 and r["elapsed"] >= 0.0

def test_verify_false_disables_hostname_and_cert_checks():
    c = bootstrap("https://127.0.0.1:1", False, {}, 8 << 20)
    assert c.ssl_context.check_hostname is False
    assert c.ssl_context.verify_mode == ssl.CERT_NONE
    assert bootstrap("https://127.0.0.1:1", True, {}, 8 << 20).ssl_context.check_hostname is True

def test_ops_are_self_contained():
    # The engine ships source text: no module-level imports may be needed.
    src = inspect.getsource(_http_ops)
    assert not re.search(r"^(import|from) ", src, re.M)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src uv run --no-project --with pytest --with scapy --with pyyaml pytest tests/test_http_ops.py -v`
Expected: FAIL with ModuleNotFoundError for `pyte.tools._http_ops`.

- [ ] **Step 3: Implement `src/pyte/tools/_http_ops.py`**

Module docstring mirrors `trex/_ops.py` (self-containment rules). In
`bootstrap`: build `ssl.create_default_context()`, apply the verify
flag, keep it as `client.ssl_context`; opener from
`build_opener(ProxyHandler({}), HTTPCookieProcessor(jar), HTTPSHandler(context=ctx))`.
In `Client.request`: build the URL, encode the body per kind, merge
headers (defaults then per-request), `opener.open(Request(...), timeout=...)`,
catch `urllib.error.HTTPError` as the response object, read at most
`max_body + 1` bytes and raise on overflow, decode by
`resp.headers.get_content_charset() or "utf-8"` with `errors="replace"`,
try `json.loads` for the `json` key, fold headers lower-case. Query
encoding with `urllib.parse.urlencode(params, doseq=True)`.

- [ ] **Step 4: Run tests to verify they pass**

Same command. Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/pyte/tools/_http_ops.py tests/test_http_ops.py
git commit -s -m "tools/http: add the agent-side stdlib HTTP client ops"
```

---

### Task 3: Engine-side facade (`http.py`)

**Files:**
- Create: `src/pyte/tools/http.py`
- Modify: `src/pyte/tools/__init__.py` (one line in the module
  docstring listing `http` among the wrappers; no imports)
- Test: `tests/test_http.py` (extend)

**Interfaces:**
- Consumes: Task 2's op-functions and the `Client.request` result dict;
  `pyte.remote.python(pco, timeout=...)`, `RemotePython.call(fn, *args, timeout=, **kwargs)`,
  `pyte.errors.RemotePythonError`, `HttpError` from Task 1,
  `pyte.log.step_push/step_pop/ring/verb`.
- Produces, in `pyte.tools.http`:
  - `TRANSPORT_MARGIN = 30.0`, `DEFAULT_LOG_BODY = 4096`, `MAX_BODY = 8 * 1024 * 1024`,
    `REDACTED = "<redacted>"`, `_ALWAYS_REDACT = frozenset({"authorization", "cookie", "set-cookie"})`.
  - `@dataclass(frozen=True) class Response: status: int; reason: str; headers: dict[str, str]; body: str; url: str; elapsed: float` with
    `def json(self)` (raises `HttpError("<url>: body is not JSON: <200-char excerpt>")`)
    and `@property def ok(self) -> bool` (200 <= status < 300).
  - `class Session` constructed as `Session(rem, client, *, timeout: float, log_body: int, redact: frozenset[str])`
    with methods:
    `request(method, path, *, params=None, json=None, form=None, data=None, content_type=None, headers=None, ok=True, timeout=None, log_body=None) -> Response`;
    `get(path, *, params=None, headers=None, ok=True, timeout=None, log_body=None)`;
    `delete(...)` same as get;
    `post(path, *, params=None, json=None, form=None, data=None, content_type=None, headers=None, ok=True, timeout=None, log_body=None)`;
    `put(...)` same as post;
    `set_header(name: str, value: str | None) -> None`;
    `cookies() -> dict[str, str]`;
    `call(fn, *args, timeout=None, **kwargs)`;
    property `remote` returning the RemotePython session.
  - `@contextmanager def session(pco, base_url: str, *, timeout: float = 30.0, verify: bool = True, headers: dict[str, str] | None = None, log_body: int = DEFAULT_LOG_BODY, redact: Iterable[str] = ()) -> Iterator[Session]`.
- Behaviour pinned by the tests below: `Session.request` validates body
  exclusivity engine-side (ValueError, before any shipping); wraps
  RemotePythonError into HttpError (`f"{method} {path}: {exc}"`, cause
  kept); raises `HttpError(f"{method} {path} -> {status} {reason}: {excerpt}", response=resp)`
  when `ok` and not `resp.ok`; the transport timeout passed to
  `rem.call` is `(timeout or self._timeout) + TRANSPORT_MARGIN` and the
  agent timeout in `kw` is `timeout or self._timeout`; `call` passes
  `self._client` as the first positional argument and the same margin
  rule.

- [ ] **Step 1: Write the failing tests**

Use a `_FakeRem` like `tests/test_trex_stl.py` (records
`(fn.__name__, args, kwargs)`, returns canned values by op name; canned
may be a callable or an exception instance to raise). A helper
`_resp(status=200, reason="OK", body='{"a": 1}', headers=None, url="http://d/x")`
builds the dict Task 2 returns. Capture log output by monkeypatching
`pyte.log.step_push`, `step_pop`, `ring`, `verb` into lists.

```python
def test_get_ships_request_op_with_agent_and_transport_timeouts(): ...
    # rem.calls[-1] == ("request", (client, "GET", "/x", {...kw...}), {"timeout": 60.0})
    # kw["timeout"] == 30.0, kw["params"] == {"q": "1"}; result is a Response
    # with status 200, headers lower-cased, .json() == {"a": 1}
def test_per_request_timeout_overrides_both(): ...     # timeout=5 -> kw 5.0, transport 35.0
def test_body_kinds_exclusive_engine_side(): ...        # ValueError, rem.calls == []
def test_get_and_delete_accept_no_body(): ...           # TypeError on get(json=...)
def test_non_2xx_raises_with_response_and_excerpt(): ...
    # 404 body "no\nsuch\n" + 300 chars -> HttpError, .response.status == 404,
    # message "GET /x -> 404 Not Found: no such ..." and len(excerpt) <= 200
def test_ok_false_returns_response(): ...               # 401 -> Response, no raise
def test_remote_error_wrapped(): ...                    # canned RemotePythonError -> HttpError, __cause__ set
def test_json_parse_failure_is_httperror(): ...         # body "<html>" -> Response.json() raises HttpError
def test_step_bracket_and_body_logging(): ...
    # step_push "GET /x", step_pop startswith "200 OK"; ring contains the body
def test_body_truncation_and_marker(): ...
    # body of 5000 chars, log_body default -> ring text has 4096 chars + "... (5000 chars)"
def test_log_body_zero_silences_bodies(): ...           # session log_body=0 and per-request log_body=0
def test_headers_redacted_in_verb(): ...
    # request headers Authorization + session redact={"X-Token"} -> verb lines show "<redacted>"
def test_set_header_and_cookies_ship_ops(): ...         # ops "set_header" and "cookies"
def test_call_inserts_client_first(): ...               # args[0] is client, transport timeout margin applied
def test_session_bootstraps_with_defaults(monkeypatch): ...
    # monkeypatch pyte.tools.http.remote.python with a fake contextmanager yielding _FakeRem;
    # session(pco, "https://d", verify=False) ships bootstrap("https://d", False, {}, MAX_BODY)
    # and logs ring "TLS verification disabled for https://d"; remote.python got timeout 60.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src uv run --no-project --with pytest --with scapy --with pyyaml pytest tests/test_http.py -v`
Expected: FAIL with ModuleNotFoundError for `pyte.tools.http`.

- [ ] **Step 3: Implement `src/pyte/tools/http.py`**

Module docstring in the style of `trex/stl.py` (what runs where, the
stdlib-only reason). `get`/`post`/... are thin delegations to
`request` (keyword-only, so a body on `get` is a TypeError from the
signature). The VERB line format is `http op: <name> <method> <path>`.
The step pop text is `f"{status} {reason} ({elapsed:.3f}s)"`. The
truncation marker is `f"... ({len(body)} chars)"` appended after the
first `log_body` characters.

- [ ] **Step 4: Run tests to verify they pass**

Same command. Expected: all PASS. Also run the whole TE-free subset
from README.md to make sure nothing else broke.

- [ ] **Step 5: Commit**

```bash
git add src/pyte/tools/http.py src/pyte/tools/__init__.py tests/test_http.py
git commit -s -m "tools/http: add the engine-side HTTP session facade"
```

---

### Task 4: Showcase test in python-ts

**Files (in `../python-ts`):**
- Create: `ts/http/session.py`, `ts/http/package.xml`, `ts/http/meson.build`
  (copy `ts/wrk/meson.build`, tests list `['session']`)
- Modify: `ts/meson.build` (add `'http'` to `packages`, alphabetical),
  `ts/package.xml` (add `<run><package name="http"/></run>` after
  `fio`), `trc/top.xml` (package `http` with objective and one PASSED
  iteration for `session`, modelled on the `remote` package entry)

**Interfaces:**
- Consumes: `pyte.tools.http.session`, `Session.get/post/call/cookies`,
  `Response.json`, `HttpError`; `pyte.tools._clientserver.serve`.
- The server runs as `python3 -c <source>` where `<source>` is
  `inspect.getsource(_serve) + f"\n_serve({PORT})\n"` and `_serve(port)`
  is a self-contained function in the test file implementing the same
  routes as Task 2's test handler for `/login`, `/data`, `/echo`
  (stdlib `http.server`, bind 127.0.0.1). `PORT = 8081`.

- [ ] **Step 0: Point the python-ts submodule at the pyte `http` branch**

`python-ts/lib/pyte` is a git submodule (pinned to an older pyte
commit, detached). Run from `../python-ts`:
```bash
git -C lib/pyte fetch /home/kostik/prj/te/pyte http && git -C lib/pyte checkout FETCH_HEAD
```
Expected: `git -C lib/pyte log --oneline -1` shows the Task 3 commit.
The submodule pointer is committed together with the showcase in
Step 5 so the suite and the library move as one.

- [ ] **Step 1: Write the showcase test**

Module docstring (first line is the objective): "Talk to an HTTP JSON
API on the agent: login cookie, views, agent-side filter." Steps, in
order, between `# docs:begin http-session` and `# docs:end`:
1. `t.step("Unauthenticated view answers 401")`: `web.get("/data", ok=False).status == 401` else `t.fail`.
2. `t.step("Log in; the cookie stays on the agent")`: `web.post("/login", json={"user": "admin", "pass": "x"}, log_body=0)`; `web.cookies() == {"sid": "abc123"}`.
3. `t.step("The view now answers JSON")`: `web.get("/data").json()["items"] == [1, 2, 3]`.
4. `t.step("Query parameters and headers reach the server")`: `web.get("/echo", params={"q": "1"}).json()["query"] == {"q": ["1"]}`.
5. `t.step("A shipped function filters on the agent")`: define `def item_sum(client, path): return sum(client.request("GET", path)["json"]["items"])`; `web.call(item_sum, "/data") == 6`.
6. `t.step("A missing path raises HttpError with the status")`: `web.get("/nope")` must raise `HttpError` whose `.response.status == 404`.

- [ ] **Step 2: Register the package and TRC entry**

Edit the three files listed under Modify. `package.xml` description:
"HTTP client session showcase: a JSON API on the agent via
pyte.tools.http". No `<req>`: the test needs only python3 on the agent.

- [ ] **Step 3: Run the showcase on the localhost rig**

Run (from `../python-ts`): `./scripts/run.sh --cfg=localhost --tester-run=python-ts/http`
Expected: `session` PASSED in the Tester summary; the HTML log shows
the six step brackets with `POST /login` having no body line.

- [ ] **Step 4: Lint**

Run (from `../python-ts`): `uv run ruff check ts/http`
Expected: no findings.

- [ ] **Step 5: Commit (python-ts repo)**

```bash
git add ts/http ts/meson.build ts/package.xml trc/top.xml lib/pyte
git commit -s -m "http: add the HTTP session showcase package"
```
Make the python-ts work on a branch `http` created from `main`.

---

### Task 5: Docs

**Files (pyte repo):**
- Create: `docs/guides/http.md`
- Modify: `docs/index.md` (add `guides/http` after `guides/remote`),
  `docs/showcase/index.md` (add `http` between `fio` and `iperf3`)

**Interfaces:**
- Consumes: the `http-session` snippet from Task 4 (generated into
  `docs/_snippets/http-session.py` by `showcase_gen` at build time).

- [ ] **Step 1: Write `docs/guides/http.md`**

Title `# pyte.tools.http: talk to an HTTP API from the agent`. Sections,
in this order, each a short paragraph in the style of
`docs/guides/tools-fio.md`:
1. What it is: a session on the agent over pyte.remote, stdlib only,
   cookies stay on the agent; `literalinclude` of `/_snippets/http-session.py`.
2. Requests and bodies: the four verbs, `json=`/`form=`/`data=` with
   `content_type=`, `params=`, `headers=`, `ok=`, `timeout=`.
3. Results and failures: Response fields, `json()`, when HttpError is
   raised, `response` attribute, the sentence that only a pyte.remote
   transport failure makes the session unusable while HTTP-level
   failures leave it usable.
4. Logging: the step bracket, body truncation and `log_body=`, the
   redaction rule, `verify=False` being logged.
5. Agent-side work: `call()` inserting the live client, the
   `Client.request` and `Client.cookies` contract, the timeout-margin
   note for multi-request functions, `session.remote` as escape hatch.
6. Limits: 8 MiB body cap, text bodies only, no persistence across
   tests, proxies ignored.

- [ ] **Step 2: Build the docs from scratch with -W**

Run (from pyte, with `../python-ts` containing Task 4):
```bash
rm -rf docs/_build && uv run --no-project --with-requirements docs/requirements.txt \
  sphinx-build -W --keep-going -b html docs docs/_build/html
```
Expected: exit 0, `docs/_build/html/guides/http.html` and
`docs/_build/html/showcase/http.html` exist and the guide shows the
snippet.

- [ ] **Step 3: Commit**

```bash
git add docs/guides/http.md docs/index.md docs/showcase/index.md
git commit -s -m "docs: add the pyte.tools.http guide and showcase page"
```

---

### Task 6: Whole-branch verification

- [ ] **Step 1: Full TE-free unit run**

Run the README.md TE-free command (whole `tests/` with its ignores).
Expected: all PASS, no new warnings about `_http_ops` imports.

- [ ] **Step 2: Ruff on pyte**

Run (from `../python-ts`): `uv run ruff check lib/pyte/src/pyte/tools/http.py lib/pyte/src/pyte/tools/_http_ops.py`
(or the equivalent path if `lib/pyte` is a symlink to this repo).
Expected: no findings.

- [ ] **Step 3: Report**

List the commits on `http` in both repos. Do not push.
