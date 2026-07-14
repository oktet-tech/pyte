# pyte.remote — run Python on the agent host

`remote.python(pco)` starts a Python interpreter **on the agent host**
and lets the test drive it: ship self-contained functions with
`rem.call()`, or work with agent-side libraries through transparent
proxies.  Zero install on the agent — only `python3` with the stdlib
is required there; everything else ships over the wire.

The showcase test `ts/remote/lib_proxy.py` drives an agent-side
sqlite3 database through proxies:

```{literalinclude} /_snippets/remote-lib-proxy.py
:language: python
```

## How a session works

A session is an ordinary `tapi_job`: the *source* of
`pyte._remote_runner` is passed verbatim as `python3 -u -c <source>`,
so nothing is installed on the agent.  Requests are JSON lines written
to the job's stdin; responses are JSON lines read back through a
readable stdout filter; stderr is logged to TE, so remote `print()`s
and crash tracebacks land in the run log.

```{mermaid}
flowchart LR
    subgraph engine [test process — engine]
        RP["RemotePython._request()"]
    end
    subgraph agent [agent host]
        RN["python3 -u -c &lt;runner&gt;<br/>Runner.serve(): decode &rarr;
dispatch &rarr; encode"]
    end
    RP -- "JSON line, job stdin (RPC)" --> RN
    RN -- "JSON line, stdout filter (RPC)" --> RP
    RN -. "stderr" .-> LOG["TE log"]
```

Every proxy operation is one synchronous, id-paired round trip
(`job_send` + `job_receive` RPCs, silenced to keep the log readable).

## Only four operations cross the wire

There is no per-library support code anywhere — sqlite3 above needed
none.  Everything any Python API does through a proxy decomposes into
four generic requests:

| op        | triggered by             | runner executes                  |
|-----------|--------------------------|----------------------------------|
| `import`  | `rem.import_module("x")` | `importlib.import_module("x")`   |
| `getattr` | `proxy.anything`         | `getattr(objects[h], "anything")`|
| `callobj` | `proxy(...)`             | `objects[h](*args, **kwargs)`    |
| `call`    | `rem.call(fn, ...)`      | `exec(src)` then `fn(*args)`     |

The interception is Python's own attribute protocol: `RemoteObject`
defines `__getattr__` and `__call__`, so `conn.execute("...")` is two
round trips — `getattr` (returning a proxy for the bound method), then
`callobj` on that proxy.  Chains of any length decompose the same way.

## Marshalling: by value or by handle

Only the *values* flowing through those operations are converted, with
one recursive rule applied in both directions:

1. A proxy encodes as its handle: `{"__pyte_ref__": N}`.
2. Lists, tuples and dicts recurse into their elements (containers may
   mix values and proxies).
3. Anything `json.dumps` accepts crosses **by value** — with JSON
   semantics: tuples become lists, dict keys become strings.
4. Anything else is **not converted at all**: the runner stores the
   object in a per-session table and sends `{"__pyte_ref__": N}`; the
   engine wraps that in a `RemoteObject`.

So objects that cannot survive JSON never cross the boundary — they
stay alive in the agent-side interpreter and only an integer handle
travels.  That is what makes state accumulate across calls (the
in-memory database above lives in the remote process), and it works in
both directions: passing a proxy as an argument sends its handle, and
the runner hands the callee the *live* object, not a copy.

The key `__pyte_ref__` is reserved.  A real dict containing it cannot
cross by value (decode would misread it as a handle): the engine
refuses to send one, and the runner ships such a dict as a proxy
instead of a value.

## Shipped functions

`rem.call(fn, *args)` extracts the function's **source text** with
`inspect.getsource()` and `exec`s it in the runner — bytecode,
closures and pickles never cross.  Consequences, enforced with clear
errors before anything is sent:

- no lambdas (their source is an expression, not a definition);
- no closures — pass captured values as arguments instead;
- no globals: the function must be self-contained, imports go
  *inside* the body (a `NameError` otherwise surfaces in the remote
  traceback);
- no `async` functions.

## What is deliberately NOT proxied

Attribute **assignment** raises: a silently-local attribute would
shadow the remote one on every later read.  Indexing, `len()`,
iteration and comparisons are not proxied either — CPython resolves
those dunders on the *type*, bypassing instance `__getattr__`, so a
proxy never sees them (underscore-prefixed attributes are refused for
the same reason).  Fetch values and operate locally, or do the work
inside a shipped function.

## Lifecycle and failure semantics

- **Timeouts**: each request runs under the session (or per-call)
  timeout.  After a timeout the reply may still be in flight, so the
  request/response pairing can no longer be trusted: the session is
  marked **broken** and every further request raises — start a new
  `remote.python()` session instead of resyncing.  An EOS on the
  stdout filter (the runner died) breaks the session the same way,
  with the job's exit status in the error.
- **Proxy release**: a garbage-collected `RemoteObject` does no I/O
  (GC may fire mid-request); its handle is queued and piggybacked on
  the next request's `"free"` field, so releases cost zero extra
  round trips.
- **Teardown**: leaving the `with remote.python(pco)` block sends a
  best-effort `shutdown` request, then the job context destroys the
  interpreter regardless.
- **Protocol hygiene**: the runner rebinds `sys.stdout` to stderr
  before serving, so user `print()`s go to the TE log instead of
  corrupting the protocol stream; responses are `ensure_ascii` JSON,
  so every protocol byte is 7-bit and no multibyte character can
  straddle a filter chunk boundary.
