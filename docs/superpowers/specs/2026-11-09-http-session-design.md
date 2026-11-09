# pyte.tools.http: an HTTP client session on a test agent

Date: 2026-11-09
Status: awaiting approval

## Intent

Some devices under test expose their state only through a web UI, and
the device's management network is reachable only from one of the test
agents (typically a control host next to the device). A Python test on
the engine needs to log in to such a device, call the JSON endpoints
the web UI itself uses, and analyse the answers engine-side.

This design adds a generic layer to pyte: an HTTP client session that
lives on an agent host and is driven from the test. Device knowledge
(the login dance, the endpoint names, the shape of the answers) stays
in the suite, as a thin class over this session. pyte never learns
what any particular device is.

## Goals

- A test can open an HTTP session on a named agent, make requests
  against a base URL, keep the cookies the device sets, and read JSON
  answers, with every request and its outcome visible in the TE log.
- A suite can put device knowledge in a plain class that takes the
  session and exposes named views, with no pyte changes per device.
- A suite can run a self-contained filter function on the agent, using
  the live client, so a large view never crosses the wire when only a
  summary is needed.
- Zero install on the agent: Python 3 with the standard library only.
  Control hosts in the lab commonly lack requests and urllib3.

## Non-goals

- No session persistence across tests. The session is a context manager
  inside one test and dies with the test's agent-side interpreter.
- No device-specific code in pyte: no login helpers, no device
  endpoints.
- No HTML scraping support. Bodies are returned as text and the caller
  parses; only JSON gets an accessor.
- No streaming, websockets, chunked uploads, or file downloads bigger
  than what fits in one JSON-line reply of the pyte.remote protocol.
- No HTTP server side. Load generation against HTTP servers is wrk.

## Anti-goals

- A second remote-execution mechanism. The session must be built on
  pyte.remote exactly as the TRex STL facade is; if it needs something
  pyte.remote cannot do, extend pyte.remote, do not bypass it.
- An agent side that depends on a third-party library, even optionally.
  One code path, stdlib only.
- Request and response bodies missing from the log when a test fails.
  The whole point is that a failed analysis is traceable to what the
  device actually returned.

## Constraints and prior art

- Build on `pyte.remote.python()`: one agent-side interpreter per
  session, op-functions shipped by source, self-contained (imports in
  the body, no closures, no module globals), JSON-able arguments and
  results, live objects crossing as handles. See docs/guides/remote.md.
- Follow the TRex STL facade shape (src/pyte/tools/trex/stl.py and
  _ops.py): engine-side facade class, agent-side ops module, one
  readable `log.step_push`/`step_pop` bracket per operation, a `VERB`
  line naming each shipped op, RemotePythonError translated into a
  ToolError subclass.
- Error class: `HttpError(ToolError)` in src/pyte/errors.py, docstring
  only, same as the other per-tool errors.
- Agent hosts run Python 3.14; do not assume anything newer than 3.10
  on the agent side since other rigs may be older.
- Follow the pyte docs-by-design convention: a showcase test in
  python-ts with `docs:begin`/`docs:end` markers, a guide page, and the
  gallery entry; the docs build with -W must pass.
- Plain ASCII in docs and docstrings.

## The decided design

### Module layout

- `src/pyte/tools/http.py`: engine side. `session()`, `Session`,
  `Response`.
- `src/pyte/tools/_http_ops.py`: agent side, shipped by source.
  `bootstrap()`, `request()`, `set_header()`.
- `src/pyte/errors.py`: `HttpError(ToolError)`.

### Opening a session

```python
from pyte.tools import http

with http.session(pco, "https://10.211.10.200",
                  verify=False, timeout=30.0,
                  headers={"Accept": "application/json"}) as web:
    ...
```

- `pco` is the RPC server on the agent that can reach the device. The
  session starts one `remote.python(pco)` interpreter and ships
  `bootstrap()`, which builds the agent-side `Client` and returns it as
  a handle. The handle is kept by the `Session` and passed back into
  every shipped op.
- `base_url` is required. Request paths are joined to it; an absolute
  URL passed as a path is used as is.
- `timeout` (default 30.0 seconds) is the per-request socket timeout on
  the agent. The pyte.remote transport timeout is `timeout` plus a
  fixed margin, so the agent-side request is always the one that times
  out first and can report why. Same rule as TRex's WAIT_MARGIN.
