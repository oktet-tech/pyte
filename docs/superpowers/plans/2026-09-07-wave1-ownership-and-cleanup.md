# Wave 1: Ownership and Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every pyte resource fail loudly instead of passing a freed pointer into C, and make every cleanup path attempt all its work without ever replacing the exception that caused the unwind.

**Architecture:** Three independent mechanisms. A single `ClosedResourceError` plus a checked `_handle()` accessor replaces the copy-pasted liveness guards (`RpcServer` has none today and is the one crash-class hole). A `cleanup_all()` helper centralizes the "attempt everything, preserve the primary exception" policy that nine `finally` blocks currently get wrong. Two new shim getters let `quiet()`/`silent_pass()` restore the state they actually found instead of a hardcoded constant.

**Tech Stack:** Python 3.11+, cffi shim over TE C libraries, pytest.

**Spec:** `/home/kostik/prj/te/pyte-api-fixes-plan-2026-09-07.md` (wave 1 section). Evidence: `/home/kostik/prj/te/pyte-api-fixes-review-2026-09-07.md`.

## Global Constraints

- Repo `/home/kostik/prj/te/pyte`, branch `wave1-ownership` (branched off `trexb` at c5b4c6c). Do NOT switch branches; the user works on `trexb` concurrently. Run tests with `.venv/bin/python -m pytest tests/ -q`. Do NOT use `uv run pytest`: it rebuilds the shim and fails with `RuntimeError: TE_INSTALL must be set`.
- Lint with `ruff check src tests setup.py`. Must print "All checks passed!".
- Baseline to keep green: **953 passed, 1 skipped**.
- New files start with `# SPDX-License-Identifier: Apache-2.0` (line 1) and `# Copyright (C) 2026 Konstantin Ushakov` (line 2).
- Breaking changes are permitted (pyte is 0.1.0; every consumer pins it). Name each one in the commit body.
- Style: 4-space indent, no tabs, wrap at 79 columns.
- Commit summary: `component: lowercase imperative description`, at most 60 chars. Body wraps at 72. Use `git commit -s`.
- Do NOT add `Claude-Session:` trailers or any AI attribution.

## Test-double conventions you MUST follow

There is no shared shim double for resources. `pyte.testing.fake_shim` covers **only** logging, test structure, tester calls and te_errno stringification — it has no `pyte_job_*`, `pyte_rpc_*` or `ffi.new()` at all. Every test file hand-rolls its own. Use the one belonging to the file you are editing:

| File | Existing helpers to reuse |
|---|---|
| `tests/test_job.py` | `_fake_shim(monkeypatch)` returning a local `FakeLib` (records into `.calls`); `_fake_job(handle=object())` returning `Job(None, handle, "prog")` |
| `tests/test_server.py` | `_bare_server()` (`RpcServer.__new__` + `_h` + `_silent_pass_depth`); `_no_shim_calls` trap fixture; `_fake_sh_shim(monkeypatch, output, flag, value)` |
| `tests/test_iomux.py` | local `FakeLib` + `_fake_shim(monkeypatch, lib)`; autouse `_reset_event_bits` |
| `tests/test_csap.py` | local `FakeLib`, `_bare_csap()`, autouse `_clear_sessions` |
| `tests/test_cfg_engine.py` | the `fake` fixture, which monkeypatches `cfg.get`/`cfg.set` and records into `fake.sets` |
| `tests/test_cfg.py` | `_install_fake_get(monkeypatch, value, cvt)`, `_install_fake_add(monkeypatch)` |
| `tests/test_tool_helpers.py` | `FakeJob`, `FakeFilter`, `Demo(ToolHandle)` — plain Python, no shim |
| `tests/test_clientserver.py` | `FakeChannel`, `FakeJob`, `FakePco` — plain Python |
| `tests/test_trex_batch_lifecycle.py` | `_FakePco`, `_FakeJob`, `_FakeFilter`, `_batch_opts()`, autouse `_fake_rcf_agent` |
| `tests/test_env.py` | **none** — it constructs real objects and monkeypatches. Add a local fake in Task 3. |
| `tests/test_errors.py` | none; uses the real shim for `errors.E*` lookups only |

Do not add a shim-level double where the file fakes one layer up.

---

### Task 1: One closed-handle exception

**Files:**
- Modify: `src/pyte/errors.py` (insert after `RemotePythonError`, before `TimeoutError`)
- Modify: `src/pyte/job.py:128,170,203,498`
- Modify: `src/pyte/rpc/iomux.py:161,171,181,201`
- Modify: `src/pyte/tad/csap.py:150`
- Modify: `src/pyte/trc.py:130,180,259,368,454`
- Test: `tests/test_errors.py`, `tests/test_job.py`, `tests/test_iomux.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `pyte.errors.ClosedResourceError(msg: str)` and `pyte.errors.TrcClosedError(msg: str)`. Tasks 2 and 7 raise `ClosedResourceError`.

**Why two classes:** `ClosedResourceError` subclasses `RuntimeError` so the existing `except RuntimeError` call sites keep working, and `TeError` so `except TeError` catches it. `trc.py` raises `TrcError` for the same semantic and trc-tool catches that, so trc gets a subclass satisfying both.

Both use a message-only `__init__` like `RemotePythonError`: `TeError.__init__` touches the shim on every construction, and a liveness guard must be constructible with no shim.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_errors.py` (it imports `from pyte import errors` — check the existing import line and match it):

```python
def test_closed_resource_error_is_both_te_and_runtime():
    exc = errors.ClosedResourceError("job 'ls' is already destroyed")
    assert isinstance(exc, errors.TeError)
    assert isinstance(exc, RuntimeError)
    assert str(exc) == "job 'ls' is already destroyed"


def test_closed_resource_error_needs_no_shim():
    """TeError.__init__ calls the shim; a liveness guard must not."""
    exc = errors.ClosedResourceError("x is closed")
    assert (exc.rc, exc.module, exc.code) == (0, 0, 0)


def test_trc_closed_error_satisfies_both_bases():
    exc = errors.TrcClosedError("TRC database is closed")
    assert isinstance(exc, errors.ClosedResourceError)
    assert isinstance(exc, errors.TrcError)
    assert isinstance(exc, RuntimeError)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_errors.py -k closed -v`
Expected: FAIL, `AttributeError: module 'pyte.errors' has no attribute 'ClosedResourceError'`

- [ ] **Step 3: Write the implementation**

In `src/pyte/errors.py`, insert after the `RemotePythonError` class:

```python
class ClosedResourceError(TeError, RuntimeError):
    """Operation on a resource that has already been closed.

    One idiom for what used to be nine copy-pasted guards raising two
    unrelated types.  Subclasses RuntimeError so the call sites that
    raised it keep working, and TeError so ``except TeError`` covers a
    closed-handle failure like any other pyte error.

    Message-only: TeError.__init__ reaches the shim on every
    construction, and a liveness guard must be raisable without one.
    """

    def __init__(self, msg: str):
        Exception.__init__(self, msg)
        self.rc = 0
        self.module = 0
        self.code = 0


class TrcClosedError(ClosedResourceError, TrcError):
    """A borrowed TRC view used after its Db was closed.

    trc.py raised a plain TrcError here and trc-tool catches that, so
    the unified error stays a TrcError as well as a
    ClosedResourceError.
    """
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_errors.py -k closed -v`
Expected: 3 passed

- [ ] **Step 5: Switch the existing guards over**

`src/pyte/job.py` — add `ClosedResourceError` to the existing `from pyte.errors import check` line, then change the class (messages unchanged) at:
- `:128` channel guard, `:170` input-channel guard, `:203` filter guard, `:498` `Job._handle`

`src/pyte/rpc/iomux.py` — import `ClosedResourceError`; replace the four `raise RuntimeError("IoMux is closed")`.

`src/pyte/tad/csap.py:150` — replace `raise RuntimeError("receive operation already finished")`. Leave `csap.py:265`'s `RuntimeError("a receive operation is already active")` alone: that is a misuse error, not a liveness guard.

