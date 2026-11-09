# pyte.tools.http: talk to an HTTP API from the agent

`pyte.tools.http` opens an HTTP client session on a test agent.  The
requests run on the agent, through `pyte.remote`, with nothing but the
Python standard library (urllib), so nothing is installed there.  The
cookie jar lives on the agent for the whole session: a login cookie is
sent back by every later request without the engine ever handling it.

From the showcase test `ts/http/session.py` (a tiny JSON server is
started on the agent with `serve()`; `web` is the session):

```{literalinclude} /_snippets/http-session.py
:language: python
```

## Requests and bodies

`http.session(pco, base_url, ...)` is a context manager yielding a
`Session`.  Paths are joined to `base_url`; a path starting with
`http://` or `https://` is used as is.  `get()`, `delete()`, `post()`
and `put()` are shortcuts for `request(method, path, ...)`.

`post()` and `put()` take at most one body: `json=` (encoded as JSON,
`application/json`), `form=` (URL-encoded, a list value repeats the
key) or `data=` (a `str` or `bytes` sent verbatim, which requires
`content_type=`).  Giving two of them raises `ValueError`.  An explicit
`content_type=` given with `json=` or `form=` overrides the default
Content-Type of that kind.  Bytes in `data=` cross the transport
base64-encoded and are decoded on the agent, while `str` goes as text.

All verbs accept `params=` (query string, appended to the URL),
`headers=` (per-request, win over session headers), `timeout=`
(seconds, default is the session's 30.0) and `ok=`.  With the default
`ok=True` a non-2xx answer raises `HttpError`; pass `ok=False` to
inspect such answers yourself.  `set_header(name, value)` changes a
session default header; `None` removes it.  Session and per-request
headers (Authorization included) are copied onto redirect targets by
the stdlib redirect handler, even across hosts.

## Results and failures

Every request returns a frozen `Response` with `status`, `reason`,
`headers` (names lower-cased), `body` (text), `url` (final URL after
redirects) and `elapsed` (seconds).  `resp.ok` is true for 2xx and
`resp.json()` parses the body, raising `HttpError` when it is not JSON.

`HttpError` is raised when a response is not 2xx and `ok=True`; its
`response` attribute then holds the `Response`, so the status and body
stay available (see the 404 step in the snippet).  It is also raised
when the request itself fails on the agent (connection refused,
timeout, body over the size cap) or the session cannot be set up; in
those cases `response` is not set.  Only a `pyte.remote` transport
failure makes the session unusable; HTTP-level failures leave it
usable and the next request works.

## Logging

Each request is a log step named `METHOD path`, closed with
`status reason (elapsed)`, or with `failed` when no response arrived.
Inside it, request and response bodies go to the RING level, cut after
`log_body` characters (default 4096) with a `... (N chars)` suffix;
`log_body=0` silences them, as the login in the snippet does.  Set it
per session or per request.  Headers are logged at VERB.

Header values of `Authorization`, `Cookie` and `Set-Cookie` are always
logged as `<redacted>`; `redact=[...]` on `session()` adds more header
names (case-insensitive).  Only header values are redacted: bodies and
query strings are logged as they are, so use `log_body=0` for secrets.
`verify=False` disables TLS verification and is logged at RING when the
session opens.

## Agent-side work

`web.call(fn, *args)` ships a self-contained function to the agent and
inserts the live client as its first argument, so a filter or a
multi-request flow runs without a round trip per request (`item_sum` in
the snippet).  The function runs in the agent's python3, so it must do
its imports inside its body and use only the standard library.

The client offers two methods for this.  `client.request(method, path,
**kw)` takes the same keywords as `Session.request()` (without `ok`
and `log_body`; `data` as `str` or `bytes`) and returns a plain dict
with `status`, `reason`, `headers`, `body`, `url`, `elapsed` and
`json` (the parsed body, or `None`).  It does not raise on non-2xx.
`client.cookies()` returns the cookies as a name to value dict.

The transport timeout of `call()` is `timeout` (default: the session's)
plus a 30 second margin.  A function that makes several requests should
be given a `timeout=` that covers all of them.  `web.remote` is the
underlying `pyte.remote` session, an escape hatch for anything else.

## Limits

- A response body over 8 MiB fails the request with `HttpError`.
- Bodies are text: they are decoded with the declared charset (UTF-8
  by default, undecodable bytes replaced), so binary downloads are not
  supported.
- A session lives inside one `with` block; nothing persists across
  tests, and the cookies go away with it.
- Proxy environment variables are ignored: requests go direct.