- `verify` (default True) controls TLS certificate and hostname
  verification. `verify=False` is the explicit opt-out for self-signed
  lab devices and is logged at RING once when the session opens.
- `headers` are default headers sent with every request. A header set
  per request overrides the default for that request only.
- Leaving the block tears the interpreter down; cookies die with it.

### Making requests

```python
r = web.get("/api/sessions", params={"limit": 1000})
r = web.post("/api/login", json={"user": "Admin", "pass": "1"})
r = web.post("/api/upload", data=b"...", content_type="text/xml")
r = web.post("/api/form", form={"a": "1", "b": "2"})
r = web.request("PATCH", "/api/x", json={...}, headers={"X-Y": "z"})
```

- Methods: `get`, `post`, `put`, `delete`, and the general `request`.
  `get` and `delete` take no body.
- Body, exactly one of: `json=` (any JSON-able value, serialised with
  `json.dumps`, content type `application/json`), `form=` (a dict,
  urlencoded, content type `application/x-www-form-urlencoded`), or
  `data=` (bytes or str, content type from `content_type=`, required
  with `data`). Passing two is a ValueError before anything is sent.
- `params=` is a dict appended as a query string.
- `headers=` are per-request headers merged over the session defaults.
- `ok=True` (default) raises `HttpError` on any status outside 200-299.
  `ok=False` returns the Response for any status so a test can assert
  on an expected 401 or 404.
- `timeout=` overrides the session timeout for one request.
- `log_body=` overrides the session body-log limit for one request
  (0 silences the bodies of that request, for a login carrying a
  password).
- Cookies: the agent-side client has an `http.cookiejar.CookieJar`
  behind an `HTTPCookieProcessor`. Every Set-Cookie is kept and sent
  back on later requests to the same host. That is all a login needs,
  so pyte has no login concept.
- Redirects: followed, as urllib does by default. The Response reports
  the final URL.
- `web.set_header(name, value)` adds or replaces a session default
  header after the fact, for bearer tokens obtained from a login
  answer. `web.set_header(name, None)` removes it.