`src/pyte/trc.py` — import `TrcClosedError`; replace the five `raise TrcError("TRC database is closed")`.

- [ ] **Step 6: Pin that the guards are catchable generically**

Append to `tests/test_job.py`:

```python
def test_destroyed_job_guard_is_a_closed_resource_error():
    from pyte.errors import ClosedResourceError
    job = _fake_job()
    job._h = None
    with pytest.raises(ClosedResourceError, match="already destroyed"):
        job._handle()
```

Append to `tests/test_iomux.py`:

```python
def test_closed_iomux_guard_is_a_closed_resource_error(monkeypatch):
    from pyte.errors import ClosedResourceError
    lib = FakeLib()
    _fake_shim(monkeypatch, lib)
    mux = IoMux.create(FakeServer(), Kind.EPOLL)
    mux.close()
    with pytest.raises(ClosedResourceError, match="closed"):
        mux.wait(0)
```

If `IoMux` has no `close()`, set `mux._h = None` directly instead — check the module and use whichever exists.

- [ ] **Step 7: Run the full suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: 956 passed, 1 skipped. Existing `pytest.raises(RuntimeError)` and `pytest.raises(TrcError)` assertions still pass by inheritance.

- [ ] **Step 8: Lint and commit**

```bash
ruff check src tests setup.py
git add -A
git commit -s -m "errors: add one closed-resource exception" -m "Nine liveness guards raised two unrelated types (RuntimeError in
job/iomux/csap, TrcError in trc) for the same semantic, so a caller
could not catch 'this handle is closed' generically.

ClosedResourceError subclasses both TeError and RuntimeError, so the
existing call sites keep working and 'except TeError' now covers it.
Its constructor is message-only because TeError.__init__ reaches the
shim, which a liveness guard must not require.  trc keeps its
contract through TrcClosedError, which is also a TrcError."
```

---

### Task 2: Checked handle access for RpcServer

**Files:**
- Modify: `src/pyte/rpc/server.py:41-70` and the `self._h` uses at `:97,100,175,182,188,196,215,248,280,285,299`
- Modify: `src/pyte/rpc/socket.py` (about 20 `self.server._h` / `server._h`)
- Modify: `src/pyte/rpc/files.py:33,41,51` and `open_file`
- Modify: `src/pyte/job.py:530`
- Modify: `src/pyte/remote.py:348`
- Test: `tests/test_server.py`, `tests/test_env.py`

**Interfaces:**
- Consumes: `ClosedResourceError` from Task 1.
- Produces: `RpcServer._handle()` returning the live `rcf_rpc_server *`, raising `ClosedResourceError` once destroyed. Task 3 relies on `RpcServer._h` remaining the caching identity.

**Background:** the one genuine use-after-free. `destroy()` returns early for env-owned PCOs *without clearing `_h`* (`server.py:63-64`), and `tapi_env_free` later frees that server (`te/lib/tapi_env/tapi_env.c:381`). Sockets and files reach C through `self.server._h` and inherit it.

**BREAKING:** `tests/test_env.py:37` currently asserts `srv._h is not None` after an unowned `destroy()`. That test encodes the bug and must be inverted in Step 5.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_server.py`, with its own local double in the file's established style:

```python
class _LifecycleLib:
    """Fake shim for the RpcServer destroy/getpid lifecycle."""

    PYTE_ETIMEDOUT = 110

    def __init__(self):
        self.calls = []

    def pyte_rpc_server_destroy(self, h):
        self.calls.append(("destroy", h))
        return 0

    def pyte_rpc_getpid(self, h, out):
        self.calls.append(("getpid", h))
        out[0] = 4242
        return 0

    def pyte_rc_error(self, rc):
        return rc

    def pyte_rc_module(self, rc):
        return 0

    def te_rc_mod2str(self, rc):
        return b"RPC"

    def te_rc_err2str(self, rc):
        return b"E"


class _LifecycleFfi:
    NULL = object()

    def new(self, spec):
        return [0]

    @staticmethod
    def string(b):
        return b


def _fake_lifecycle_shim(monkeypatch):
    lib = _LifecycleLib()
    monkeypatch.setitem(
        sys.modules, "pyte._shim",
        types.SimpleNamespace(ffi=_LifecycleFfi(), lib=lib))
    return lib


def test_destroyed_server_raises_instead_of_passing_null(monkeypatch):
    from pyte.errors import ClosedResourceError
    _fake_lifecycle_shim(monkeypatch)
    srv = RpcServer(object(), "Agt", "pco")
    srv.destroy()
    with pytest.raises(ClosedResourceError, match="pco"):
        srv.getpid()


def test_unowned_destroy_clears_the_handle(monkeypatch):
    """tapi_env_free will free this pointer; the wrapper must stop
    handing it to C just because destroy() is a no-op for env PCOs."""
    from pyte.errors import ClosedResourceError
    lib = _fake_lifecycle_shim(monkeypatch)
    srv = RpcServer(object(), "Agt", "iut_rpcs", owned=False)
    srv.destroy()
    assert srv._h is None
    assert not any(c[0] == "destroy" for c in lib.calls)
    with pytest.raises(ClosedResourceError):
        srv.getpid()


def test_destroy_is_idempotent(monkeypatch):
    lib = _fake_lifecycle_shim(monkeypatch)
    srv = RpcServer(object(), "Agt", "pco")
    srv.destroy()
    srv.destroy()
    assert len([c for c in lib.calls if c[0] == "destroy"]) == 1
```

Check `tests/test_server.py`'s imports and add `sys`/`types` if absent (the file already imports them for `_fake_sh_shim`).

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_server.py -k "destroyed or unowned or idempotent" -v`
Expected: FAIL. `getpid()` passes `None` to the fake and returns 4242; `srv._h is None` fails for the unowned case.

- [ ] **Step 3: Add the accessor and fix destroy()**

In `src/pyte/rpc/server.py`, add after `__init__`:

```python
    def _handle(self):
        """The live C handle; raises after destroy().

        pyte_shim passes handles straight into the rcf_rpc_* calls, so
        a NULL handle would crash the test process in C instead of
        raising.  Env-owned PCOs are the sharp case: tapi_env_free
        frees the server out from under any wrapper still holding it.
        """
        if self._h is None:
            raise ClosedResourceError(
                f"RPC server {self.ta}/{self.name} is already destroyed")
        return self._h
```

Replace `destroy()` in full:

```python
    def destroy(self) -> None:
        """Destroy the RPC server; idempotent.

        Env-provided PCOs are owned by tapi_env (tapi_env_free destroys
        them), so the wrapper must not call pyte_rpc_server_destroy for
        them.  It DOES clear the handle either way: tapi_env_free will
        invalidate that pointer, and a wrapper the caller believes is
        dead must not keep handing it to C.
        """
        h, self._h = self._h, None
        if h is None or not self._owned:
            return
        lib = _shim_lib()
        check(lib.pyte_rpc_server_destroy(h),
              f"rpc_server_destroy({self.name})", RpcError)
```

Add `ClosedResourceError` to the module's `from pyte.errors import ...`.

- [ ] **Step 4: Route every call through the accessor**

`server.py`: replace `self._h` with `self._handle()` at lines 97, 100, 175, 182, 188, 196, 215, 248, 280, 285, 299. Do NOT touch `__init__` or the new `destroy()`/`_handle()`.

`socket.py`: replace every `self.server._h` with `self.server._handle()`, and `server._h` in the socket constructor with `server._handle()`.

`files.py`: replace every `self.server._h` with `self.server._handle()`, and `server._h` in `open_file` with `server._handle()`.

`job.py:530`: `server._h` becomes `server._handle()`.

`remote.py:348`: `server=pco._h` becomes `server=pco._handle()`.

- [ ] **Step 5: Invert the test that encoded the bug**

In `tests/test_env.py`, replace `test_rpc_server_not_owned_skips_destroy`:

```python
def test_rpc_server_not_owned_skips_destroy_but_clears_handle():
    """The env owns this server: destroy() must not call the shim, but
    it MUST drop the handle -- tapi_env_free frees that pointer, and a
    retained wrapper would keep passing it to C."""
    srv = RpcServer(object(), "Agt_A", "pco", owned=False)
    srv.destroy()          # must not touch the shim
    assert srv._h is None  # but the handle is no longer usable
```

- [ ] **Step 6: Run tests**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 7: Verify no raw handle access remains**

Run: `grep -rn '\._h\b' src/pyte/rpc/ src/pyte/remote.py src/pyte/job.py | grep -v 'self\._h' | grep -v '_handle'`
Expected: no output. Any hit can still pass a freed pointer to C.

- [ ] **Step 8: Lint and commit**

```bash
ruff check src tests setup.py
git add -A
git commit -s -m "rpc/server: check the handle before every native call" -m "RpcServer was the one wrapper with no liveness guard: every facade
method passed self._h straight to the shim.  For an env-owned PCO
destroy() also returned early WITHOUT clearing the handle, so a
wrapper kept a pointer tapi_env_free later freed -- a genuine
use-after-free, not a NULL deref.  Sockets and files inherited it
through self.server._h.

Add RpcServer._handle() mirroring Job._handle(), route every call
site through it (server, socket, files, job factory, remote), and
clear the handle in destroy() on both the owned and unowned paths.

BREAKING: destroy() on an env-owned server now clears the handle, so
subsequent use raises ClosedResourceError instead of crashing.  The
test that asserted the old behaviour is inverted."
```

---

### Task 3: Env caches PCO wrappers by handle

**Files:**
- Modify: `src/pyte/env.py` (`__init__`, `close`, `pco`)
- Test: `tests/test_env.py`

**Interfaces:**
- Consumes: `RpcServer._handle()` from Task 2.
- Produces: `Env.pco(name)` returning the same `RpcServer` object for repeated lookups of one underlying server.

**Background:** `env.pco()` builds a fresh wrapper per call. Two nap-ts call sites already alias the same PCO, and `_silent_pass_depth` lives per Python object while `rpcs->silent_pass` is one shared C field, so the inner alias's exit clears the flag inside the outer block.

- [ ] **Step 1: Write the failing test**

`tests/test_env.py` has no local doubles. Add one at the top of the file, after the imports:

```python
class _EnvLib:
    """Fake shim for Env lookups and teardown."""

    PYTE_ENOENT = 0x7E02

    def __init__(self):
        self.calls = []
        self.pco_handle = object()

    def pyte_env_get_pco(self, h, name, out):
        self.calls.append(("get_pco", h, bytes(name)))
        out[0] = self.pco_handle
        return 0

    def pyte_rpc_server_ta_name(self, h, out):
        out[0] = b"Agt_A"
        return 0

    def pyte_env_free(self, h):
        self.calls.append(("env_free", h))
        return 0

    def pyte_rc_error(self, rc):
        return rc

    def pyte_rc_module(self, rc):
        return 0

    def te_rc_mod2str(self, rc):
        return b"TAPI"

    def te_rc_err2str(self, rc):
        return b"E"


class _EnvFfi:
    NULL = None

    def new(self, spec):
        return [None]

    @staticmethod
    def string(value):
        return value


def _fake_env(monkeypatch):
    import sys
    import types
    lib = _EnvLib()
    monkeypatch.setitem(sys.modules, "pyte._shim",
                        types.SimpleNamespace(ffi=_EnvFfi(), lib=lib))
    env = env_mod.Env.__new__(env_mod.Env)
    env._h = object()
    env._cfg = "test-env"
    env._pcos = {}
    return env, lib
```

Then the tests:

```python
def test_pco_returns_the_same_wrapper_for_the_same_server(monkeypatch):
    env, _ = _fake_env(monkeypatch)
    assert env.pco("iut_rpcs") is env.pco("iut_rpcs")


def test_close_invalidates_every_handed_out_pco(monkeypatch):
    from pyte.errors import ClosedResourceError
    env, _ = _fake_env(monkeypatch)
    pco = env.pco("iut_rpcs")
    env.close()
    with pytest.raises(ClosedResourceError):
        pco._handle()
```

`_take_str` decodes and frees via the shim; if `_EnvLib` needs `pyte_free_string`, add a no-op recording method.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_env.py -k "same_wrapper or invalidates" -v`
Expected: FAIL on `is` (two distinct wrappers) and on the close test (nothing invalidates handed-out wrappers).

- [ ] **Step 3: Implement the cache**

In `src/pyte/env.py`, add to `Env.__init__` after the existing attributes:

```python
        #: RpcServer wrappers handed out by pco(), keyed by C handle.
        #: Aliases must share one object: silent_pass depth is
        #: per-wrapper while rpcs->silent_pass is one shared C field.
        self._pcos: dict = {}
```

Replace the tail of `pco()` (from the `ta_out` line):

```python
        ta_out = ffi.new("char **")
        check(lib.pyte_rpc_server_ta_name(out[0], ta_out),
              f"pco {name!r} ta", EnvError)
        handle = out[0]
        cached = self._pcos.get(handle)
        if cached is not None:
            return cached
        srv = RpcServer(handle, _take_str(ta_out), name, owned=False)
        self._pcos[handle] = srv
        return srv
```

Replace `close()`:

```python
    def close(self) -> None:
        """Free the environment (closes env-created RPC servers).

        Invalidates every PCO wrapper handed out first: tapi_env_free
        frees the underlying rcf_rpc_server, so a retained wrapper
        would otherwise hold a dangling pointer.
        """
        lib = _shim_lib()
        for srv in self._pcos.values():
            srv._h = None
        self._pcos.clear()
        if self._h is not None:
            h, self._h = self._h, None   # struct is freed even on error
            check(lib.pyte_env_free(h), "env free", EnvError)
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 5: Lint and commit**

```bash
ruff check src tests setup.py
git add -A
git commit -s -m "env: cache pco wrappers and invalidate them on close" -m "env.pco() built a fresh RpcServer per call, so two lookups of one
server produced two wrappers with independent _silent_pass_depth
over a single shared rpcs->silent_pass field: the inner alias's exit
cleared the flag inside the outer block.  Two nap-ts call sites
already alias the same PCO.

Cache by C handle so aliases share one object, and have close()
clear those handles -- tapi_env_free frees the servers, and a
retained wrapper otherwise keeps a dangling pointer."
```

---

### Task 4: The cleanup-all helper

**Files:**
- Create: `src/pyte/_cleanup.py`
- Test: `tests/test_cleanup.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `pyte._cleanup.cleanup_all(*actions, primary=None) -> None`. Each action is a zero-argument callable; `primary` is the exception being unwound, or `None`. Tasks 5, 6 and 7 call it.

**Contract:** run every action even if earlier ones raise. With `primary`, return normally (the caller re-raises it) and attach failures as `primary.cleanup_errors` plus `add_note()` lines, leaving the message untouched. Without `primary`, raise the first failure carrying the rest. Catch `BaseException` so an interrupt mid-teardown does not skip the remaining actions.

- [ ] **Step 1: Write the failing test**

Create `tests/test_cleanup.py`:

```python
# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""pyte._cleanup: attempt every action, never eat the real error."""
import pytest

from pyte._cleanup import cleanup_all


def _raiser(exc):
    def go():
        raise exc
    return go


def test_runs_every_action_even_when_one_raises():
    done = []
    cleanup_all(lambda: done.append(1),
                _raiser(ValueError("boom")),
                lambda: done.append(3))
    assert done == [1, 3]


def test_with_no_primary_raises_the_first_failure():
    first, second = ValueError("first"), ValueError("second")
    with pytest.raises(ValueError) as info:
        cleanup_all(_raiser(first), _raiser(second))
    assert info.value is first
    assert info.value.cleanup_errors == (second,)


def test_primary_exception_is_preserved_exactly():
    primary = RuntimeError("the real failure")
    failure = ValueError("teardown also broke")
    cleanup_all(_raiser(failure), primary=primary)
    assert primary.cleanup_errors == (failure,)
    assert str(primary) == "the real failure"