- `web.cookies()` returns the jar as `dict[str, str]` (name to value,
  for the base URL's host). This is the generic accessor a suite needs
  when a UI copies a cookie value into a header on every mutating call
  (the CSRF pattern), or when a login answers with a redirect and the
  Set-Cookie sits on the intermediate response that `Response.headers`
  never shows. Cookie values are redacted in the log like `Cookie`
  headers. Author's call after the builder check.
- Proxy environment variables (`http_proxy`, `https_proxy`, `no_proxy`)
  on the agent are ignored: the opener is built with an empty
  `ProxyHandler`, so lab traffic never silently routes through a proxy
  a host happens to have configured. There is no `proxies=` option in
  this version. Author's call.

### Results

```python
@dataclass
class Response:
    status: int
    reason: str
    headers: dict[str, str]     # keys lower-cased, last value wins
    body: str                   # decoded text; see encoding below
    url: str                    # final URL after redirects

    def json(self): ...         # json.loads(self.body); raises HttpError
                                # with the body excerpt on failure
```

- The body is decoded on the agent using the charset from the
  Content-Type header, falling back to UTF-8 with errors replaced.
  Binary bodies are out of scope for this version; if one is needed
  later a `raw: bytes` field and base64 transport is the extension
  point, not a change to `body`.
- `json()` is a method, not a property, so the parse error carries the
  path and an excerpt of the body in the message.

### Failures

- `HttpError(ToolError)` is raised for: transport failures (connection
  refused, DNS, TLS, socket timeout), a non-2xx status when `ok=True`,
  and a JSON parse failure in `Response.json()`.
- An `HttpError` raised for a status carries the Response in a
  `response` attribute, so a handler can read the device's answer. The
  message is one line: method, path, status and reason, then the first
  200 characters of the body with newlines collapsed.
- A RemotePythonError from the transport (runner died, pyte.remote
  timeout, EOS) is wrapped into HttpError with the original as
  `__cause__`, the same way TrexError wraps it. Only in that case is
  the session unusable afterwards and the test must open a new one.
  An HTTP-level failure (connection refused, TLS error, agent-side
  socket timeout, non-2xx status) also raises HttpError but leaves the
  session usable: the agent-side request is the one that timed out,
  the pyte.remote transport (session timeout plus the margin) never
  did, and the next request works. The guide says this explicitly.
- Reply size: the agent-side op caps the response body (default
  8 MiB, below the 16 MiB TE job filter queue) and raises a clean
  error naming the length, instead of letting an oversized JSON line
  break the pyte.remote protocol mid-reply. Author's call.
- Agent-side `urllib.error.HTTPError` is caught inside the shipped op
  and turned into a normal result dict, so a 4xx never surfaces as a
  remote traceback; only true transport failures raise on the agent.

### Logging

- Each request is one step bracket: push `GET /api/sessions`, pop with
  the status and reason, `200 OK`, and the elapsed time.
- The request body (when any) and the response body are logged at RING
  inside the bracket, truncated to a per-session limit, default 4096
  characters, with a marker giving the full length. The limit is a
  `session()` keyword (`log_body=`); 0 disables body logging for
  high-volume polling loops.
- Headers are logged at VERB. The values of `Authorization`, `Cookie`,
  `Set-Cookie` and any header named in a `redact=` session keyword are
  replaced with `<redacted>` in the log at every level. Passwords in a
  JSON login body are the suite's problem: the suite passes
  `log_body=0` for that one request, or the per-request `log_body=`
  override, and the design accepts that the default logs the body.
- Every shipped op gets a `VERB` line `http op: <name> <detail>` like
  TRex's `stl op:`.

### Agent-side work

```python
def _count_by_proto(client, path):
    import collections
    r = client.request("GET", path)
    return dict(collections.Counter(s["proto"] for s in r["json"]))

counts = web.call(_count_by_proto, "/api/sessions")
```

- `Session.call(fn, *args, timeout=None, **kwargs)` ships `fn` through
  `rem.call` with the live agent-side client inserted as the first
  argument. The same self-containment rules as `remote.call` apply and
  the same errors surface, wrapped in HttpError. The transport timeout
  for a `call` is the session timeout plus the margin, so a shipped
  function that makes several requests must pass a larger `timeout=`;
  the guide says so.
- The agent-side `Client.request(method, path, params=None, json=None,
  form=None, data=None, content_type=None, headers=None,
  timeout=None)` is therefore a supported API, not private plumbing,
  and returns the same dict the engine turns into a Response, plus a
  `json` key holding the parsed body when the content type is JSON
  and it parses, else None. Its signature is the stable contract
  between the engine facade and suite-shipped functions.
- `Session.remote` exposes the underlying RemotePython session for a
  suite that wants `import_module` or a second handle. Documented as an
  escape hatch, not as the normal path.

### Showcase test and docs

- python-ts package `ts/http/` with one test, `session.py`: start a
  stdlib HTTP server on the same agent with `_clientserver.serve`, the
  server being a small self-contained script that sets a cookie on
  `POST /login`, answers `GET /data` with JSON only when the cookie is
  present (401 otherwise), and echoes query parameters on `GET /echo`.
  The test shows: a 401 with `ok=False`, login, the cookie working,
  `params=`, `json()`, an agent-side filter through `call`, and an
  `HttpError` for a missing path, and `cookies()` showing the login
  cookie. No external dependency, no new TRC tag, no prologue probe.
  The server script ships as `python3 -c <source>` in argv like the
  remote runner, so it runs on a rig whose agent host has no suite
  tree, and on a port distinct from the wrk showcase's 8080.
- `docs/guides/http.md` following the remote and trex guides, with the
  showcase snippet included through the `docs:begin`/`docs:end`
  markers, and the gallery entry under docs/showcase.
- Unit tests for the engine side with a fake remote session (the TRex
  tests have the pattern), covering body-kind exclusivity, `ok`
  handling, redaction, truncation and error wrapping. The agent-side
  ops get a unit test that runs them in-process against
  `http.server` on loopback, since they are plain functions.

## Left to the builder

- Internal structure of `_http_ops.py` beyond the public `Client`
  signature, and how the op-functions carry the kwargs across.
- The exact margin added to the transport timeout and the elapsed-time
  format in the step pop line.
- How `Response.headers` folds repeated headers beyond "last wins".
- The server script used by the showcase and where it lives.
- Whether `Session` implements `get`/`post`/... by delegation to
  `request` or as one generated method per verb.
- Test file names and the order of steps in the showcase.

## Scope decision

The deliverable is pyte only: the module, the agent-side ops, the error
class, unit tests, the loopback showcase test in python-ts and the
docs. A suite-side device class driven against a real device is a
separate follow-up project. Decided by the author of the request on
2026-11-09.

## Open questions

None.