def test_primary_is_not_raised_by_the_helper():
    # Returns normally: the caller re-raises the primary itself.
    cleanup_all(_raiser(ValueError("x")), primary=RuntimeError("real"))


def test_cleanup_failures_are_noted_on_the_primary():
    primary = RuntimeError("real")
    cleanup_all(_raiser(ValueError("noted")), primary=primary)
    assert any("noted" in n for n in getattr(primary, "__notes__", []))


def test_base_exception_during_cleanup_does_not_skip_the_rest():
    done = []
    primary = RuntimeError("real")
    cleanup_all(_raiser(KeyboardInterrupt()),
                lambda: done.append("still ran"),
                primary=primary)
    assert done == ["still ran"]
    assert isinstance(primary.cleanup_errors[0], KeyboardInterrupt)


def test_no_failures_leaves_the_primary_untouched():
    primary = RuntimeError("real")
    cleanup_all(lambda: None, primary=primary)
    assert not hasattr(primary, "cleanup_errors")


def test_no_failures_and_no_primary_is_a_no_op():
    cleanup_all(lambda: None, lambda: None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_cleanup.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'pyte._cleanup'`

- [ ] **Step 3: Write the implementation**

Create `src/pyte/_cleanup.py`:

```python
# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""One cleanup policy for every teardown path in pyte.

A bare ``finally: resource.close()`` has two bugs pyte hit in nine
places: a raising cleanup REPLACES the exception being unwound (so the
failure a user needs to see is lost and a teardown detail takes its
place), and the first failing cleanup skips every later one (so a
half-torn-down environment leaks the rest).

:func:`cleanup_all` attempts every action, keeps the primary exception
byte-for-byte, and attaches what went wrong during teardown to it.
"""
from __future__ import annotations

from typing import Callable


def _attach(exc: BaseException, failures: list[BaseException]) -> None:
    """Record *failures* on *exc* without altering its message."""
    exc.cleanup_errors = tuple(failures)
    for f in failures:
        exc.add_note(f"cleanup also failed: {f!r}")


def cleanup_all(*actions: Callable[[], object],
                primary: BaseException | None = None) -> None:
    """Run every action; never let a cleanup replace the real error.

    With *primary* given (the exception being unwound) this returns
    normally -- the caller re-raises *primary* itself -- and teardown
    failures are attached to it as a ``cleanup_errors`` tuple and
    exception notes.

    With no *primary*, the first failure is raised carrying the rest
    the same way.

    Catches BaseException: an interrupt arriving mid-teardown must not
    skip the cleanups that have not run yet.
    """
    failures: list[BaseException] = []
    for action in actions:
        try:
            action()
        except BaseException as exc:  # noqa: BLE001  see docstring
            failures.append(exc)
    if not failures:
        return
    if primary is not None:
        _attach(primary, failures)
        return
    first, rest = failures[0], failures[1:]
    if rest:
        _attach(first, rest)
    raise first
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_cleanup.py -v`
Expected: 8 passed

- [ ] **Step 5: Lint and commit**

```bash
ruff check src tests setup.py
git add -A
git commit -s -m "add one cleanup policy helper" -m "Nine finally blocks let a raising cleanup replace the exception
being unwound, and abort the remaining cleanups.  cleanup_all()
attempts every action, preserves the primary exception unchanged,
and attaches teardown failures as a cleanup_errors tuple plus
exception notes.

Catches BaseException deliberately: an interrupt during teardown
must not skip the cleanups that have not run yet."
```

---

### Task 5: Apply the policy to the configuration contexts

**Files:**
- Modify: `src/pyte/cfg/__init__.py` (`backup`, `transaction`, `borrowed_rsrc`)
- Modify: `src/pyte/cfg/_engine.py:64-86` (`CfgObject.saved`)
- Test: `tests/test_cfg_engine.py`, `tests/test_cfg.py`

**Interfaces:**
- Consumes: `cleanup_all` from Task 4.
- Produces: nothing new; behavior change only.

`tests/test_cfg_engine.py`'s `fake` fixture monkeypatches `cfg.get`/`cfg.set`, so a failing restore is induced by making `cfg.set` raise for one OID. No shim double is needed.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cfg_engine.py`:

```python
# -- saved(): attempt every restore, keep the real error --------------

class _TwoKnob(CfgObject):
    mtu = IntKnob("mtu")
    ttl = IntKnob("ip4_ttl")

    def __init__(self, ta, ifname):
        super().__init__(f"/agent:{ta}/interface:{ifname}")


def _fail_setting(fake, monkeypatch, bad_subid):
    """Make cfg.set raise for one subid, recording every attempt."""
    from pyte.errors import CfgError
    attempts = []
    real = cfg.set

    def _set(oid, value, cvt=None):
        attempts.append(oid)
        if bad_subid in oid:
            raise CfgError("restore refused")
        real(oid, value, cvt)

    monkeypatch.setattr(cfg, "set", _set)
    return attempts


def test_saved_restores_every_attribute_despite_one_failure(
        fake, monkeypatch):
    obj = _TwoKnob("A", "eth0")
    fake.store["/agent:A/interface:eth0/mtu:"] = 1500
    fake.store["/agent:A/interface:eth0/ip4_ttl:"] = 64
    attempts = _fail_setting(fake, monkeypatch, "mtu")
    from pyte.errors import CfgError
    with pytest.raises(CfgError):
        with obj.saved("mtu", "ttl"):
            pass
    # ttl attempted even though mtu's restore raised, and in reverse
    # order (ttl was saved last, so it is restored first).
    assert "/agent:A/interface:eth0/ip4_ttl:" in attempts
    assert (attempts.index("/agent:A/interface:eth0/ip4_ttl:")
            < attempts.index("/agent:A/interface:eth0/mtu:"))


def test_saved_does_not_replace_the_body_exception(fake, monkeypatch):
    obj = _TwoKnob("A", "eth0")
    fake.store["/agent:A/interface:eth0/mtu:"] = 1500
    _fail_setting(fake, monkeypatch, "mtu")
    boom = RuntimeError("what the test actually failed on")
    with pytest.raises(RuntimeError) as info:
        with obj.saved("mtu"):
            raise boom
    assert info.value is boom
    assert info.value.cleanup_errors
```

Append to `tests/test_cfg.py`, following its `_install_fake_*` style:

```python
def _install_fake_backup(monkeypatch, fail=()):
    """Record backup create/restore/release; fail the named steps."""
    from pyte.errors import CfgError
    calls = []

    def _step(name):
        def go(*a):
            calls.append(name)
            if name in fail:
                raise CfgError(f"{name} refused")
            return "bk1" if name == "create" else None
        return go

    monkeypatch.setattr(cfg, "_backup_create", _step("create"))
    monkeypatch.setattr(cfg, "_backup_restore", _step("restore"))
    monkeypatch.setattr(cfg, "_backup_release", _step("release"))
    return calls


def test_backup_release_runs_even_when_restore_fails(monkeypatch):
    calls = _install_fake_backup(monkeypatch, fail=("restore",))
    from pyte.errors import CfgError
    with pytest.raises(CfgError):
        with cfg.backup():
            pass
    assert "release" in calls


def test_backup_restore_failure_does_not_replace_the_body_error(
        monkeypatch):
    _install_fake_backup(monkeypatch, fail=("restore",))
    boom = RuntimeError("the real failure")
    with pytest.raises(RuntimeError) as info:
        with cfg.backup():
            raise boom
    assert info.value is boom
    assert info.value.cleanup_errors
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_cfg.py tests/test_cfg_engine.py -k "saved or backup" -v`
Expected: FAIL. `saved` aborts at the first restore; both contexts let the restore error replace the body's.

- [ ] **Step 3: Fix CfgObject.saved**

In `src/pyte/cfg/_engine.py`, add at the top `import functools` and `from pyte._cleanup import cleanup_all`, then replace the tail of `saved` from `old = ...`:

```python
        old = {a: getattr(self, a) for a in attrs}
        primary = None
        try:
            yield self
        except BaseException as exc:
            primary = exc
            raise
        finally:
            # Reverse order, every attribute attempted: a failing
            # restore must not abandon the rest, nor replace the
            # exception that caused the unwind.
            cleanup_all(
                *[functools.partial(setattr, self, a, v)
                  for a, v in reversed(list(old.items()))],
                primary=primary)
```

Also update the docstring's last sentence, which currently justifies the read-only pre-check by saying a failing restore "would otherwise fail inside the finally and mask the real error" — masking no longer happens; keep the pre-check but say it fails fast instead.

- [ ] **Step 4: Fix the three cfg contexts**

In `src/pyte/cfg/__init__.py`, add `import functools` and `from pyte._cleanup import cleanup_all`.

`backup()`:

```python
@contextmanager
def backup():
    """Snapshot the configuration; restore it on block exit.

    Restore runs whether the block succeeds or raises, and the backup
    name is released either way.  A failure in either step is attached
    to the exception being unwound rather than replacing it.
    """
    name = _backup_create()
    primary = None
    try:
        yield name
    except BaseException as exc:
        primary = exc
        raise
    finally:
        cleanup_all(functools.partial(_backup_restore, name),
                    functools.partial(_backup_release, name),
                    primary=primary)
```

`transaction()` — keep the docstring body but change the summary line to `"""Roll the configuration back if the block raises.`:

```python
    name = _backup_create()
    primary = None
    try:
        yield
    except BaseException as exc:
        primary = exc
        raise
    finally:
        actions = [functools.partial(_backup_release, name)]
        if primary is not None:
            actions.insert(0, functools.partial(_backup_restore, name))
        cleanup_all(*actions, primary=primary)
```

`borrowed_rsrc()` — delete the docstring paragraph beginning "Standard ``finally`` semantics apply", which documents the behavior being fixed:

```python
    set(f"/agent:{owner_agent}/rsrc:{name}", "")
    primary = None
    try:
        grab_rsrc(borrower_agent, name,
                  f"/agent:{borrower_agent}/{subpath}")
        try:
            yield
        except BaseException as exc:
            primary = exc
            raise
        finally:
            cleanup_all(
                functools.partial(release_rsrc, borrower_agent, name),
                primary=primary)
    finally:
        cleanup_all(
            functools.partial(set, f"/agent:{owner_agent}/rsrc:{name}",
                              f"/agent:{owner_agent}/{subpath}"),
            primary=primary)
```

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: all pass. `test_saved_restores_on_exception` and `test_saved_multiple_knobs_all_restored` must still pass unchanged.

- [ ] **Step 6: Lint and commit**

```bash
ruff check src tests setup.py
git add -A
git commit -s -m "cfg: attempt every restore, keep the real exception" -m "CfgObject.saved() restored in insertion order and stopped at the
first failure, leaving later attributes unrestored; backup(),
transaction() and borrowed_rsrc() each let a failing restore replace
the exception being unwound -- borrowed_rsrc even documented it as
expected.

Route all four through cleanup_all(): every action attempted, in
reverse order for saved(), with teardown failures attached to the
primary exception instead of replacing it.

Also correct transaction()'s summary line, which promised
'all-or-nothing rollback' while its own body already explained that
writes apply immediately."
```

---

### Task 6: Retryable teardown for tools, TRex and client/server

**Files:**
- Modify: `src/pyte/tools/_tool.py:206` (`__init__`), `:322-333` (`close`)
- Modify: `src/pyte/tools/trex/batch.py:458-486` (`__init__`), `:602-617` (`close`), `:695-702` (`create`'s finally)
- Modify: `src/pyte/tools/_clientserver.py:46-62` (`serve`)
- Test: `tests/test_tool_helpers.py`, `tests/test_trex_batch_lifecycle.py`, `tests/test_clientserver.py`

**Interfaces:**
- Consumes: `cleanup_all` from Task 4.
- Produces: nothing new.

**Background:** both `close()` implementations set `_closed = True` *before* doing the work, so a failed teardown is permanent and the second call returns having done nothing. Separately `serve()` runs `pco.sleep(ready_delay)` between the bring-up guard and the yield guard; `sleep()` is an RPC, so a timeout there leaks the started server job in all five client/server wrappers.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_tool_helpers.py` (uses the file's plain-Python `FakeJob`/`FakeFilter`/`Demo`):

```python
class _FlakyJob(FakeJob):
    """FakeJob whose destroy() fails until told otherwise."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.destroy_fails = True
        self.destroys = 0

    def destroy(self, *a, **k):
        self.destroys += 1
        self.events.append(("destroy",))
        if self.destroy_fails:
            raise TeError(12)


def test_failed_close_can_be_retried():
    job = _FlakyJob()
    handle = Demo(job, FakeFilter())
    with pytest.raises(TeError):
        handle.close()
    job.destroy_fails = False
    handle.close()
    assert job.destroys == 2      # actually retried


def test_close_runs_after_close_even_if_destroy_fails():
    job = _FlakyJob()
    handle = Demo(job, FakeFilter())
    ran = []
    handle._after_close = lambda: ran.append("after")
    with pytest.raises(TeError):
        handle.close()
    assert ran == ["after"]


def test_successful_close_is_still_idempotent():
    job = FakeJob()
    handle = Demo(job, FakeFilter())
    handle.close()
    handle.close()
    assert [e for e in job.events if e == ("destroy",)] == [("destroy",)]
```

Append to `tests/test_clientserver.py` (uses its plain-Python `FakePco`/`FakeJob`):

```python
def test_readiness_delay_failure_destroys_the_server_job():
    """pco.sleep() is an RPC and can time out; the started job used to
    leak between the bring-up guard and the yield guard."""
    pco = FakePco()

    def _boom(seconds):
        raise TeError(12)

    pco.sleep = _boom
    with pytest.raises(TeError):
        with _clientserver.serve(pco, "srv", [], host="h", port=1,
                                 ready_delay=1.0):
            pass
    assert pco._job.destroyed
```

Match the attribute names `FakePco`/`FakeJob` actually use in that file (check `FakeJob` for `destroyed` vs an events list) and adjust the assertion accordingly. Import `TeError` if the file does not already.

Append to `tests/test_trex_batch_lifecycle.py`:

```python
def test_failed_close_can_be_retried():
    pco = _FakePco()
    trex = None
    with pytest.raises(TeError):
        with batch.create(pco, _batch_opts()) as trex_obj:
            trex = trex_obj
            trex.job.destroy = _raise_te_error
    # the create() CM's own close() already failed; retry must work
    trex.job.destroy = lambda *a, **k: None
    trex.close()
    assert trex._closed
```

Add the small helper `def _raise_te_error(*a, **k): raise TeError(12)` near the file's other helpers, and import `TeError`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_tool_helpers.py tests/test_clientserver.py tests/test_trex_batch_lifecycle.py -k "retried or after_close or readiness or idempotent" -v`
Expected: FAIL. The retry finds `_closed` already true and returns; `_after_close` never runs; the leaked job is never destroyed.

- [ ] **Step 3: Fix ToolHandle.close**

In `src/pyte/tools/_tool.py`, add `from pyte._cleanup import cleanup_all` to the imports, add three flags next to the existing `self._closed = False` at line 206:

```python
        self._stopped = False
        self._job_destroyed = False
        self._after_close_done = False
```

and replace `close()`:

```python
    def close(self) -> None:
        """Stop the tool and destroy the job; idempotent and retryable.

        Tracks the steps that actually completed, so a close() that
        failed part-way retries only what is left.  Setting a _closed
        flag up front (what this replaced) made a failed teardown
        permanent: the job stayed alive and the second call returned
        having done nothing.
        """
        if self._closed:
            return
        from pyte.errors import TeError
        if not self._stopped:
            try:
                self._stop_for_close()
            except TeError:
                pass
            self._stopped = True
        cleanup_all(self._destroy_job_once, self._after_close_once)
        self._closed = True

    def _destroy_job_once(self) -> None:
        if not self._job_destroyed:
            self._job.destroy()
            self._job_destroyed = True

    def _after_close_once(self) -> None:
        if not self._after_close_done:
            self._after_close()
            self._after_close_done = True
```

- [ ] **Step 4: Fix Trex.close and create()**

Apply the identical shape in `src/pyte/tools/trex/batch.py`. Add `self._stopped = False`, `self._job_destroyed = False`, `self._files_removed = False` to `__init__`, then:

```python
    def close(self) -> None:
        """Idempotent, retryable teardown: stop-tolerant destroy, then
        remove the ``/tmp`` yaml and astf json files from the agent.

        DIVERGENCE: C's ``tapi_trex_destroy`` never removes either
        file -- a deliberate leak this port does not reproduce.

        Each step is tracked separately, so a close() whose job
        destroy failed retries only the unfinished work rather than
        marking itself done and leaving the process alive.
        """
        if self._closed:
            return
        if not self._stopped:
            try:
                self.job.stop()
            except TeError:
                pass
            self._stopped = True
        cleanup_all(self._destroy_job_once, self._remove_files_once)
        self._closed = True

    def _destroy_job_once(self) -> None:
        if not self._job_destroyed:
            self.job.destroy()
            self._job_destroyed = True

    def _remove_files_once(self) -> None:
        if not self._files_removed:
            _remove_tmp_files(self._pco, self._yaml_path, self._astf_path)
            self._files_removed = True
```

In `create()`, replace the trailing `finally: trex.close()`:

```python
    primary = None
    try:
        with pco.silent_pass():
            trex._attach_filters(opts)
        yield trex
    except BaseException as exc:
        primary = exc
        raise
    finally:
        cleanup_all(trex.close, primary=primary)
```

Add `from pyte._cleanup import cleanup_all` to the imports.

- [ ] **Step 5: Fix the readiness-delay leak in serve()**

In `src/pyte/tools/_clientserver.py`:

```python
    job = pco.job(program, argv)
    try:
        job.stderr.log(level="WARN")
        job.start()
        # Inside the guard: pco.sleep() is an RPC and can fail, and a
        # failure here used to leak the already-started server job.
        if ready_delay:
            pco.sleep(ready_delay)
    except BaseException:
        job.destroy()
        raise
    primary = None
    try:
        yield Endpoint(host, port)
    except BaseException as exc:
        primary = exc
        raise
    finally:
        from pyte.errors import TeError

        def _stop():
            try:
                job.stop(signal=term)
            except TeError:
                pass

        cleanup_all(_stop, job.destroy, primary=primary)
```

Update the docstring: the sentence "If the server fails to start, the job is destroyed before the exception propagates" now covers the readiness delay too.

- [ ] **Step 6: Run tests**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: all pass. `test_close_is_idempotent` and `test_report_resilences_filters_via_job_quiet_not_rpcserver` must still pass unchanged.

- [ ] **Step 7: Lint and commit**

```bash
ruff check src tests setup.py
git add -A
git commit -s -m "tools: make teardown retryable and non-masking" -m "ToolHandle.close() and Trex.close() set _closed before doing the
work, so a failed teardown was permanent: the job stayed alive and
the next call returned having done nothing.  Track completed steps
instead and set _closed only once they all succeeded.

_clientserver.serve() ran the readiness delay between the bring-up
guard and the yield guard; pco.sleep() is an RPC, so a timeout there
leaked the started server job.  All five client/server wrappers
inherited it.

Route the teardowns through cleanup_all so a failing stop or destroy
no longer replaces the body's exception."
```

---

### Task 7: Close the remaining teardown leaks

**Files:**
- Modify: `src/pyte/job.py:741-766` (`destroy`), `:537-539` (`create`'s stdin step)
- Modify: `src/pyte/tad/csap.py` (`Csap`: add `__del__`)
- Test: `tests/test_job.py`, `tests/test_csap.py`

**Interfaces:**
- Consumes: `cleanup_all` from Task 4.
- Produces: nothing new.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_job.py`, using its `_fake_shim`/`_fake_job` helpers. The local `FakeLib` needs `pyte_job_destroy` and `pyte_job_factory_destroy` entries that record and can be steered to fail; add them if absent, following the file's existing method style:

```python
def test_destroy_frees_the_factory_even_when_job_destroy_fails(
        monkeypatch):
    lib = _fake_shim(monkeypatch)
    lib.job_destroy_rc = 12          # add this knob to FakeLib
    job = Job("fac-h", "job-h", "prog")
    from pyte.errors import TeError
    with pytest.raises(TeError):
        job.destroy()
    assert any(c[0] == "job_factory_destroy" for c in lib.calls)


def test_failed_job_destroy_does_not_retry_the_freed_pointer(
        monkeypatch):
    """TE may already have freed the job; a retry must not hand the
    same pointer back to C."""
    lib = _fake_shim(monkeypatch)
    lib.job_destroy_rc = 12
    job = Job("fac-h", "job-h", "prog")
    from pyte.errors import TeError
    with pytest.raises(TeError):
        job.destroy()
    assert job._h is None


def test_stdin_allocation_failure_destroys_the_partial_job(monkeypatch):
    lib = _fake_shim(monkeypatch)
    lib.alloc_input_rc = 12          # add this knob to FakeLib
    from pyte.errors import TeError
    with pytest.raises(TeError):
        Job.create(_FakeServer(), "cat", [], stdin=True)
    assert any(c[0] == "job_destroy" for c in lib.calls)
    assert any(c[0] == "job_factory_destroy" for c in lib.calls)
```

`Job.create` takes a server whose `_handle()` is passed to `pyte_job_factory_rpc`; add a two-line `_FakeServer` with `_handle()` and `name` if the file has none.

Append to `tests/test_csap.py`, using its `_bare_csap()`:

```python
def test_csap_warns_when_garbage_collected_unclosed(monkeypatch):
    _fake_shim(monkeypatch)
    c = _bare_csap()
    with pytest.warns(ResourceWarning, match="Csap"):
        c.__del__()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_job.py tests/test_csap.py -k "factory or freed_pointer or stdin or garbage" -v`
Expected: FAIL. `destroy()` raises before reaching the factory block and leaves `_h` set; `create()` leaves the job and factory alive; `Csap` has no `__del__`.

- [ ] **Step 3: Fix Job.destroy**

In `src/pyte/job.py`, add `import functools` and `from pyte._cleanup import cleanup_all`, then replace `destroy()`:

```python
    def destroy(self, timeout: float = DEFAULT_TIMEOUT) -> None:
        """Destroy the job (terminating it if needed) and its factory.

        Idempotent, and the factory is freed even when the job destroy
        fails -- it used to be skipped, leaking the factory with no way
        to retry.  Channel, Filter and InputChannel objects created
        from this job are invalidated: TE frees them together with the
        job, so any further use would dereference freed memory in C.
        They raise ClosedResourceError instead.
        """
        cleanup_all(functools.partial(self._destroy_job, timeout),
                    self._destroy_factory)

    def _destroy_job(self, timeout: float) -> None:
        if self._h is None:
            return
        lib = _shim_lib()
        # Clear the handle and invalidate the children BEFORE the call:
        # TE frees them with the job whether or not it reports success,
        # so a retry must never hand the same pointer back to C.
        h, self._h = self._h, None
        self._invalidate_children()
        check(lib.pyte_job_destroy(h, _ms(timeout)),
              f"job.destroy({self.program})")

    def _invalidate_children(self) -> None:
        for child in (self._stdout, self._stderr, self._stdin,
                      *self._filters):
            if child is not None:
                child._h = None
        self._stdout = self._stderr = self._stdin = None
        self._filters.clear()

    def _destroy_factory(self) -> None:
        if self._factory is None:
            return
        lib = _shim_lib()
        f, self._factory = self._factory, None
        check(lib.pyte_job_factory_destroy(f), "job_factory_destroy")
```

- [ ] **Step 4: Fix the stdin allocation leak**

In `src/pyte/job.py`, replace the tail of `create()`:

```python
        job = cls(fac[0], out[0], program)
        try:
            if stdin:
                _ = job.stdin
        except BaseException:
            # The job and factory both exist by now; a failure here
            # used to leak both with no handle to retry from.
            job.destroy()
            raise
        return job
```

- [ ] **Step 5: Add the Csap finalizer**

In `src/pyte/tad/csap.py`, add `import warnings` if absent, and add to `Csap`:

```python
    def __del__(self):
        """Warn about a CSAP that was never destroyed.

        Warn-only, no remote call: at interpreter shutdown the shim may
        already be gone.  Unlike Packet, a Csap has no owner that frees
        it, so one not used as a context manager leaks the agent-side
        CSAP for the whole run.
        """
        if getattr(self, "_handle", None) is not None:
            warnings.warn(f"unclosed {self!r}; use it as a context "
                          "manager or call destroy()",
                          ResourceWarning, stacklevel=2)
```

- [ ] **Step 6: Run tests**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: all pass. If any existing test constructs a `Csap` and drops it, it may now emit `ResourceWarning`; that is correct — have the test destroy it, or assert the warning.

- [ ] **Step 7: Lint and commit**

```bash
ruff check src tests setup.py
git add -A
git commit -s -m "job: free the factory and partial jobs on failure" -m "Job.destroy() raised out of the job destroy before reaching the
factory block, leaking the factory with no way to retry, and
__exit__ never retried.  Job.create(stdin=True) leaked both the job
and the factory when the input-channel allocation failed.

Split destroy() into per-resource steps run through cleanup_all, and
clear the handle and invalidate the children BEFORE the check() so a
failed free never hands the same pointer back to C.

Csap gains a warn-only __del__: unlike Packet it has no owner, so
one not used as a context manager leaked for the whole run."
```

---

### Task 8: Real save/restore for quiet logging

**Files:**
- Modify: `shim/pyte_shim_cdef.h:31,179`
- Modify: `shim/pyte_shim.c` (near `pyte_rpc_set_silent_pass:117` and `pyte_job_set_tracing:1427`)
- Modify: `src/pyte/job.py:709-732` (`tracing`, `quiet`)
- Modify: `src/pyte/rpc/server.py:158-182` (`silent_pass`)
- Test: `tests/test_job.py`, `tests/test_server.py`

**Interfaces:**
- Consumes: nothing.
- Produces: shim functions `int pyte_rpc_get_silent_pass(rcf_rpc_server *rpcs)` and `int pyte_job_get_tracing(tapi_job_t *job)`; Python method `Job.tracing_enabled() -> bool`.

**Background:** `Job.quiet()` restores a hardcoded `True`, so leaving the block permanently un-silences a job created under `pco.silent_pass()`; `trex/batch.py:574-577` documents working around exactly this. `RpcServer.silent_pass()` depth-counts within one wrapper but restores a hardcoded 0.

**Requires a shim rebuild.** The offline tests use file-local fakes and pass without one, so do NOT claim the C side works until you have rebuilt (needs `TE_INSTALL`; see `build_shim.py`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_job.py`. Extend the local `FakeLib` with a tracing store first:

```python
    # add to FakeLib.__init__
    self.tracing = {}

    # add to FakeLib
    def pyte_job_set_tracing(self, h, trace):
        self.tracing[h] = trace
        self.calls.append(("set_tracing", h, trace))

    def pyte_job_get_tracing(self, h):
        return self.tracing.get(h, 1)
```

then:

```python
def test_quiet_restores_the_state_it_found(monkeypatch):
    """A job created under pco.silent_pass() is already silent; leaving
    a quiet() block must not turn its tracing on."""
    lib = _fake_shim(monkeypatch)
    job = _fake_job(handle="job-h")
    lib.tracing["job-h"] = 0            # created silent
    with job.quiet():
        pass
    assert lib.tracing["job-h"] == 0


def test_nested_quiet_does_not_unsilence_the_outer_block(monkeypatch):
    lib = _fake_shim(monkeypatch)
    job = _fake_job(handle="job-h")
    with job.quiet():
        with job.quiet():
            pass
        assert lib.tracing["job-h"] == 0
```

Append to `tests/test_server.py`, extending the silent-pass double already used by `test_silent_pass_sets_and_restores` with a `pyte_rpc_get_silent_pass` returning a settable value:

```python
def test_silent_pass_restores_an_ambient_setting(monkeypatch):
    lib = _fake_silent_shim(monkeypatch)   # the file's existing helper
    lib.silent_pass = 1                    # set by an enclosing block
    srv = _bare_server()
    with srv.silent_pass():
        pass
    assert lib.silent_pass == 1
```

Use whatever the file's existing silent-pass tests already build; extend it rather than adding a second double.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_job.py tests/test_server.py -k "quiet or silent_pass" -v`
Expected: FAIL. `quiet()` restores 1 unconditionally; `silent_pass()` restores 0.

- [ ] **Step 3: Add the shim getters**

In `shim/pyte_shim_cdef.h`, beside each setter:

```c
int pyte_rpc_get_silent_pass(rcf_rpc_server *rpcs);
int pyte_job_get_tracing(tapi_job_t *job);
```

In `shim/pyte_shim.c`, beside each setter:

```c
int
pyte_rpc_get_silent_pass(rcf_rpc_server *rpcs)
{
    /* Read-only accessor so the Python facade can save and restore the
     * state it actually found: silent_pass is one shared field and may
     * have been set by an enclosing block or another wrapper. */
    return rpcs->silent_pass ? 1 : 0;
}

int
pyte_job_get_tracing(tapi_job_t *job)
{
    /* tapi_job_set_tracing() writes !trace to the job and to every
     * channel and filter (tapi_job.c:1635-1646); the job's own flag is
     * the one to save and restore. */
    return tapi_job_get_silent_pass(job) ? 0 : 1;
}
```

If TE exposes no `tapi_job_get_silent_pass`, read the field the way `tapi_job_set_tracing` writes it and say so in the comment.

- [ ] **Step 4: Fix Job.quiet**

In `src/pyte/job.py`:

```python
    def tracing_enabled(self) -> bool:
        """Whether per-call RPC logging is currently on for this job."""
        h = self._handle()
        lib = _shim_lib()
        return bool(lib.pyte_job_get_tracing(h))

    @contextmanager
    def quiet(self):
        """Suppress RPC tracing for the block, restoring what it found.

        Restores the PREVIOUS state, not an unconditional "on": a job
        created inside pco.silent_pass() is already silent, and the old
        hardcoded restore turned its logging on permanently.  Nests.
        """
        if self._h is None:      # mirrors tracing()'s post-destroy no-op
            yield self
            return
        was = self.tracing_enabled()
        self.tracing(False)
        try:
            yield self
        finally:
            self.tracing(was)
```

- [ ] **Step 5: Fix RpcServer.silent_pass**

In `src/pyte/rpc/server.py`, add `self._silent_pass_was = 0` to `__init__` and replace the body:

```python
        lib = _shim_lib()
        h = self._handle()
        if self._silent_pass_depth == 0:
            self._silent_pass_was = lib.pyte_rpc_get_silent_pass(h)
            lib.pyte_rpc_set_silent_pass(h, 1)
        self._silent_pass_depth += 1
        try:
            yield self
        finally:
            self._silent_pass_depth -= 1
            if self._silent_pass_depth == 0:
                lib.pyte_rpc_set_silent_pass(h, self._silent_pass_was)
```

The docstring already claims "the previous state is restored, not forced off" — that becomes true here; leave it.

Note `_bare_server()` in `tests/test_server.py` sets `_silent_pass_depth` by hand; add `_silent_pass_was = 0` there too.

- [ ] **Step 6: Run tests**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 7: Re-examine the downstream workaround**

`src/pyte/tools/trex/batch.py:560-578`'s `report()` docstring explains that its `job.quiet()` re-silences filters that an earlier `job.quiet()` exit turned loud. With `quiet()` restoring the found state, that exit no longer un-silences anything. Read the block, decide whether the bracket is still needed, and either delete it with its comment or update the comment to state the remaining reason. Then run `.venv/bin/python -m pytest tests/test_trex_batch_lifecycle.py -q` — `test_report_resilences_filters_via_job_quiet_not_rpcserver` encodes the old behavior and will need updating either way.

- [ ] **Step 8: Rebuild the shim and verify**

Rebuild with `TE_INSTALL` set (see `build_shim.py`), then confirm both getters are callable from a real session. Do not mark this task done on fake-shim results alone.

- [ ] **Step 9: Lint and commit**

```bash
ruff check src tests setup.py
git add -A
git commit -s -m "job: restore the tracing state quiet() actually found" -m "Job.quiet() restored a hardcoded 'on', so leaving the block
permanently un-silenced a job created under pco.silent_pass() --
tools/trex/batch.py carried a documented workaround for exactly
this.  RpcServer.silent_pass() depth-counted correctly but restored
a hardcoded 0, clobbering any ambient setting.

Neither was fixable in Python: the shim declared only setters.  Add
pyte_rpc_get_silent_pass() and pyte_job_get_tracing(), and save and
restore the real value.

Requires a shim rebuild."
```

---

### Task 9: Write down the two undecided ownership rules

**Files:**
- Modify: `src/pyte/rpc/socket.py:235` (`close`), `src/pyte/rpc/files.py:30-36` (`close`)
- Modify: `src/pyte/test.py:137-146` (`_run_cleanups`)
- Test: `tests/test_socket.py`, `tests/test_test.py`

**Interfaces:**
- Consumes: `cleanup_all` from Task 4.
- Produces: nothing new; two documented decisions and one bug fix.

**Background, part 1.** `RpcSocket.close()` sets `self.fd = -1` *before* checking the result, and `RpcFile.close()` does the same. That is defensible as double-close avoidance, but it means a failed close leaks the agent-side fd with no way to retry, and nobody wrote down which behavior was intended. Pick one and say so in the docstring. The recommendation is to keep the current order (a double close on an fd TE may have already released is worse than a leak, and the agent's exit reclaims fds anyway) and document it — but make that a decision, not an accident.

**Background, part 2.** `test.py:139-142` `_run_cleanups` catches only `Exception`. It is called from inside `start()`'s `finally` (`test.py:256`), so a `BaseException` from a cleanup — a `KeyboardInterrupt`, or the `SystemExit` a cleanup might raise — escapes past `t._env.close()` (`:258`), past `_current = None` (`:266`) and past `sys.exit(result)` (`:267`). The test then exits with an uncaught traceback, an unfreed environment and a module global still pointing at a dead test.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_test.py`:

```python
def test_a_base_exception_in_cleanup_still_frees_the_env(fake_shim):
    """_run_cleanups caught only Exception, so a KeyboardInterrupt in a
    cleanup escaped past env.close() and left _current set."""
    import pyte.test as test_mod
    closed = []

    class _Env:
        def close(self):
            closed.append(True)

    t = test_mod.Test.__new__(test_mod.Test)
    t._cleanups = [(_raise_interrupt, (), {})]
    t._env = _Env()
    ok = t._run_cleanups()
    assert closed == [True] or not ok   # the env is still freed
    assert not ok                       # and the failure is reported


def _raise_interrupt():
    raise KeyboardInterrupt()
```

Match `Test`'s real attribute names and the real `_run_cleanups` signature before writing this — read `src/pyte/test.py:130-150` first and adjust. If `_run_cleanups` does not itself close the env, assert instead that it returns `False` and does not propagate.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_test.py -k base_exception -v`
Expected: FAIL — the `KeyboardInterrupt` propagates out of `_run_cleanups`.

- [ ] **Step 3: Catch BaseException in _run_cleanups**

In `src/pyte/test.py`, widen the `except Exception` to `except BaseException` with a `# noqa: BLE001` and a comment:

```python
            except BaseException as e:  # noqa: BLE001
                # BaseException, not Exception: this runs inside
                # start()'s finally, so an interrupt (or a SystemExit
                # from a cleanup) escaping here would skip env.close()
                # and leave _current pointing at a dead test.
                log.error(f"cleanup {fn!r} failed: {e}")
                ok = False
```

Keep everything else identical: the reversed (LIFO) order, the logging, and `ok = False` so a cleanup failure still turns a passing test into a failure.

- [ ] **Step 4: Decide and document the fd close ordering**

In `src/pyte/rpc/socket.py` and `src/pyte/rpc/files.py`, add to each `close()` docstring:

```python
        """Close the descriptor on the agent; idempotent.

        The fd is marked closed BEFORE the result is checked, so a
        failed close is not retried.  That is deliberate: retrying a
        close on a descriptor TE may already have released risks
        closing an unrelated fd the agent has since reused, which is
        worse than leaking one that the agent's own exit reclaims.
        """
```

If you decide the other way instead, invert the code and say so — but do not leave it undocumented.

- [ ] **Step 5: Pin the decision with a test**

Append to `tests/test_socket.py`:

```python
def test_failed_close_does_not_retry_the_fd(monkeypatch):
    """Documented decision: a close that failed is NOT retried, because
    the agent may have reused the descriptor number since."""

    class _RaisingServer:
        """FakeServer, but _check_call reports the close as failed.

        Raises a plain RuntimeError rather than an RpcError: building
        one calls TeError.__init__, which reaches the shim, and this
        file's FakeLib has no te_errno accessors.  The assertion here
        is about retry semantics, not the exception type.
        """

        _h = "srv-h"

        def _handle(self):
            return self._h

        def _check_call(self, rc, value, ok, where):
            raise RuntimeError(f"close refused: {where}")

    lib = _fake_shim(monkeypatch)
    closes = []
    lib.pyte_rpc_close = lambda h, fd, out: (closes.append(fd), 0)[1]

    sock = RpcSocket(_RaisingServer(), 5)
    with pytest.raises(RuntimeError, match="close refused"):
        sock.close()
    assert sock.fd == -1            # marked closed despite the failure
    sock.close()                    # second call is a no-op...
    assert closes == [5]            # ...not a retry
```

`_RaisingServer` carries `_handle()` because Task 2 routed `close()` through it. `RpcSocket(server, fd)` is the real constructor, used the same way at `tests/test_socket.py:39`.

- [ ] **Step 6: Run tests, lint, commit**

```bash
.venv/bin/python -m pytest tests/ -q
ruff check src tests setup.py
git add -A
git commit -s -m "test: do not let an interrupt skip env teardown" -m "_run_cleanups caught only Exception, and it runs inside start()'s
finally: a KeyboardInterrupt (or a SystemExit raised by a cleanup)
escaped past env.close(), past the _current reset and past
sys.exit(), leaving an unfreed environment and a module global
pointing at a dead test.

Also write down the fd-close ordering rule RpcSocket and RpcFile
both implement but neither documented: the descriptor is marked
closed before the result is checked, so a failed close is not
retried -- retrying risks closing an fd the agent has since reused,
which is worse than leaking one its exit reclaims."

```

---

## Wave 1 exit criteria

- [ ] `.venv/bin/python -m pytest tests/ -q` green, at least 25 tests added.
- [ ] `grep -rn '\._h\b' src/pyte/rpc/ src/pyte/remote.py src/pyte/job.py | grep -v 'self\._h' | grep -v '_handle'` returns nothing.
- [ ] No liveness guard raises a bare `RuntimeError`: check `src/pyte/job.py`, `src/pyte/rpc/iomux.py`, `src/pyte/tad/csap.py`, `src/pyte/trc.py`.
- [ ] Every `finally:` in `src/pyte/` that stops, destroys, closes, restores or releases routes through `cleanup_all`. Audit with `grep -rn -A4 'finally:' src/pyte/ | grep -E 'destroy\(|close\(|_restore|release'`.
- [ ] Shim rebuilt; both new getters callable from a live run.
- [ ] `test.py`'s `_run_cleanups` catches `BaseException`.
- [ ] `RpcSocket.close`/`RpcFile.close` document their ordering rule.
- [ ] `ruff check src tests setup.py` clean.
